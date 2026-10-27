"""Repository ingestion: Python AST + git history -> C1 nodes and edges (A1.4-A1.7).

Emits a revision-stamped, idempotent snapshot. Observed relationships come from
AST structure and git objects; heuristic relationships (name-only call
resolution, test-name coverage, ownership share) are marked inferred with a
confidence. Known limitations are documented in docs/graph/parser-limitations.md
and recorded on every `IngestionResult.limitations`.
"""

from __future__ import annotations

import ast
import subprocess
from collections import Counter, defaultdict
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tracefix.graph.models import (
    Edge,
    Node,
    Provenance,
    content_hash,
    make_entity_id,
    normalize_repo_url,
)

SKIP_DIR_NAMES = {".git", ".venv", "venv", "__pycache__", "build", "dist", ".tox", ".mypy_cache"}
MAX_COMMIT_HISTORY_DEFAULT = 500

LIMITATIONS = [
    "Local (nested) function definitions are not extracted.",
    "CALLS resolves only: same-module name calls, self.<method>/<cls method> inside "
    "the same class, and <import alias>.<function> via import/ImportFrom aliases. "
    "All other dynamic calls are skipped, never guessed.",
    "CALLS resolved by repo-wide unique simple name only are emitted as inferred "
    "(confidence heuristic); ambiguous names are skipped.",
    "COVERED_BY is always inferred (import + name-mention heuristic); no coverage "
    "run artifact is consumed yet.",
    "MODIFIED_IN is File->Commit only; Function->Commit needs hunk-line mapping "
    "and is not emitted.",
    "External/unresolvable imports produce no IMPORTS edge; they appear only in "
    "the File node's imports_declared property.",
    "Git history is bounded to the most recent max_commits commits.",
    "Decorated-function start_line is the def line, not the first decorator line.",
]


class IngestionError(Exception):
    """Ingestion cannot produce a snapshot (e.g. no revision available)."""


@dataclass
class IngestionResult:
    repo: str
    revision: str
    nodes: dict[str, Node]
    edges: list[Edge]
    history_available: bool
    parse_errors: list[dict[str, str]] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)
    limitations: list[str] = field(default_factory=lambda: list(LIMITATIONS))

    def edge_identities(self) -> list[tuple[str, str, str, str]]:
        return [e.identity() for e in self.edges]

    def node_properties(self) -> dict[str, dict[str, Any]]:
        return {eid: dict(n.properties) for eid, n in self.nodes.items()}


@dataclass
class _EdgeSink:
    edges: list[Edge] = field(default_factory=list)
    seen: set[tuple[str, str, str, str]] = field(default_factory=set)

    def add(
        self,
        edge_type: str,
        source_id: str,
        target_id: str,
        provenance: Provenance,
        source: str,
        revision: str,
        confidence: str | None = None,
        **props: Any,
    ) -> None:
        edge = Edge(
            edge_type=edge_type,
            source_id=source_id,
            target_id=target_id,
            provenance=provenance,
            source=source,
            revision=revision,
            confidence=confidence,
            properties=props,
        )
        key = edge.identity()
        if key not in self.seen:
            self.seen.add(key)
            self.edges.append(edge)


def ingest_repository(
    repo_root: Path,
    repo_url: str,
    revision: str | None = None,
    include_history: bool = True,
    max_commits: int = MAX_COMMIT_HISTORY_DEFAULT,
    ingested_at: str | None = None,
) -> IngestionResult:
    """Build a C1 snapshot for one repository revision.

    `revision` defaults to HEAD of `repo_root`; a non-git tree requires an
    explicit 40-char SHA so every emitted entity stays revision-stamped.
    """
    repo_root = repo_root.resolve()
    if not repo_root.is_dir():
        raise IngestionError(f"not a directory: {repo_root}")
    if revision is None:
        revision = git_head(repo_root)
        if revision is None:
            raise IngestionError(
                "revision required: directory is not a git repository (or git failed)"
            )
    stamp = ingested_at or datetime.now(UTC).isoformat()
    repo = normalize_repo_url(repo_url)

    nodes: dict[str, Node] = {}
    sink = _EdgeSink()
    parse_errors: list[dict[str, str]] = []
    module_functions: dict[str, dict[str, str]] = defaultdict(dict)
    class_methods: dict[str, dict[str, str]] = defaultdict(dict)
    pending_calls: dict[str, list[dict[str, str]]] = {}
    module_by_qn: dict[str, str] = {}
    file_alias_maps: dict[str, dict[str, str]] = {}
    repo_file_ids: list[str] = []

    repo_node_id = make_entity_id(repo_url, "Repository", repo)
    nodes[repo_node_id] = Node(
        entity_id=repo_node_id,
        kind="Repository",
        repo=repo,
        revision=revision,
        properties={"url": repo},
        ingested_at=stamp,
    )

    for path in _iter_python_files(repo_root):
        rel = path.relative_to(repo_root).as_posix()
        try:
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            parse_errors.append({"path": rel, "error": f"unreadable: {exc}"})
            continue
        module_qn = module_qualified_name(rel)
        tree: ast.Module | None
        try:
            tree = ast.parse(source, filename=rel)
        except SyntaxError as exc:
            parse_errors.append(
                {"path": rel, "error": f"syntax error: {exc.msg} (line {exc.lineno})"}
            )
            tree = None

        file_id = make_entity_id(repo_url, "File", rel)
        nodes[file_id] = Node(
            entity_id=file_id,
            kind="File",
            repo=repo,
            revision=revision,
            content_hash=content_hash(source),
            properties={
                "path": rel,
                "imports_declared": collect_import_declarations(tree),
            },
            ingested_at=stamp,
        )
        repo_file_ids.append(file_id)

        module_id = make_entity_id(repo_url, "Module", module_qn)
        if module_id not in nodes:
            nodes[module_id] = Node(
                entity_id=module_id,
                kind="Module",
                repo=repo,
                revision=revision,
                content_hash=content_hash(source),
                properties={
                    "qualified_name": module_qn,
                    "path": rel,
                    "is_package": rel.endswith("__init__.py"),
                },
                ingested_at=stamp,
            )
            module_by_qn[module_qn] = module_id
            sink.add("CONTAINS", file_id, module_id, Provenance.OBSERVED, "python-ast", revision)

        if tree is None:
            continue
        file_alias_maps[rel] = collect_alias_map(tree)
        lines = source.splitlines()
        _walk_definitions(
            tree.body,
            ctx=_WalkCtx(
                repo_url=repo_url,
                repo=repo,
                revision=revision,
                stamp=stamp,
                module_qn=module_qn,
                module_id=module_id,
                path=rel,
                lines=lines,
                is_test_file=is_test_file(rel),
                nodes=nodes,
                sink=sink,
                module_functions=module_functions,
                class_methods=class_methods,
                pending_calls=pending_calls,
            ),
        )

    _resolve_import_edges(repo_url, nodes, sink, revision, module_by_qn)
    _resolve_call_edges(
        sink, revision, nodes, module_functions, class_methods, pending_calls, file_alias_maps
    )
    _add_coverage_edges(sink, revision, nodes, source_root=repo_root)

    history_available = False
    if include_history:
        history_available = _add_history(
            repo_root=repo_root,
            repo_url=repo_url,
            revision=revision,
            stamp=stamp,
            nodes=nodes,
            sink=sink,
            max_commits=max_commits,
            repo_file_ids=repo_file_ids,
            repo=repo,
        )

    return IngestionResult(
        repo=repo,
        revision=revision,
        nodes=nodes,
        edges=sink.edges,
        history_available=history_available,
        parse_errors=parse_errors,
        stats=_stats(nodes, sink.edges),
    )


# --------------------------------------------------------------------------- ast


@dataclass
class _WalkCtx:
    repo_url: str
    repo: str
    revision: str
    stamp: str
    module_qn: str
    module_id: str
    path: str
    lines: list[str]
    is_test_file: bool
    nodes: dict[str, Node]
    sink: _EdgeSink
    module_functions: dict[str, dict[str, str]]
    class_methods: dict[str, dict[str, str]]
    pending_calls: dict[str, list[dict[str, str]]]
    parent_class_qn: str | None = None


def _walk_definitions(body: list[ast.stmt], ctx: _WalkCtx) -> None:
    for stmt in body:
        if isinstance(stmt, ast.ClassDef):
            qn = (
                f"{ctx.parent_class_qn}.{stmt.name}"
                if ctx.parent_class_qn
                else f"{ctx.module_qn}.{stmt.name}"
            )
            parent_id = (
                make_entity_id(ctx.repo_url, "Class", ctx.parent_class_qn)
                if ctx.parent_class_qn
                else ctx.module_id
            )
            node_id = make_entity_id(ctx.repo_url, "Class", qn)
            ctx.nodes[node_id] = Node(
                entity_id=node_id,
                kind="Class",
                repo=ctx.repo,
                revision=ctx.revision,
                properties={
                    "qualified_name": qn,
                    "path": ctx.path,
                    "start_line": stmt.lineno,
                    "end_line": stmt.end_lineno or stmt.lineno,
                    "base_classes_declared": [ast.unparse(b) for b in stmt.bases],
                },
                ingested_at=ctx.stamp,
            )
            ctx.sink.add(
                "CONTAINS", parent_id, node_id, Provenance.OBSERVED, "python-ast", ctx.revision
            )
            _walk_definitions(stmt.body, _WalkCtx(**{**ctx.__dict__, "parent_class_qn": qn}))
        elif isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
            qn = (
                f"{_parent_class_qn(ctx)}.{stmt.name}"
                if _parent_class_qn(ctx)
                else f"{ctx.module_qn}.{stmt.name}"
            )
            kind = "Test" if ctx.is_test_file and stmt.name.startswith("test_") else "Function"
            node_id = make_entity_id(ctx.repo_url, kind, qn)
            segment = "\n".join(ctx.lines[stmt.lineno - 1 : (stmt.end_lineno or stmt.lineno)])
            ctx.nodes[node_id] = Node(
                entity_id=node_id,
                kind=kind,
                repo=ctx.repo,
                revision=ctx.revision,
                content_hash=content_hash(segment),
                properties={
                    "qualified_name": qn,
                    "path": ctx.path,
                    "start_line": stmt.lineno,
                    "end_line": stmt.end_lineno or stmt.lineno,
                    "is_method": _parent_class_qn(ctx) is not None,
                    "is_coroutine": isinstance(stmt, ast.AsyncFunctionDef),
                    "decorators_declared": [ast.unparse(d) for d in stmt.decorator_list],
                    "signature": f"{stmt.name}({ast.unparse(stmt.args)})",
                },
                ingested_at=ctx.stamp,
            )
            parent_class = _parent_class_qn(ctx)
            if parent_class is not None:
                ctx.class_methods[parent_class][stmt.name] = node_id
                class_id = make_entity_id(ctx.repo_url, "Class", parent_class)
                ctx.sink.add(
                    "CONTAINS", class_id, node_id, Provenance.OBSERVED, "python-ast", ctx.revision
                )
            else:
                ctx.module_functions[ctx.module_qn][stmt.name] = node_id
                ctx.sink.add(
                    "CONTAINS",
                    ctx.module_id,
                    node_id,
                    Provenance.OBSERVED,
                    "python-ast",
                    ctx.revision,
                )
            ctx.pending_calls[node_id] = collect_calls(stmt)


def _parent_class_qn(ctx: _WalkCtx) -> str | None:
    return ctx.parent_class_qn


def module_qualified_name(rel_path: str) -> str:
    parts = rel_path.split("/")
    if parts and parts[0] == "src":
        parts = parts[1:]
    if parts and parts[-1] == "__init__.py":
        parts = parts[:-1]
    else:
        parts[-1] = parts[-1].removesuffix(".py")
    return ".".join(p for p in parts if p)


def is_test_file(rel_path: str) -> bool:
    name = rel_path.rsplit("/", 1)[-1]
    parts = rel_path.split("/")
    return (
        name.startswith("test_")
        or name.endswith("_test.py")
        or "tests" in parts[:-1]
        or "test" in parts[:-1]
    )


def collect_import_declarations(tree: ast.AST | None) -> list[str]:
    if tree is None:
        return []
    declared: list[str] = []
    for stmt in ast.walk(tree):
        if isinstance(stmt, ast.Import):
            for alias in stmt.names:
                declared.append(alias.name)
        elif isinstance(stmt, ast.ImportFrom):
            prefix = "." * (stmt.level or 0)
            declared.append(f"{prefix}{stmt.module or ''}")
    return sorted(set(declared))


def collect_alias_map(tree: ast.AST) -> dict[str, str]:
    """Local alias -> dotted module for absolute imports (module-level or any)."""
    aliases: dict[str, str] = {}
    for stmt in ast.walk(tree):
        if isinstance(stmt, ast.Import):
            for alias in stmt.names:
                local = alias.asname or alias.name.split(".")[0]
                aliases[local] = alias.name if alias.asname else alias.name.split(".")[0]
        elif isinstance(stmt, ast.ImportFrom) and (stmt.level or 0) == 0 and stmt.module:
            for alias in stmt.names:
                if alias.name == "*":
                    continue
                aliases[alias.asname or alias.name] = f"{stmt.module}.{alias.name}"
    return aliases


def collect_calls(func_def: ast.FunctionDef | ast.AsyncFunctionDef) -> list[dict[str, str]]:
    calls: list[dict[str, str]] = []
    for n in ast.walk(func_def):
        if not isinstance(n, ast.Call):
            continue
        func = n.func
        if isinstance(func, ast.Name):
            calls.append({"style": "name", "name": func.id})
        elif isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
            if func.value.id in ("self", "cls"):
                calls.append({"style": "self", "name": func.attr})
            else:
                calls.append({"style": "module_attr", "name": f"{func.value.id}.{func.attr}"})
    return calls


def _resolve_import_edges(
    repo_url: str,
    nodes: dict[str, Node],
    sink: _EdgeSink,
    revision: str,
    module_by_qn: dict[str, str],
) -> None:
    """Emit IMPORTS only for in-repo resolvable modules (observed)."""
    for node in list(nodes.values()):
        if node.kind != "File":
            continue
        source_module = module_qualified_name(node.properties["path"])
        source_module_id = make_entity_id(repo_url, "Module", source_module)
        for declared in node.properties.get("imports_declared", []):
            target_qn = resolve_import_to_module(declared, source_module)
            if target_qn is None:
                continue
            target_id = module_by_qn.get(target_qn)
            if target_id is None or target_id == source_module_id:
                continue
            sink.add(
                "IMPORTS",
                source_module_id,
                target_id,
                Provenance.OBSERVED,
                "import-resolution",
                revision,
            )


def resolve_import_to_module(declared: str, source_module: str) -> str | None:
    """Map a declared import to an in-repo dotted module path, or None."""
    if declared.startswith("."):
        level = len(declared) - len(declared.lstrip("."))
        rest = declared[level:]
        base_parts = source_module.split(".")[:-1]
        up = level - 1
        if up > len(base_parts):
            return None
        base = base_parts[: len(base_parts) - up] if up else base_parts
        if rest:
            return ".".join(base + rest.split("."))
        return ".".join(base) if base else None
    return declared or None


def _resolve_call_edges(
    sink: _EdgeSink,
    revision: str,
    nodes: dict[str, Node],
    module_functions: dict[str, dict[str, str]],
    class_methods: dict[str, dict[str, str]],
    pending_calls: dict[str, list[dict[str, str]]],
    file_alias_maps: dict[str, dict[str, str]],
) -> None:
    simple_name_index: dict[str, list[str]] = defaultdict(list)
    for funcs in module_functions.values():
        for name, nid in funcs.items():
            simple_name_index[name].append(nid)
    for methods in class_methods.values():
        for name, nid in methods.items():
            simple_name_index[name].append(nid)

    for node_id, calls in pending_calls.items():
        node = nodes.get(node_id)
        if node is None:
            continue
        path = str(node.properties["path"])
        source_module = module_qualified_name(path)
        enclosing_class = _enclosing_class_qn(str(node.properties["qualified_name"]))
        aliases = file_alias_maps.get(path, {})
        for call in calls:
            resolved = _resolve_call(
                call,
                source_module_funcs=module_functions.get(source_module, {}),
                class_methods=class_methods.get(enclosing_class, {}) if enclosing_class else {},
                aliases=aliases,
                module_functions=module_functions,
                simple_name_index=simple_name_index,
            )
            if resolved is None:
                continue
            target_id, provenance, confidence = resolved
            sink.add(
                "CALLS",
                node_id,
                target_id,
                provenance,
                "name-resolution" if provenance is Provenance.OBSERVED else "name-heuristic",
                revision,
                confidence=confidence,
            )


def _enclosing_class_qn(qualified_name: str) -> str | None:
    parts = qualified_name.split(".")
    if len(parts) < 2:
        return None
    if parts[-2][:1].isupper():
        return ".".join(parts[:-1])
    return None


def _resolve_call(
    call: dict[str, str],
    *,
    source_module_funcs: dict[str, str],
    class_methods: dict[str, str],
    aliases: dict[str, str],
    module_functions: dict[str, dict[str, str]],
    simple_name_index: dict[str, list[str]],
) -> tuple[str, Provenance, str] | None:
    style, name = call["style"], call["name"]
    if style == "name":
        if name in source_module_funcs:
            return source_module_funcs[name], Provenance.OBSERVED, "resolved"
        alias_target = aliases.get(name)
        if alias_target and "." in alias_target:
            mod, attr = alias_target.rsplit(".", 1)
            target = module_functions.get(mod, {}).get(attr)
            if target is not None:
                return target, Provenance.OBSERVED, "resolved"
        candidates = simple_name_index.get(name, [])
        if len(candidates) == 1:
            return candidates[0], Provenance.INFERRED, "heuristic"
        return None
    if style == "self":
        target = class_methods.get(name)
        return (target, Provenance.OBSERVED, "resolved") if target else None
    if style == "module_attr":
        alias, attr = name.split(".", 1)
        module_qn = aliases.get(alias)
        if module_qn is None:
            return None
        target = module_functions.get(module_qn, {}).get(attr)
        if target is None and alias in module_functions:
            target = module_functions[alias].get(attr)
        return (target, Provenance.OBSERVED, "resolved") if target else None
    return None


def _add_coverage_edges(
    sink: _EdgeSink,
    revision: str,
    nodes: dict[str, Node],
    source_root: Path,
) -> None:
    """COVERED_BY heuristic: a Test covers a Function when the test file
    references the function's module and mentions the function's simple name."""
    tests = [n for n in nodes.values() if n.kind == "Test"]
    functions = [n for n in nodes.values() if n.kind == "Function"]
    test_text: dict[str, str] = {}
    for test in tests:
        path = source_root / str(test.properties["path"])
        try:
            test_text[test.entity_id] = path.read_text(encoding="utf-8")
        except OSError:
            test_text[test.entity_id] = ""
    for test in tests:
        test_module = module_qualified_name(str(test.properties["path"]))
        text = test_text[test.entity_id]
        for func in functions:
            func_module = module_qualified_name(str(func.properties["path"]))
            if func_module == test_module:
                continue
            simple = str(func.properties["qualified_name"]).rsplit(".", 1)[-1]
            mentions_module = func_module in text or func_module.split(".")[0] in text
            if mentions_module and simple in text:
                sink.add(
                    "COVERED_BY",
                    func.entity_id,
                    test.entity_id,
                    Provenance.INFERRED,
                    "test-name-convention",
                    revision,
                    confidence="heuristic",
                )


# ------------------------------------------------------------------------ history


def _add_history(
    *,
    repo_root: Path,
    repo_url: str,
    repo: str,
    revision: str,
    stamp: str,
    nodes: dict[str, Node],
    sink: _EdgeSink,
    max_commits: int,
    repo_file_ids: list[str],
) -> bool:
    commits = git_commits(repo_root, max_commits)
    if commits is None:
        return False
    file_touch_counts: dict[str, Counter[str]] = defaultdict(Counter)
    for commit in commits:
        sha = commit["sha"]
        person_key = commit["email"].lower()
        person_id = make_entity_id(repo_url, "Person", person_key)
        if person_id not in nodes:
            nodes[person_id] = Node(
                entity_id=person_id,
                kind="Person",
                repo=repo,
                revision=revision,
                properties={"identity": person_key, "name": commit["author"]},
                ingested_at=stamp,
            )
        commit_id = make_entity_id(repo_url, "Commit", sha)
        nodes[commit_id] = Node(
            entity_id=commit_id,
            kind="Commit",
            repo=repo,
            revision=revision,
            properties={
                "sha": sha,
                "author_person": person_id,
                "committed_at": commit["committed_at"],
                "message": commit["subject"],
                "parent_shas": commit["parents"].split() if commit["parents"] else [],
            },
            ingested_at=stamp,
        )
        sink.add("AUTHORED_BY", commit_id, person_id, Provenance.OBSERVED, "git-log", revision)
        for rel in commit["files"]:
            file_id = make_entity_id(repo_url, "File", rel)
            if file_id in nodes:
                sink.add(
                    "MODIFIED_IN",
                    file_id,
                    commit_id,
                    Provenance.OBSERVED,
                    "git-log",
                    revision,
                )
                file_touch_counts[rel][person_key] += 1

    for node_id in repo_file_ids:
        rel = str(nodes[node_id].properties["path"])
        counts = file_touch_counts.get(rel)
        if not counts:
            continue
        top_email, touches = counts.most_common(1)[0]
        total = sum(counts.values())
        person_id = make_entity_id(repo_url, "Person", top_email)
        if person_id not in nodes:
            continue
        sink.add(
            "OWNED_BY",
            node_id,
            person_id,
            Provenance.INFERRED,
            "git-history-ownership-heuristic",
            revision,
            confidence="heuristic",
            weight=round(touches / total, 4),
        )
    return True


def git_head(repo_root: Path) -> str | None:
    try:
        out = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if out.returncode != 0:
        return None
    sha = out.stdout.strip()
    return sha if len(sha) == 40 else None


def git_commits(repo_root: Path, max_commits: int) -> list[dict[str, Any]] | None:
    fmt = "%H%x00%an%x00%ae%x00%aI%x00%P%x00%s"
    try:
        log = subprocess.run(
            [
                "git",
                "-C",
                str(repo_root),
                "log",
                f"-n{max_commits}",
                f"--format={fmt}",
                "--name-only",
            ],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if log.returncode != 0:
        return None
    return _parse_git_log(log.stdout)


def _parse_git_log(raw: str) -> list[dict[str, Any]]:
    commits: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for line in raw.splitlines():
        if "\x00" in line:
            sha, author, email, committed_at, parents, subject = line.split("\x00", 5)
            current = {
                "sha": sha,
                "author": author,
                "email": email,
                "committed_at": committed_at,
                "parents": parents,
                "subject": subject,
                "files": [],
            }
            commits.append(current)
        elif line.strip() and current is not None:
            current["files"].append(line.strip())
    return commits


def _stats(nodes: dict[str, Node], edges: list[Edge]) -> dict[str, Any]:
    by_kind = Counter(n.kind for n in nodes.values())
    by_edge = Counter(e.edge_type for e in edges)
    by_prov = Counter(e.provenance.value for e in edges)
    return {
        "nodes_by_kind": dict(sorted(by_kind.items())),
        "edges_by_type": dict(sorted(by_edge.items())),
        "edges_by_provenance": dict(sorted(by_prov.items())),
        "node_count": len(nodes),
        "edge_count": len(edges),
    }


def _iter_python_files(repo_root: Path) -> Iterator[Path]:
    for path in sorted(repo_root.rglob("*.py")):
        rel_parts = path.relative_to(repo_root).parts
        if any(part in SKIP_DIR_NAMES or part.startswith(".") for part in rel_parts):
            continue
        yield path
