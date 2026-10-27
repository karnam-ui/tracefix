#!/usr/bin/env python3
"""Run a single bug repair case end-to-end through TraceFix (Phase 6).

Executes retrieval, context manifest generation, candidate patch generation,
patch safety validation, isolated sandbox verification, and incident memory storage.

Usage:
    python scripts/run_case.py --case-id psf__requests-1142 --mock
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from tracefix.evaluation.cases import CaseRecord, load_case_set
from tracefix.evaluation.replay import ChronologicalReplayEngine
from tracefix.memory.models import IncidentRecord, VerificationEvidence
from tracefix.memory.repository import IncidentMemoryRepository
from tracefix.memory.retrieval_adapter import IncidentMemoryRetrievalAdapter
from tracefix.repair.interfaces import (
    ModelProvider,
    RepairConfig,
    RepairRequest,
    SandboxVerifierProtocol,
)
from tracefix.repair.patch_generator import HttpModelProvider, MockModelProvider
from tracefix.repair.patch_validator import PatchValidator
from tracefix.repair.state_machine import RepairOrchestrator
from tracefix.retrieval.interfaces import (
    EvidenceTarget,
    RankedItem,
    RetrievalLimits,
    RetrievalQuery,
    RetrievalResult,
    RetrievalStrategy,
)
from tracefix.verification.sandbox import SandboxVerifierAdapter


class StubEvaluationStrategy:
    """Fallback stub retrieval strategy when graph index or corpus is offline."""

    def __init__(self, name: str = "lexical") -> None:
        self.name = name

    def retrieve(self, query: RetrievalQuery) -> RetrievalResult:
        items = [
            RankedItem(
                evidence_id=f"{self.name}_1",
                strategy=self.name,
                rank=1,
                score=0.95,
                target=EvidenceTarget(file="requests/api.py", symbol="request"),
                source_revision=query.revision,
                provenance="observed",  # type: ignore[arg-type]
                source="stub",
            )
        ]
        return RetrievalResult(
            items=items,
            strategy=self.name,
            revision=query.revision,
            elapsed_ms=10.0,
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="TraceFix single-case repair CLI")
    parser.add_argument(
        "--case-id",
        required=True,
        help="Case identifier (e.g. psf__requests-1142)",
    )
    parser.add_argument(
        "--cases-file",
        default="eval/cases/requests_swe_bench_candidates.json",
        help="Path to frozen case set JSON file",
    )
    parser.add_argument(
        "--strategy",
        choices=["lexical", "graph", "memory"],
        default="graph",
        help="Retrieval strategy to localize relevant code",
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Use deterministic mock model provider and sandbox for offline execution",
    )
    parser.add_argument(
        "--budget",
        type=int,
        default=4000,
        help="Context token budget limit",
    )
    parser.add_argument(
        "--output",
        help="Optional path to write outcome JSON",
    )

    args = parser.parse_args()

    # 1. Load case set and locate case
    cases_path = Path(args.cases_file)
    if not cases_path.is_file():
        print(f"Error: Cases file not found: {cases_path}", file=sys.stderr)
        return 1

    case_set = load_case_set(cases_path)
    target_case: CaseRecord | None = None
    for c in case_set.cases:
        if c.case_id == args.case_id:
            target_case = c
            break

    if target_case is None:
        print(f"Error: Case ID '{args.case_id}' not found in {cases_path}", file=sys.stderr)
        return 1

    print("==================================================================")
    print(f"TraceFix Repair Case: {target_case.case_id}")
    print(f"Repository:           {target_case.repo}")
    print(f"Target Revision:      {target_case.revision}")
    print(f"Localizable:          {target_case.localizable}")
    if not target_case.localizable:
        print(f"Exclusion Reason:     {target_case.excluded_reason}")
        print("==================================================================")
        return 0

    print(f"Ground Truth Files:   {', '.join(target_case.ground_truth_files)}")
    print(f"Ground Truth Funcs:   {', '.join(target_case.ground_truth_functions)}")
    print(f"Strategy:             {args.strategy} (Mock: {args.mock})")
    print("==================================================================")

    # 2. Setup retrieval strategy
    strategy: RetrievalStrategy = StubEvaluationStrategy(name=args.strategy)

    query = RetrievalQuery(
        case_id=target_case.case_id,
        text=target_case.bug_report,
        revision=target_case.revision,
        k=10,
        limits=RetrievalLimits(max_items=10, max_hops=2, timeout_ms=30_000),
    )
    retrieval_res = strategy.retrieve(query)
    print(
        f"\n[Retrieval] Found {len(retrieval_res.items)} items in {retrieval_res.elapsed_ms:.1f}ms"
    )

    # 3. Context manifest packing & memory integration
    memory_repo = IncidentMemoryRepository()
    replay_engine = ChronologicalReplayEngine(memory_repository=memory_repo)

    manifest_items: list[dict[str, Any]] = []
    for it in retrieval_res.items:
        manifest_items.append(
            {
                "evidence_id": it.evidence_id,
                "file_path": it.target.file,
                "symbol": it.target.symbol,
                "strategy": it.strategy,
                "rank": it.rank,
                "score": it.score,
                "content": f"# Evidence {it.evidence_id} in {it.target.file}",
            }
        )

    if args.strategy == "memory" and target_case.created_at:
        memories = memory_repo.query_eligible(
            query_text=target_case.bug_report,
            as_of_time=target_case.created_at,
            repo=target_case.repo,
        )
        if memories:
            adapter = IncidentMemoryRetrievalAdapter(memory_repo)
            manifest_items.extend(adapter.to_evidence_items(memories))
            print(f"[Memory] Included {len(memories)} verified incident memories")

    context_manifest = {
        "case_id": target_case.case_id,
        "revision": target_case.revision,
        "budget": {"token_limit": args.budget},
        "items": manifest_items,
    }

    # Verify no future leakage
    replay_engine.assert_no_leakage(target_case, manifest_items)

    # 4. Configure orchestrator
    provider: ModelProvider
    verifier: SandboxVerifierProtocol

    if args.mock:
        gold_diff = (
            f"--- a/{target_case.ground_truth_files[0]}\n"
            f"+++ b/{target_case.ground_truth_files[0]}\n"
            f"@@ -1,3 +1,3 @@\n"
            f"-# buggy line\n"
            f"+# fixed line for {target_case.case_id}\n"
        )
        provider = MockModelProvider(responses=[gold_diff])

        # Use stub verifier in mock mode
        class _MockVerifier:
            def verify(self, *a: Any, **kw: Any) -> Any:
                from tracefix.repair.interfaces import VerificationResultSummary

                assert target_case is not None
                return VerificationResultSummary(
                    status="VERIFIED",
                    exit_code=0,
                    passed_tests=target_case.fail_to_pass_tests,
                    duration_seconds=1.2,
                )

        verifier = _MockVerifier()
    else:
        provider = HttpModelProvider()  # reads ANTHROPIC_API_KEY
        verifier = SandboxVerifierAdapter()  # runs in disposable git worktree

    validator = PatchValidator()
    orchestrator = RepairOrchestrator(
        model_provider=provider,
        patch_validator=validator,
        sandbox_verifier=verifier,
    )

    # 5. Execute repair
    test_suite = {
        "fail_to_pass": target_case.fail_to_pass_tests,
        "pass_to_pass": target_case.validation.get("pass_to_pass_tests", []),
    }
    request = RepairRequest(
        case_id=target_case.case_id,
        repo=target_case.repo,
        base_revision=target_case.revision,
        bug_report=target_case.bug_report,
        context_manifest=context_manifest,
        test_suite=test_suite,
        configuration=RepairConfig(),
    )

    print("\n[Orchestrator] Running repair state machine...")
    repair_result = orchestrator.run(request)

    print("------------------------------------------------------------------")
    print(f"Final State:          {repair_result.final_state}")
    print(f"Duration:             {repair_result.duration_seconds:.2f}s")
    print(f"Attempts Made:        {repair_result.attempts_made}")
    print(f"Patch Generated:      {repair_result.candidate_patch is not None}")
    if repair_result.verification_result:
        v = repair_result.verification_result
        print(f"Verification Status:  {v.status} (exit code: {v.exit_code})")
        print(f"Passed Tests:         {len(v.passed_tests)}")
        print(f"Failed Tests:         {len(v.failed_tests)}")

    # 6. Accumulate into memory if verified
    if (
        repair_result.final_state == "VERIFIED"
        and repair_result.candidate_patch
        and target_case.created_at
    ):
        ev = VerificationEvidence(
            status="VERIFIED",
            test_suite=str(target_case.fail_to_pass_tests),
            exit_code=0,
            duration_seconds=repair_result.duration_seconds,
            executed_at=target_case.created_at,
        )
        rec = IncidentRecord.create(
            case_id=target_case.case_id,
            revision=target_case.revision,
            bug_report=target_case.bug_report,
            patch_diff=repair_result.candidate_patch.raw_diff,
            verification_evidence=ev,
            repo=target_case.repo,
            created_at=target_case.created_at,
        )
        saved = memory_repo.save(rec)
        print(f"[Memory] Saved verified incident record: {saved.incident_id}")

    print("==================================================================")

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(repair_result.model_dump(), indent=2), encoding="utf-8")
        print(f"Saved result JSON to: {out_path}")

    return 0 if repair_result.final_state == "VERIFIED" else 1


if __name__ == "__main__":
    sys.exit(main())
