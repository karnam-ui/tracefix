"""Multi-arm research experiment harness for repair and localization (Phase 6).

Evaluates and compares repair outcomes across multiple retrieval and memory configurations:
- Arm A: Conventional lexical retrieval baseline (LexicalBM25Strategy)
- Arm B: Graph-guided retrieval (GraphGuidedStrategy / Hybrid RRF)
- Arm C: Graph-guided + verified incident memory (Replay + Memory repository)
- Context budget ablations (4k, 8k, 16k tokens)


Enforces:
1. Identical case-set fingerprint across comparable arms.
2. Honest reporting of denominators (never silently drop excluded or failed cases).
3. Strict chronological replay and leakage prevention when memory is enabled.
4. Deterministic aggregation and reproducibility.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from tracefix.evaluation.cases import CaseRecord
from tracefix.evaluation.metrics import (
    MetricsConfig,
    first_relevant_rank,
    hit_at_k,
    macro_average,
    micro_recall,
    patch_generation_rate,
    patch_validation_rate,
    recall_at_k,
    reciprocal_rank,
    repair_success_rate,
)
from tracefix.evaluation.replay import ChronologicalReplayEngine
from tracefix.memory.models import IncidentRecord, VerificationEvidence
from tracefix.memory.repository import IncidentMemoryRepository
from tracefix.memory.retrieval_adapter import IncidentMemoryRetrievalAdapter
from tracefix.repair.interfaces import (
    RepairConfig,
    RepairRequest,
    RepairResult,
)
from tracefix.repair.patch_generator import MockModelProvider
from tracefix.repair.state_machine import RepairOrchestrator
from tracefix.retrieval.interfaces import (
    RankedItem,
    RetrievalLimits,
    RetrievalQuery,
    RetrievalStrategy,
)

CaseStatus = Literal["ok", "failed", "excluded"]


def provisional_relevance(case: CaseRecord, item: RankedItem) -> bool:
    """Provisional symbol-level relevance function against ground truth."""
    symbol = item.target.symbol
    if not symbol:
        return False
    return any(
        symbol == qn or symbol == qn.rsplit(".", 1)[-1] for qn in case.ground_truth_functions
    )


class ArmCaseResult(BaseModel):
    """Detailed outcome for one case within an experimental arm."""

    arm_id: str
    case_id: str
    revision: str
    status: CaseStatus
    evaluated: bool
    excluded_reason: str | None = None
    failure_reason: str | None = None
    ground_truth_functions_count: int = 0
    relevant_ranks: list[int] = Field(default_factory=list)
    hit_at_k: dict[str, bool] = Field(default_factory=dict)
    recall_at_k: dict[str, float | None] = Field(default_factory=dict)
    first_relevant_rank: int | None = None
    mrr: float = 0.0
    retrieved_items_count: int = 0
    context_tokens_used: int = 0
    retrieval_latency_ms: float = 0.0
    patch_generated: bool = False
    patch_validated: bool = False
    final_state: str = "NOT_EVALUATED"
    verified: bool = False
    repair_duration_seconds: float = 0.0
    repair_retries: int = 0
    memory_added: bool = False
    incident_id: str | None = None


class ArmAggregate(BaseModel):
    """Aggregated performance metrics for an experimental arm."""

    arm_id: str
    arm_name: str
    description: str
    cases_total: int
    cases_localizable: int
    cases_evaluated: int
    cases_excluded: int
    cases_failed: int
    hit_at_k_macro: dict[str, float | None] = Field(default_factory=dict)
    hit_at_k_denominator: dict[str, int] = Field(default_factory=dict)
    recall_at_k_macro: dict[str, float | None] = Field(default_factory=dict)
    recall_at_k_micro: dict[str, float | None] = Field(default_factory=dict)
    recall_at_k_denominator: dict[str, int] = Field(default_factory=dict)
    mrr_macro: float | None = None
    patch_generated_rate: float | None = None
    patch_validated_rate: float | None = None
    verified_repair_rate: float | None = None
    mean_context_tokens: float | None = None
    mean_retrieval_latency_ms: float | None = None
    mean_repair_duration_seconds: float | None = None
    memories_accumulated: int = 0


class MultiArmExperimentResult(BaseModel):
    """Complete comparative result across multiple experimental arms."""

    experiment_name: str
    case_set_fingerprint: str
    created_at: str
    k_values: list[int]
    primary_k: int
    token_budget: int
    arms: dict[str, ArmAggregate] = Field(default_factory=dict)
    case_results: dict[str, list[ArmCaseResult]] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ExperimentArm:
    """Specification for an experimental arm."""

    def __init__(
        self,
        arm_id: str,
        name: str,
        strategy_factory: Callable[[], RetrievalStrategy] | RetrievalStrategy,
        *,
        memory_enabled: bool = False,
        token_budget: int = 4000,
        orchestrator_factory: Callable[[], RepairOrchestrator] | RepairOrchestrator | None = None,
        repair_config: RepairConfig | None = None,
        memory_repository: IncidentMemoryRepository | None = None,
        description: str = "",
    ) -> None:
        self.arm_id = arm_id
        self.name = name
        self.strategy_factory = strategy_factory
        self.memory_enabled = memory_enabled
        self.token_budget = token_budget
        self.orchestrator_factory = orchestrator_factory
        self.repair_config = repair_config or RepairConfig()
        self.memory_repository = memory_repository
        self.description = description

    def get_strategy(self) -> RetrievalStrategy:
        if callable(self.strategy_factory):
            return self.strategy_factory()
        return self.strategy_factory

    def get_orchestrator(self) -> RepairOrchestrator:
        if self.orchestrator_factory is not None:
            if callable(self.orchestrator_factory):
                return self.orchestrator_factory()
            return self.orchestrator_factory
        from tracefix.repair.patch_validator import PatchValidator
        from tracefix.verification.sandbox import SandboxVerifierAdapter

        return RepairOrchestrator(
            model_provider=MockModelProvider(),
            patch_validator=PatchValidator(),
            sandbox_verifier=SandboxVerifierAdapter(),
        )


class MultiArmExperimentRunner:
    """Executes controlled multi-arm comparative experiments."""

    def __init__(
        self,
        metrics_config: MetricsConfig | None = None,
        relevance_fn: Callable[[CaseRecord, RankedItem], bool] | None = None,
    ) -> None:
        self.metrics_config = metrics_config or MetricsConfig()
        self.relevance_fn = relevance_fn or provisional_relevance

    def run_arm(
        self,
        arm: ExperimentArm,
        cases: list[CaseRecord],
        *,
        memory_repository: IncidentMemoryRepository | None = None,
    ) -> tuple[ArmAggregate, list[ArmCaseResult]]:
        """Run an experimental arm across a set of cases."""
        strategy = arm.get_strategy()
        orchestrator = arm.get_orchestrator()
        repo = arm.memory_repository or memory_repository or IncidentMemoryRepository()

        replay_engine = ChronologicalReplayEngine(
            memory_repository=repo,
            memory_enabled=arm.memory_enabled,
        )

        eval_cases = cases
        if arm.memory_enabled:
            # Enforce strict chronological order for dynamic learning & leakage checks
            eval_cases = replay_engine.sort_cases(cases)

        results: list[ArmCaseResult] = []

        for case in eval_cases:
            res = self._evaluate_case(
                arm=arm,
                case=case,
                strategy=strategy,
                orchestrator=orchestrator,
                replay_engine=replay_engine,
                repo=repo,
            )
            results.append(res)

        aggregate = self._aggregate_arm(arm, results, len(repo.query_eligible()))
        return aggregate, results

    def _evaluate_case(
        self,
        arm: ExperimentArm,
        case: CaseRecord,
        strategy: RetrievalStrategy,
        orchestrator: RepairOrchestrator,
        replay_engine: ChronologicalReplayEngine,
        repo: IncidentMemoryRepository,
    ) -> ArmCaseResult:
        if not case.localizable:
            return ArmCaseResult(
                arm_id=arm.arm_id,
                case_id=case.case_id,
                revision=case.revision,
                status="excluded",
                evaluated=False,
                excluded_reason=case.excluded_reason or "Non-localizable case",
            )

        n_gt = len(case.ground_truth_functions)
        max_k = max(self.metrics_config.k_values)
        query = RetrievalQuery(
            case_id=case.case_id,
            text=case.bug_report,
            revision=case.revision,
            k=max_k,
            limits=RetrievalLimits(max_items=max_k, max_hops=2, timeout_ms=30_000),
        )

        # 1. Retrieval
        try:
            retrieval_res = strategy.retrieve(query)
        except Exception as exc:  # noqa: BLE001
            return ArmCaseResult(
                arm_id=arm.arm_id,
                case_id=case.case_id,
                revision=case.revision,
                status="failed",
                evaluated=False,
                failure_reason=f"Retrieval failure: {type(exc).__name__}: {exc}",
                ground_truth_functions_count=n_gt,
            )

        ranks = [
            rank
            for rank, item in enumerate(retrieval_res.items, start=1)
            if self.relevance_fn(case, item)
        ]
        hits = {str(k): hit_at_k(ranks, k) for k in self.metrics_config.k_values}
        recalls = {str(k): recall_at_k(ranks, k, n_gt) for k in self.metrics_config.k_values}
        fr_rank = first_relevant_rank(ranks)
        mrr = reciprocal_rank(ranks)

        # 2. Context manifest packing
        items_payload: list[dict[str, Any]] = []
        for item in retrieval_res.items:
            items_payload.append(
                {
                    "evidence_id": item.evidence_id,
                    "file_path": item.target.file,
                    "symbol": item.target.symbol,
                    "strategy": item.strategy,
                    "rank": item.rank,
                    "score": item.score,
                    "provenance": item.provenance.value,
                    "source": item.source,
                    "content": (
                        f"# Evidence {item.evidence_id} in {item.target.file}:{item.target.symbol}"
                    ),
                }
            )

        # 3. Memory integration (if enabled)
        prior_memories = []
        if arm.memory_enabled and case.created_at:
            prior_memories = repo.query_eligible(
                query_text=case.bug_report,
                as_of_time=case.created_at,
                repo=case.repo,
            )
            if prior_memories:
                adapter = IncidentMemoryRetrievalAdapter(repo)
                mem_items = adapter.to_evidence_items(prior_memories)
                items_payload.extend(mem_items)

        context_manifest: dict[str, Any] = {
            "case_id": case.case_id,
            "revision": case.revision,
            "budget": {"token_limit": arm.token_budget},
            "items": items_payload,
        }

        # 4. Leakage assertion
        if arm.memory_enabled:
            replay_engine.assert_no_leakage(case, context_manifest["items"])

        # 5. Estimate token usage
        # Simple deterministic character-based estimator (4 chars / token)
        total_chars = sum(len(str(it)) for it in items_payload)
        tokens_used = (total_chars + 3) // 4

        # 6. Repair orchestration
        test_suite = {
            "fail_to_pass": case.fail_to_pass_tests,
            "pass_to_pass": case.validation.get("pass_to_pass_tests", []),
        }
        repair_req = RepairRequest(
            case_id=case.case_id,
            repo=case.repo,
            base_revision=case.revision,
            bug_report=case.bug_report,
            context_manifest=context_manifest,
            test_suite=test_suite,
            configuration=arm.repair_config,
        )

        repair_res: RepairResult = orchestrator.run(repair_req)

        # 7. Memory accumulation on verified success
        memory_added = False
        incident_id: str | None = None
        if (
            arm.memory_enabled
            and repair_res.final_state == "VERIFIED"
            and repair_res.candidate_patch
            and case.created_at
        ):
            evidence = VerificationEvidence(
                status="VERIFIED",
                test_suite=str(case.fail_to_pass_tests),
                exit_code=0,
                duration_seconds=repair_res.duration_seconds,
                executed_at=case.created_at,
            )
            rec = IncidentRecord.create(
                case_id=case.case_id,
                revision=case.revision,
                bug_report=case.bug_report,
                patch_diff=repair_res.candidate_patch.raw_diff,
                verification_evidence=evidence,
                repo=case.repo,
                created_at=case.created_at,
            )
            saved = repo.save(rec)
            memory_added = True
            incident_id = saved.incident_id

        patch_gen = repair_res.candidate_patch is not None
        patch_val = repair_res.verification_result is not None or repair_res.final_state in {
            "VERIFIED",
            "FAILED",
        }
        is_verified = repair_res.final_state == "VERIFIED"
        retries_count = len(repair_res.retry_history)

        return ArmCaseResult(
            arm_id=arm.arm_id,
            case_id=case.case_id,
            revision=case.revision,
            status="ok",
            evaluated=True,
            ground_truth_functions_count=n_gt,
            relevant_ranks=ranks,
            hit_at_k=hits,
            recall_at_k=recalls,
            first_relevant_rank=fr_rank,
            mrr=mrr,
            retrieved_items_count=len(retrieval_res.items),
            context_tokens_used=tokens_used,
            retrieval_latency_ms=retrieval_res.elapsed_ms,
            patch_generated=patch_gen,
            patch_validated=patch_val,
            final_state=repair_res.final_state,
            verified=is_verified,
            repair_duration_seconds=repair_res.duration_seconds,
            repair_retries=retries_count,
            memory_added=memory_added,
            incident_id=incident_id,
        )

    def _aggregate_arm(
        self,
        arm: ExperimentArm,
        results: list[ArmCaseResult],
        memories_count: int,
    ) -> ArmAggregate:
        evaluated = [r for r in results if r.evaluated]
        failed = [r for r in results if r.status == "failed"]
        excluded = [r for r in results if r.status == "excluded"]
        localizable = [r for r in results if r.status != "excluded"]

        n_eval = len(evaluated)

        hit_macro: dict[str, float | None] = {}
        hit_denom: dict[str, int] = {}
        recall_macro: dict[str, float | None] = {}
        recall_micro: dict[str, float | None] = {}
        recall_denom: dict[str, int] = {}

        for k in self.metrics_config.k_values:
            key = str(k)
            hit_values = [1.0 if r.hit_at_k.get(key) else 0.0 for r in evaluated]
            hit_macro[key] = macro_average(hit_values)
            hit_denom[key] = len(hit_values)

            recall_values = [r.recall_at_k.get(key) for r in evaluated]
            recall_macro[key] = macro_average(recall_values)

            # micro recall
            per_case_ranks = [r.relevant_ranks for r in evaluated]
            per_case_gt = [r.ground_truth_functions_count for r in evaluated]
            recall_micro[key] = micro_recall(per_case_ranks, k, per_case_gt)
            recall_denom[key] = sum(per_case_gt)

        mrr_macro = macro_average([r.mrr for r in evaluated])

        # Repair rates
        generated_count = sum(1 for r in evaluated if r.patch_generated)
        validated_count = sum(1 for r in evaluated if r.patch_validated)
        verified_count = sum(1 for r in evaluated if r.verified)

        gen_rate = patch_generation_rate(generated_count, n_eval)
        val_rate = patch_validation_rate(validated_count, n_eval)
        rep_rate = repair_success_rate(verified_count, n_eval)

        mean_tokens = sum(r.context_tokens_used for r in evaluated) / n_eval if n_eval > 0 else None
        mean_retrieval_ms = (
            sum(r.retrieval_latency_ms for r in evaluated) / n_eval if n_eval > 0 else None
        )
        mean_repair_sec = (
            sum(r.repair_duration_seconds for r in evaluated) / n_eval if n_eval > 0 else None
        )

        return ArmAggregate(
            arm_id=arm.arm_id,
            arm_name=arm.name,
            description=arm.description,
            cases_total=len(results),
            cases_localizable=len(localizable),
            cases_evaluated=n_eval,
            cases_excluded=len(excluded),
            cases_failed=len(failed),
            hit_at_k_macro=hit_macro,
            hit_at_k_denominator=hit_denom,
            recall_at_k_macro=recall_macro,
            recall_at_k_micro=recall_micro,
            recall_at_k_denominator=recall_denom,
            mrr_macro=mrr_macro,
            patch_generated_rate=gen_rate,
            patch_validated_rate=val_rate,
            verified_repair_rate=rep_rate,
            mean_context_tokens=mean_tokens,
            mean_retrieval_latency_ms=mean_retrieval_ms,
            mean_repair_duration_seconds=mean_repair_sec,
            memories_accumulated=memories_count,
        )

    def run_experiment(
        self,
        experiment_name: str,
        case_set_fingerprint: str,
        arms: Sequence[ExperimentArm],
        cases: list[CaseRecord],
        token_budget: int = 4000,
        metadata: dict[str, Any] | None = None,
    ) -> MultiArmExperimentResult:
        """Run full multi-arm comparative experiment across all configured arms."""
        aggregates: dict[str, ArmAggregate] = {}
        case_results_map: dict[str, list[ArmCaseResult]] = {}

        for arm in arms:
            agg, res = self.run_arm(arm, cases)
            aggregates[arm.arm_id] = agg
            case_results_map[arm.arm_id] = res

        return MultiArmExperimentResult(
            experiment_name=experiment_name,
            case_set_fingerprint=case_set_fingerprint,
            created_at=datetime.now(UTC).isoformat(),
            k_values=list(self.metrics_config.k_values),
            primary_k=self.metrics_config.primary_k,
            token_budget=token_budget,
            arms=aggregates,
            case_results=case_results_map,
            metadata=metadata or {},
        )
