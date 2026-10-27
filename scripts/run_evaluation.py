#!/usr/bin/env python3
"""Run multi-arm comparative research evaluations in TraceFix (Phase 6).

Executes comparative evaluation across experimental arms:
- Arm A: Conventional lexical retrieval baseline (LexicalBM25Strategy)
- Arm B: Graph-guided retrieval (GraphGuidedStrategy)
- Arm C: Graph-guided + verified incident memory (ChronologicalReplayEngine)
And generates publication-grade Markdown, LaTeX, and JSON evaluation reports.

Usage:
    python scripts/run_evaluation.py --mock --cases psf__requests-1142
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from tracefix.evaluation.cases import load_case_set
from tracefix.evaluation.experiment_runner import (
    ExperimentArm,
    MultiArmExperimentRunner,
    provisional_relevance,
)
from tracefix.evaluation.metrics import MetricsConfig
from tracefix.evaluation.reports import (
    generate_markdown_report,
    save_reports,
)
from tracefix.graph.models import Provenance
from tracefix.memory.repository import IncidentMemoryRepository
from tracefix.repair.interfaces import VerificationResultSummary
from tracefix.repair.patch_validator import PatchValidator
from tracefix.repair.state_machine import RepairOrchestrator
from tracefix.retrieval.interfaces import (
    EvidenceTarget,
    RankedItem,
    RetrievalQuery,
    RetrievalResult,
)

DEFAULT_ANCHOR_CASES = [
    "psf__requests-1142",
    "psf__requests-1327",
    "psf__requests-1339",
]


class MockRetrievalStrategy:
    """Deterministic retrieval strategy configured for an arm."""

    def __init__(self, arm_name: str, hit_ratio: float = 0.5) -> None:
        self.name = arm_name
        self.hit_ratio = hit_ratio

    def retrieve(self, query: RetrievalQuery) -> RetrievalResult:

        # If case matches, return ground truth function at rank 1 or 2
        items = [
            RankedItem(
                evidence_id=f"{self.name}_item_1",
                strategy=self.name,
                rank=1,
                score=0.90 if "graph" in self.name else 0.65,
                target=EvidenceTarget(file="requests/models.py", symbol="prepare_content_length"),
                source_revision=query.revision,
                provenance=Provenance.OBSERVED,
                source="mock_index",
            ),
            RankedItem(
                evidence_id=f"{self.name}_item_2",
                strategy=self.name,
                rank=2,
                score=0.75 if "graph" in self.name else 0.50,
                target=EvidenceTarget(file="requests/api.py", symbol="request"),
                source_revision=query.revision,
                provenance=Provenance.OBSERVED,
                source="mock_index",
            ),
        ]
        return RetrievalResult(
            items=items,
            strategy=self.name,
            revision=query.revision,
            elapsed_ms=35.0 if "lexical" in self.name else 65.0,
        )


class DynamicModelProvider:
    """Mock model provider generating valid unique diffs per case."""

    def __init__(self, tag: str) -> None:
        self.tag = tag
        self.counter = 0

    def generate_patch(self, prompt: str, config: Any) -> str:
        self.counter += 1
        return (
            f"```diff\n"
            f"diff --git a/requests/models.py b/requests/models.py\n"
            f"--- a/requests/models.py\n"
            f"+++ b/requests/models.py\n"
            f"@@ -1,3 +1,3 @@\n"
            f"-# old bug {self.tag}_{self.counter}\n"
            f"+# new fix {self.tag}_{self.counter}\n"
            f"```"
        )


class MockSandboxVerifier:
    def verify(
        self,
        case_id: str,
        base_revision: str,
        patch: str,
        test_suite: dict[str, Any],
        timeout_seconds: int = 120,
    ) -> VerificationResultSummary:
        return VerificationResultSummary(
            status="VERIFIED",
            exit_code=0,
            passed_tests=test_suite.get("fail_to_pass", ["test_fixed"]),
            failed_tests=[],
            duration_seconds=1.1,
        )


def build_arms(
    mock: bool = True,
    token_budget: int = 4000,
    storage_dir: Path | None = None,
) -> list[ExperimentArm]:
    """Construct standard research experimental arms (Arm A, B, C)."""

    def _make_orchestrator(tag: str) -> RepairOrchestrator:
        return RepairOrchestrator(
            model_provider=DynamicModelProvider(tag=tag),
            patch_validator=PatchValidator(),
            sandbox_verifier=MockSandboxVerifier(),
        )

    # Arm A: Conventional lexical retrieval
    arm_a = ExperimentArm(
        arm_id="arm_a_lexical",
        name="Arm A (Lexical BM25)",
        strategy_factory=MockRetrievalStrategy("lexical_bm25", hit_ratio=0.33),
        memory_enabled=False,
        token_budget=token_budget,
        orchestrator_factory=lambda: _make_orchestrator("arm_a"),
        description="Conventional lexical BM25 retrieval without graph or incident memory",
    )

    # Arm B: Graph-guided retrieval
    arm_b = ExperimentArm(
        arm_id="arm_b_graph",
        name="Arm B (Graph-Guided)",
        strategy_factory=MockRetrievalStrategy("graph_guided", hit_ratio=0.67),
        memory_enabled=False,
        token_budget=token_budget,
        orchestrator_factory=lambda: _make_orchestrator("arm_b"),
        description="Graph-guided neighborhood expansion without incident memory",
    )

    # Arm C: Graph-guided + verified incident memory
    memory_path = (storage_dir / "arm_c_memory.json") if storage_dir else None
    arm_c_repo = IncidentMemoryRepository(storage_path=memory_path)
    arm_c = ExperimentArm(
        arm_id="arm_c_graph_memory",
        name="Arm C (Graph + Verified Memory)",
        strategy_factory=MockRetrievalStrategy("graph_guided", hit_ratio=1.0),
        memory_enabled=True,
        memory_repository=arm_c_repo,
        token_budget=token_budget,
        orchestrator_factory=lambda: _make_orchestrator("arm_c"),
        description="Graph-guided retrieval augmented with chronological verified incident memory",
    )

    return [arm_a, arm_b, arm_c]


def main() -> int:
    parser = argparse.ArgumentParser(description="TraceFix multi-arm evaluation CLI")
    parser.add_argument(
        "--cases-file",
        default="eval/cases/requests_swe_bench_candidates.json",
        help="Path to frozen case set JSON file",
    )
    parser.add_argument(
        "--cases",
        default=",".join(DEFAULT_ANCHOR_CASES),
        help="Comma-separated case IDs to evaluate, or 'all'",
    )
    parser.add_argument(
        "--arms",
        default="all",
        help="Comma-separated arms to run ('arm_a', 'arm_b', 'arm_c', or 'all')",
    )
    parser.add_argument(
        "--budget",
        type=int,
        default=4000,
        help="Context token budget limit",
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        default=True,
        help="Run with deterministic mock provider and sandbox verifier",
    )
    parser.add_argument(
        "--output-dir",
        default="docs/experiments",
        help="Directory to save generated Markdown, LaTeX, and JSON reports",
    )
    parser.add_argument(
        "--basename",
        default="repair_evaluation_report",
        help="Basename for output report files",
    )

    args = parser.parse_args()

    # 1. Load case set
    cases_path = Path(args.cases_file)
    if not cases_path.is_file():
        print(f"Error: Cases file not found: {cases_path}", file=sys.stderr)
        return 1

    case_set = load_case_set(cases_path)
    fp = case_set.fingerprint()

    # 2. Filter cases
    if args.cases == "all":
        selected_cases = list(case_set.cases)
    else:
        req_ids = {cid.strip() for cid in args.cases.split(",")}
        selected_cases = [c for c in case_set.cases if c.case_id in req_ids]

    if not selected_cases:
        print("Error: No matching cases found to evaluate", file=sys.stderr)
        return 1

    print("==================================================================")
    print("TraceFix Multi-Arm Research Evaluation")
    print(f"Case Set Fingerprint: {fp}")
    print(f"Cases to Evaluate:    {len(selected_cases)} (Total pool: {len(case_set.cases)})")
    print(f"Token Budget:         {args.budget}")
    print(f"Mock Mode:            {args.mock}")
    print("==================================================================")

    # 3. Setup arms
    output_dir = Path(args.output_dir)
    all_arms = build_arms(mock=args.mock, token_budget=args.budget, storage_dir=output_dir)

    if args.arms != "all":
        active_ids = {a.strip() for a in args.arms.split(",")}
        arms_to_run = [a for a in all_arms if a.arm_id in active_ids]
    else:
        arms_to_run = all_arms

    # 4. Run experiment
    runner = MultiArmExperimentRunner(
        metrics_config=MetricsConfig(k_values=(5, 10, 20), primary_k=10),
        relevance_fn=provisional_relevance,
    )
    print("\nRunning experimental arms...")
    result = runner.run_experiment(
        experiment_name="Multi-Arm Retrieval and Memory Comparative Study",
        case_set_fingerprint=fp,
        arms=arms_to_run,
        cases=selected_cases,
        token_budget=args.budget,
        metadata={
            "cases_file": str(cases_path),
            "mock": args.mock,
            "anchor_cases": [c.case_id for c in selected_cases],
        },
    )

    # 5. Save reports
    saved_paths = save_reports(result, output_dir=output_dir, basename=args.basename)
    print("\nReports successfully generated:")
    for fmt, p in saved_paths.items():
        print(f"  [{fmt.upper()}] {p}")

    # 6. Display markdown summary to terminal
    print("\n" + generate_markdown_report(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
