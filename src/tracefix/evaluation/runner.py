"""Single-arm evaluation runner (A6a).

Evaluates **one** retrieval strategy against a frozen case set and produces
per-case records plus aggregates. It runs one arm only: baseline-versus-
treatment comparisons are deliberately out of scope until C4/D8 are decided.

Honesty rules enforced here
---------------------------
- A retrieval failure is recorded as ``status="failed"`` with a message; it is
  never converted into a zero-rank success.
- A non-localizable case is recorded as ``status="excluded"`` with its reason
  and is excluded from every metric denominator.
- Ground truth is carried as *provisional*; the report says so explicitly.
- Reproducible result fields are separated from volatile metadata
  (wall-clock, environment) via :meth:`EvaluationReport.reproducible_dict`.

Strategy construction is fully injectable, so the runner is tested with stub
strategies and never needs Docker, FalkorDB, or the network.
"""

from __future__ import annotations

import json
import platform
from collections.abc import Callable
from datetime import UTC, datetime
from importlib import metadata
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field

from tracefix.evaluation.cases import CaseRecord, CaseSet
from tracefix.evaluation.metrics import (
    MetricsConfig,
    count_duplicates,
    count_undefined,
    first_relevant_rank,
    hit_at_k,
    latency_stats,
    macro_average,
    micro_recall,
    recall_at_k,
    sum_tokens,
)
from tracefix.retrieval.interfaces import (
    RankedItem,
    RetrievalLimits,
    RetrievalQuery,
    RetrievalResult,
    RetrievalStrategy,
)

CaseStatus = Literal["ok", "failed", "excluded"]

RelevanceFn = Callable[[CaseRecord, RankedItem], bool]
QueryBuilder = Callable[[CaseRecord, MetricsConfig], RetrievalQuery]
ContentResolver = Callable[[RankedItem], str]


class TokenCounterLike(Protocol):
    """Minimal tokenizer interface (mirrors retrieval.context_selector)."""

    def count(self, text: str) -> int: ...


class CaseResult(BaseModel):
    """Per-case outcome. ``evaluated`` is False for excluded/failed cases."""

    case_id: str
    revision: str
    status: CaseStatus
    evaluated: bool
    n_ground_truth_functions: int = 0
    relevant_ranks: list[int] = Field(default_factory=list)
    hit_at_k: dict[str, bool] = Field(default_factory=dict)
    recall_at_k: dict[str, float | None] = Field(default_factory=dict)
    first_relevant_rank: int | None = None
    retrieved_count: int = 0
    duplicates: int = 0
    candidate_tokens: int | None = None
    latency_ms: float | None = None
    failure: str | None = None
    note: str | None = None


class LatencyAggregate(BaseModel):
    count: int
    total_ms: float
    mean_ms: float | None
    p50_ms: float | None
    p95_ms: float | None
    max_ms: float | None


class Aggregate(BaseModel):
    """Aggregate over evaluated cases. Denominators are reported explicitly."""

    cases_total: int
    cases_localizable: int
    cases_evaluated: int
    cases_failed: int
    cases_excluded: int
    k_values: list[int]
    primary_k: int
    hit_at_k_macro: dict[str, float | None] = Field(default_factory=dict)
    hit_at_k_denominator: dict[str, int] = Field(default_factory=dict)
    recall_at_k_macro: dict[str, float | None] = Field(default_factory=dict)
    recall_at_k_micro: dict[str, float | None] = Field(default_factory=dict)
    recall_at_k_denominator: dict[str, int] = Field(default_factory=dict)
    undefined_metric_counts: dict[str, int] = Field(default_factory=dict)
    total_candidate_tokens: int = 0
    tokens_available_for: int = 0
    latency: LatencyAggregate
    total_duplicates: int = 0


class EvaluationReport(BaseModel):
    # --- reproducible fields ------------------------------------------------
    case_set_fingerprint: str
    fingerprint_includes_excluded: bool
    evaluation_contract_version: str
    strategy_name: str
    strategy_config: dict[str, Any] = Field(default_factory=dict)
    metric_config: dict[str, Any] = Field(default_factory=dict)
    command: str
    dataset: dict[str, Any] = Field(default_factory=dict)
    contamination: dict[str, Any] = Field(default_factory=dict)
    denominators: dict[str, int] = Field(default_factory=dict)
    excluded: list[dict[str, Any]] = Field(default_factory=list)
    aggregate: Aggregate
    cases: list[CaseResult] = Field(default_factory=list)
    # --- volatile metadata --------------------------------------------------
    generated_at: str | None = None
    environment: dict[str, Any] = Field(default_factory=dict)

    def reproducible_dict(self) -> dict[str, Any]:
        """Stable subset: identical inputs -> identical dict (no timestamps)."""
        data = self.model_dump()
        for volatile in ("generated_at", "environment"):
            data.pop(volatile, None)
        return data

    def to_json(self, *, include_volatile: bool = True) -> str:
        data = self.model_dump()
        if not include_volatile:
            for volatile in ("generated_at", "environment"):
                data.pop(volatile, None)
        return json.dumps(data, sort_keys=True)


def provisional_function_relevance(case: CaseRecord, item: RankedItem) -> bool:
    """Provisional evidence->ground-truth mapping (Q-B7/Q-B9, **not final**).

    A retrieved item counts as relevant when its symbol matches a ground-truth
    function by exact qualified name or by final dotted component. This is a
    placeholder so the runner is runnable; the normalization policy is a C4
    decision and callers may inject their own ``relevance`` callable.
    """
    symbol = item.target.symbol
    if not symbol:
        return False
    return any(
        symbol == qn or symbol == qn.rsplit(".", 1)[-1] for qn in case.ground_truth_functions
    )


def default_query_builder(case: CaseRecord, metrics: MetricsConfig) -> RetrievalQuery:
    """Build a retrieval query from the case's bug report and base revision."""
    max_k = max(metrics.k_values)
    return RetrievalQuery(
        case_id=case.case_id,
        text=case.bug_report,
        revision=case.revision,
        k=max_k,
        limits=RetrievalLimits(max_items=max_k, max_hops=0, timeout_ms=30_000),
    )


def capture_environment() -> dict[str, Any]:
    """Best-effort environment capture (volatile; not part of reproducibility)."""
    dependencies: dict[str, str] = {}
    for name in ("pydantic", "rank_bm25", "falkordb", "tiktoken"):
        if _installed(name):
            dependencies[name] = metadata.version(name)
    return {
        "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "tracefix_version": metadata.version("tracefix") if _installed("tracefix") else "0.0.1",
        "dependencies": dependencies,
    }


def _installed(name: str) -> bool:
    try:
        metadata.version(name)
    except metadata.PackageNotFoundError:
        return False
    return True


class EvaluationRunner:
    """Runs one retrieval strategy over a case set (single arm)."""

    def __init__(
        self,
        strategy: RetrievalStrategy,
        *,
        command: str,
        metrics: MetricsConfig | None = None,
        relevance: RelevanceFn | None = None,
        query_builder: QueryBuilder | None = None,
        content_resolver: ContentResolver | None = None,
        token_counter: TokenCounterLike | None = None,
        strategy_config: dict[str, Any] | None = None,
    ) -> None:
        self.strategy = strategy
        self.command = command
        self.metrics = metrics or MetricsConfig()
        self.relevance = relevance or provisional_function_relevance
        self.query_builder = query_builder or default_query_builder
        self.content_resolver = content_resolver
        self.token_counter = token_counter
        self.strategy_config = strategy_config or {"name": getattr(strategy, "name", "unknown")}

    def _evaluate_case(self, case: CaseRecord) -> CaseResult:
        if not case.localizable:
            return CaseResult(
                case_id=case.case_id,
                revision=case.revision,
                status="excluded",
                evaluated=False,
                note=case.excluded_reason,
            )

        n_gt = len(case.ground_truth_functions)
        query = self.query_builder(case, self.metrics)
        try:
            result = self.strategy.retrieve(query)
        except Exception as exc:  # noqa: BLE001 - recorded as failure, not swallowed
            return CaseResult(
                case_id=case.case_id,
                revision=case.revision,
                status="failed",
                evaluated=False,
                n_ground_truth_functions=n_gt,
                failure=f"{type(exc).__name__}: {exc}",
            )

        ranks = [
            rank for rank, item in enumerate(result.items, start=1) if self.relevance(case, item)
        ]
        hits = {str(k): hit_at_k(ranks, k) for k in self.metrics.k_values}
        recalls = {str(k): recall_at_k(ranks, k, n_gt) for k in self.metrics.k_values}
        ids = [item.evidence_id for item in result.items]
        note = None
        if not result.complete and result.partial_reason is not None:
            note = f"partial: {result.partial_reason.value}"
        return CaseResult(
            case_id=case.case_id,
            revision=case.revision,
            status="ok",
            evaluated=True,
            n_ground_truth_functions=n_gt,
            relevant_ranks=ranks,
            hit_at_k=hits,
            recall_at_k=recalls,
            first_relevant_rank=first_relevant_rank(ranks),
            retrieved_count=len(result.items),
            duplicates=count_duplicates(ids),
            candidate_tokens=self._candidate_tokens(result),
            latency_ms=result.elapsed_ms,
            note=note,
        )

    def _candidate_tokens(self, result: RetrievalResult) -> int | None:
        if self.token_counter is None or self.content_resolver is None:
            return None
        return sum_tokens(
            [int(self.token_counter.count(self.content_resolver(item))) for item in result.items]
        )

    def _aggregate(self, results: list[CaseResult]) -> Aggregate:
        evaluated = [r for r in results if r.evaluated]
        failed = [r for r in results if r.status == "failed"]
        excluded = [r for r in results if r.status == "excluded"]

        hit_macro: dict[str, float | None] = {}
        hit_denominator: dict[str, int] = {}
        recall_macro: dict[str, float | None] = {}
        recall_micro: dict[str, float | None] = {}
        recall_denominator: dict[str, int] = {}
        undefined: dict[str, int] = {}
        for k in self.metrics.k_values:
            key = str(k)
            hit_values = [1.0 if r.hit_at_k.get(key) else 0.0 for r in evaluated]
            hit_macro[key] = macro_average(hit_values) if hit_values else None
            hit_denominator[key] = len(hit_values)
            recall_values = [r.recall_at_k.get(key) for r in evaluated]
            recall_macro[key] = macro_average(recall_values)
            undefined[key] = count_undefined(recall_values)
            recall_denominator[key] = sum(r.n_ground_truth_functions for r in evaluated)
            recall_micro[key] = micro_recall(
                [r.relevant_ranks for r in evaluated],
                k,
                [r.n_ground_truth_functions for r in evaluated],
            )

        latencies = [r.latency_ms for r in evaluated if r.latency_ms is not None]
        stats = latency_stats(latencies)
        available_tokens = [r.candidate_tokens for r in evaluated if r.candidate_tokens is not None]
        return Aggregate(
            cases_total=len(results),
            cases_localizable=len(evaluated) + len(failed),
            cases_evaluated=len(evaluated),
            cases_failed=len(failed),
            cases_excluded=len(excluded),
            k_values=list(self.metrics.k_values),
            primary_k=self.metrics.primary_k,
            hit_at_k_macro=hit_macro,
            hit_at_k_denominator=hit_denominator,
            recall_at_k_macro=recall_macro,
            recall_at_k_micro=recall_micro,
            recall_at_k_denominator=recall_denominator,
            undefined_metric_counts=undefined,
            total_candidate_tokens=sum_tokens(available_tokens),
            tokens_available_for=len(available_tokens),
            latency=LatencyAggregate(
                count=stats.count,
                total_ms=stats.total_ms,
                mean_ms=stats.mean_ms,
                p50_ms=stats.p50_ms,
                p95_ms=stats.p95_ms,
                max_ms=stats.max_ms,
            ),
            total_duplicates=sum(r.duplicates for r in evaluated),
        )

    def run(self, case_set: CaseSet) -> EvaluationReport:
        results = [self._evaluate_case(case) for case in case_set.cases]
        aggregate = self._aggregate(results)
        pre_cutoff = sum(1 for c in case_set.cases if c.pre_cutoff)
        dataset = {
            "source": case_set.dataset_source,
            "repo": case_set.repo,
            "license": case_set.license,
            "ground_truth_status": case_set.ground_truth_status,
            "ground_truth_is_provisional": case_set.ground_truth_is_provisional,
            "provenance_verified": False,
            "provenance_note": (
                "raw rows provenance (source URL / dataset revision / checksum) not recorded"
            ),
        }
        contamination = {
            "pre_cutoff_cases": pre_cutoff,
            "total_cases": len(case_set.cases),
            "note": (
                "pre-cutoff cases may be contaminated for current models; "
                "disclose this in every report"
            ),
        }
        denominators = {
            "cases_total": len(case_set.cases),
            "cases_localizable": len(case_set.localizable),
            "cases_excluded": len(case_set.excluded),
            "cases_evaluated": aggregate.cases_evaluated,
            "cases_failed": aggregate.cases_failed,
        }
        return EvaluationReport(
            case_set_fingerprint=case_set.fingerprint(),
            fingerprint_includes_excluded=False,
            evaluation_contract_version=case_set.contract_version,
            strategy_name=getattr(self.strategy, "name", "unknown"),
            strategy_config=self.strategy_config,
            metric_config={
                "k_values": list(self.metrics.k_values),
                "primary_k": self.metrics.primary_k,
                "multi_function_policy": self.metrics.multi_function_policy,
            },
            command=self.command,
            dataset=dataset,
            contamination=contamination,
            denominators=denominators,
            excluded=[
                {"case_id": c.case_id, "reason": c.excluded_reason} for c in case_set.excluded
            ],
            aggregate=aggregate,
            cases=results,
            generated_at=datetime.now(UTC).isoformat(),
            environment=capture_environment(),
        )


def evaluate_case_set(
    strategy: RetrievalStrategy,
    case_set: CaseSet,
    *,
    command: str,
    **kwargs: Any,
) -> EvaluationReport:
    """Convenience wrapper: run one strategy over a case set."""
    return EvaluationRunner(strategy, command=command, **kwargs).run(case_set)
