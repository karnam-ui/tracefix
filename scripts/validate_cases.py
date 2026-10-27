#!/usr/bin/env python
"""D8 case-set validator: SWE-bench `psf/requests` instances -> frozen candidate pool.

For each upstream instance this checks, against the local clone:

1. the recorded base commit exists;
2. the gold `patch` applies cleanly at the base commit;
3. every FAIL_TO_PASS test file exists at the base commit or is created by
   the test patch;
4. provisional ground-truth files/functions can be derived from the applied
   gold patch (enclosing-function-of-hunk; **provisional pending Q-B7**);
5. license and pre-cutoff contamination flags.

Output is written to eval/cases/requests_swe_bench_candidates.json together with
a case-set fingerprint (case_id, revision) so results stay comparable per
contracts/evaluation.json. No metric is computed here: this only freezes a
candidate pool. Ground truth is explicitly marked provisional.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import warnings
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CLONE = REPO_ROOT / "data" / "repos" / "requests"
CONTRACT = REPO_ROOT / "contracts" / "evaluation.json"
RAW_ROWS_ENV = "TF_SWEBENCH_ROWS"
DEFAULT_ROWS = REPO_ROOT / "eval" / "cases" / "source" / "swebench_requests_rows.json"
DEFAULT_OUT = REPO_ROOT / "eval" / "cases" / "requests_swe_bench_candidates.json"

MODEL_CUTOFF = datetime(2024, 1, 1, tzinfo=UTC)
HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
DIFF_FILE_RE = re.compile(r"^\+\+\+ b/(.+)$", re.MULTILINE)


@dataclass
class CaseRecord:
    case_id: str
    repo: str
    revision: str
    bug_report: str
    ground_truth_files: list[str] = field(default_factory=list)
    ground_truth_functions: list[str] = field(default_factory=list)
    localizable: bool = False
    excluded_reason: str | None = None
    dataset_source: str = "swe-bench"
    dataset_instance_id: str = ""
    fix_commit: str | None = None
    fail_to_pass_tests: list[str] = field(default_factory=list)
    ground_truth_policy: str = "provisional-enclosing-function-of-gold-hunk (pending Q-B7)"
    pre_cutoff: bool = True
    created_at: str = ""
    validation: dict[str, object] = field(default_factory=dict)


def _git(cwd: Path, *args: str, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(cwd), *args], capture_output=True, text=True, timeout=timeout, check=False
    )


def parse_patch_new_spans(patch: str) -> dict[str, list[tuple[int, int]]]:
    """Map each changed path to its post-image line intervals (hunk fallback)."""
    spans: dict[str, list[tuple[int, int]]] = {}
    current: str | None = None
    for line in patch.splitlines():
        if line.startswith("+++ b/"):
            current = line[6:]
            spans.setdefault(current, [])
            continue
        if line.startswith("--- ") or line.startswith("+++ "):
            continue
        match = HUNK_RE.match(line)
        if match and current is not None:
            new_start = int(match.group(3))
            new_len = int(match.group(4) or "1")
            spans[current].append((new_start, max(new_len, 1)))
    return spans


def parse_changed_lines(patch: str) -> dict[str, list[int]]:
    """Post-image line numbers of added ('+') lines, per changed path.

    More precise than full hunk spans for ground-truth attribution; callers fall
    back to `parse_patch_new_spans` when a file has only deletions/renames.
    """
    changed: dict[str, list[int]] = {}
    current: str | None = None
    new_line = 0
    for line in patch.splitlines():
        if line.startswith("+++ b/"):
            current = line[6:]
            changed.setdefault(current, [])
            continue
        if line.startswith("--- ") or line.startswith("+++ "):
            continue
        match = HUNK_RE.match(line)
        if match:
            new_line = int(match.group(3))
            continue
        if current is None:
            continue
        if line.startswith("+"):
            changed[current].append(new_line)
            new_line += 1
        elif line.startswith("-"):
            continue
        elif line.startswith("\\"):
            continue
        else:
            new_line += 1
    return changed


def enclosing_functions(source: str, module_qn: str, line: int) -> list[str]:
    """Qualified names of the innermost Function/Class enclosing `line`."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    best: list[tuple[int, str]] = []

    def visit(node: ast.AST, prefix: str, depth: int) -> None:
        for child in ast.iter_child_nodes(node):
            name = getattr(child, "name", None)
            is_def = isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            child_prefix = prefix
            if is_def and name is not None:
                child_prefix = f"{prefix}.{name}" if prefix else name
                start = child.lineno
                end = getattr(child, "end_lineno", start) or start
                if start <= line <= end:
                    best.append((depth, child_prefix))
            visit(child, child_prefix, depth + 1)

    visit(tree, module_qn, 0)
    if not best:
        return []
    innermost = max(depth for depth, _ in best)
    return sorted({qn for depth, qn in best if depth == innermost})


def module_qn_for(path: str) -> str:
    parts = path.split("/")
    if parts and parts[-1].endswith(".py"):
        parts[-1] = parts[-1][:-3]
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(p for p in parts if p)


def derive_ground_truth(worktree: Path, patch: str) -> tuple[list[str], list[str], list[str]]:
    spans = parse_patch_new_spans(patch)
    added = parse_changed_lines(patch)
    files = sorted(spans)
    functions: list[str] = []
    errors: list[str] = []
    for rel in files:
        target = worktree / rel
        if not target.exists():
            errors.append(f"changed file missing after apply: {rel}")
            continue
        source = target.read_text(encoding="utf-8", errors="replace")
        module_qn = module_qn_for(rel)
        lines = added.get(rel) or []
        if not lines:
            for start, length in spans[rel]:
                lines.extend(range(start, start + length))
        for line in lines:
            functions.extend(enclosing_functions(source, module_qn, line))
    return files, sorted(set(functions)), errors


def validate_case(worktree: Path, row: dict) -> CaseRecord:
    case_id = row["instance_id"]
    base_commit = row["base_commit"]
    record = CaseRecord(
        case_id=case_id,
        repo="https://github.com/psf/requests",
        revision=base_commit,
        bug_report=row.get("problem_statement", ""),
        dataset_instance_id=case_id,
        fix_commit=row.get("fix_commit") or None,
        created_at=row.get("created_at", ""),
    )
    try:
        record.fail_to_pass_tests = json.loads(row.get("FAIL_TO_PASS") or "[]")
        pass_to_pass = json.loads(row.get("PASS_TO_PASS") or "[]")
    except json.JSONDecodeError as exc:
        record.validation["error"] = f"unparseable test lists: {exc}"
        record.excluded_reason = "invalid-upstream-fields"
        return record

    created = row.get("created_at", "")
    if created:
        record.pre_cutoff = datetime.fromisoformat(created.replace("Z", "+00:00")) < MODEL_CUTOFF

    exists = _git(CLONE, "cat-file", "-e", f"{base_commit}^{{commit}}").returncode == 0
    record.validation["base_commit_exists"] = exists
    if not exists:
        record.excluded_reason = "base-commit-missing-in-local-clone"
        return record

    checkout = _git(worktree, "checkout", "-f", "--detach", base_commit)
    if checkout.returncode != 0:
        record.excluded_reason = "base-commit-checkout-failed"
        record.validation["error"] = checkout.stderr.strip()
        return record

    test_files = sorted({tid.split("::", 1)[0] for tid in record.fail_to_pass_tests})
    created_by_test_patch = set(DIFF_FILE_RE.findall(row.get("test_patch", "")))
    missing = [
        f for f in test_files if not (worktree / f).exists() and f not in created_by_test_patch
    ]
    record.validation["fail_to_pass_files"] = test_files
    record.validation["missing_test_files"] = missing
    if missing:
        record.excluded_reason = "fail-to-pass-test-file-missing-and-not-in-test-patch"

    patch = row.get("patch", "")
    with tempfile.NamedTemporaryFile("w", suffix=".patch", delete=False) as handle:
        handle.write(patch)
        patch_path = handle.name
    check = _git(worktree, "apply", "--check", patch_path)
    record.validation["gold_patch_applies"] = check.returncode == 0
    if check.returncode != 0:
        record.validation["patch_error"] = check.stderr.strip()
        if record.excluded_reason is None:
            record.excluded_reason = "gold-patch-does-not-apply"
        Path(patch_path).unlink(missing_ok=True)
        return record

    apply = _git(worktree, "apply", patch_path)
    Path(patch_path).unlink(missing_ok=True)
    if apply.returncode != 0:
        record.excluded_reason = record.excluded_reason or "gold-patch-apply-failed"
        return record

    files, functions, gt_errors = derive_ground_truth(worktree, patch)
    record.ground_truth_files = files
    record.ground_truth_functions = functions
    record.validation["ground_truth_errors"] = gt_errors
    record.validation["pass_to_pass_count"] = len(pass_to_pass)
    record.localizable = bool(files and functions)
    if not record.localizable and record.excluded_reason is None:
        record.excluded_reason = "no-enclosing-function-derived-from-gold-hunk"
    _git(worktree, "checkout", "-f", "--detach", base_commit)
    return record


def fingerprint(cases: list[CaseRecord], contract_version: str) -> str:
    pairs = sorted((c.case_id, c.revision) for c in cases)
    payload = json.dumps([pairs, contract_version], separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def main(argv: list[str]) -> int:
    warnings.filterwarnings("ignore", category=SyntaxWarning)
    rows_path = Path(argv[1]) if len(argv) > 1 else Path(os.environ.get(RAW_ROWS_ENV, DEFAULT_ROWS))
    out_path = Path(argv[2]) if len(argv) > 2 else DEFAULT_OUT
    if not rows_path.is_file():
        print(
            f"raw rows not found: {rows_path}\n"
            f"fetch the psf/requests SWE-bench rows from the HF datasets-server "
            f"or set {RAW_ROWS_ENV} / pass a path",
            file=sys.stderr,
        )
        return 2
    if not CLONE.is_dir():
        print(f"clone not found: {CLONE}", file=sys.stderr)
        return 2
    rows = json.loads(rows_path.read_text(encoding="utf-8"))
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    contract_version = contract["version"]

    worktree = Path(tempfile.mkdtemp(prefix="tracefix-validate-"))
    add = _git(CLONE, "worktree", "add", "--detach", str(worktree), "HEAD")
    if add.returncode != 0:
        print(f"worktree add failed: {add.stderr}", file=sys.stderr)
        return 2

    records: list[CaseRecord] = []
    try:
        for row in rows:
            records.append(validate_case(worktree, row))
    finally:
        _git(CLONE, "worktree", "remove", "--force", str(worktree))

    localizable = [c for c in records if c.localizable]
    excluded = [c for c in records if not c.localizable]
    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "dataset_source": "swe-bench",
        "repo": "https://github.com/psf/requests",
        "license": "Apache-2.0",
        "evaluation_contract_version": contract_version,
        "case_set_fingerprint": fingerprint(localizable, contract_version),
        "ground_truth_status": "provisional (pending Q-B7)",
        "counts": {
            "total": len(records),
            "localizable": len(localizable),
            "excluded": len(excluded),
            "pre_cutoff": sum(1 for c in records if c.pre_cutoff),
        },
        "excluded_tally": {
            reason: sum(1 for c in excluded if c.excluded_reason == reason)
            for reason in sorted({c.excluded_reason for c in excluded if c.excluded_reason})
        },
        "cases": [asdict(c) for c in records],
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    print(json.dumps(payload["counts"], indent=2))
    print(f"fingerprint: {payload['case_set_fingerprint']}")
    print(f"wrote: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
