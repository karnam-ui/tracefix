"""Graph-guided retrieval strategy (A3.3), implementing the C2 interface.

Pipeline: lexical seeds -> bounded graph expansion via a `NeighborhoodProvider`
-> deterministic rerank with dedup -> C2 `RetrievalResult`.

Determinism and ranking
-----------------------
Items are ordered by `(depth, seed_rank, evidence_id)` ascending: lexical seeds
are depth 0, then expansions by hop distance, then by the rank of the seed that
reached them, then by stable id. `score = 1/(depth+1) + 1/(seed_rank+1)` (higher
is more relevant), which is monotonic with that order. Ties never depend on
iteration order.

Provenance
----------
Every item carries `provenance=observed|inferred`. An expanded item is
`inferred` if any edge on its graph path is inferred. `source` labels the
traversal (`graph_seed`, `graph_callers`, `graph_callees`, `graph_covered_by`,
`graph_imports`, ...).

Degradation (C2 failure semantics)
----------------------------------
- graph unavailable / revision mismatch / other provider error: return the
  seeds with `complete=false` and the matching `partial_reason`; only raise
  `RetrievalError` when there are no usable items at all.
- hop/result limits hit: `limit_reached`; wall-clock/provider deadline:
  `timeout`. Seeds are always retained.
- `max_hops == 0`: seeds only, `complete=true`.

The structured graph path for each expanded item is retained for the (draft)
context manifest via `explain(evidence_id)`; the C2 `RankedItem` itself is not
extended, so this strategy stays compatible with the current retrieval contract.
"""

from __future__ import annotations

import time
from collections.abc import Sequence

from tracefix.graph.query import (
    GraphPath,
    GraphRevisionMismatchError,
    GraphUnavailableError,
    NeighborhoodProvider,
)
from tracefix.retrieval.interfaces import (
    EvidenceTarget,
    PartialReason,
    RankedItem,
    RetrievalError,
    RetrievalQuery,
    RetrievalResult,
)
from tracefix.retrieval.lexical import LexicalBM25Strategy, make_query

DEFAULT_SEED_COUNT = 10
DEFAULT_FANOUT = 5


def _ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 3)


class GraphGuidedStrategy:
    name = "graph_guided"

    def __init__(
        self,
        provider: NeighborhoodProvider,
        seed_strategy: LexicalBM25Strategy,
        *,
        seed_count: int = DEFAULT_SEED_COUNT,
        edge_types: Sequence[str] | None = None,
        fanout: int = DEFAULT_FANOUT,
    ) -> None:
        if seed_count < 1:
            raise ValueError("seed_count must be >= 1")
        if fanout < 1:
            raise ValueError("fanout must be >= 1")
        self.provider = provider
        self.seed_strategy = seed_strategy
        self.seed_count = seed_count
        self.edge_types = tuple(edge_types) if edge_types else None
        self.fanout = fanout
        self._explanations: dict[str, GraphPath] = {}

    def explain(self, evidence_id: str) -> GraphPath | None:
        """Graph path that produced `evidence_id` in the most recent retrieve()."""
        return self._explanations.get(evidence_id)

    def retrieve(self, query: RetrievalQuery) -> RetrievalResult:
        started = time.perf_counter()
        limits = query.limits
        self._explanations = {}

        seed_k = min(self.seed_count, limits.max_items)
        seed_result = self.seed_strategy.retrieve(
            make_query(
                query.text,
                query.revision,
                k=seed_k,
                max_items=limits.max_items,
                case_id=query.case_id,
                timeout_ms=limits.timeout_ms,
            )
        )
        seed_items = list(seed_result.items)
        seed_rank = {item.evidence_id: item.rank for item in seed_items}

        config: dict[str, object] = {
            "strategy": self.name,
            "provider": type(self.provider).__name__,
            "seed_strategy": self.seed_strategy.name,
            "seed_count": self.seed_count,
            "edge_types": list(self.edge_types) if self.edge_types else None,
            "max_hops": limits.max_hops,
            "fanout": self.fanout,
            "graph_status": "ok",
        }

        if not seed_items:
            config["graph_status"] = "no_seeds"
            return RetrievalResult(
                items=[],
                complete=True,
                strategy=self.name,
                config=config,
                revision=query.revision,
                elapsed_ms=_ms(started),
            )

        paths: tuple[GraphPath, ...] = ()
        truncated = False
        timed_out = False
        partial_reason: PartialReason | None = None

        if limits.max_hops >= 1:
            remaining = max(1, limits.timeout_ms - int((time.perf_counter() - started) * 1000))
            try:
                neighborhood = self.provider.neighborhood(
                    [item.evidence_id for item in seed_items],
                    revision=query.revision,
                    edge_types=self.edge_types,
                    max_hops=limits.max_hops,
                    max_results=limits.max_items * self.fanout,
                    timeout_ms=remaining,
                )
                paths = neighborhood.paths
                truncated = neighborhood.truncated
                timed_out = neighborhood.timed_out
            except GraphRevisionMismatchError as exc:
                config["graph_status"] = "revision_mismatch"
                config["graph_error"] = str(exc)
                partial_reason = PartialReason.GRAPH_UNAVAILABLE
            except GraphUnavailableError as exc:
                config["graph_status"] = "unavailable"
                config["graph_error"] = str(exc)
                partial_reason = PartialReason.GRAPH_UNAVAILABLE
            except Exception as exc:  # noqa: BLE001 - recovered per C2 semantics
                config["graph_status"] = "provider_error"
                config["graph_error"] = str(exc)
                partial_reason = PartialReason.STRATEGY_ERROR_RECOVERED
        else:
            config["graph_status"] = "disabled"

        ranked, total_candidates = self._build_items(seed_items, seed_rank, paths, limits.max_items)
        elapsed = _ms(started)

        if partial_reason is None:
            if timed_out or elapsed > limits.timeout_ms:
                partial_reason = PartialReason.TIMEOUT
            elif truncated or total_candidates > limits.max_items:
                partial_reason = PartialReason.LIMIT_REACHED

        if partial_reason is None:
            return RetrievalResult(
                items=ranked,
                complete=True,
                strategy=self.name,
                config=config,
                revision=query.revision,
                elapsed_ms=elapsed,
            )

        if not ranked:
            raise RetrievalError(f"graph_guided produced no usable items ({partial_reason.value})")
        return RetrievalResult(
            items=ranked,
            complete=False,
            partial_reason=partial_reason,
            strategy=self.name,
            config=config,
            revision=query.revision,
            elapsed_ms=elapsed,
        )

    def _build_items(
        self,
        seed_items: list[RankedItem],
        seed_rank: dict[str, int],
        paths: tuple[GraphPath, ...],
        max_items: int,
    ) -> tuple[list[RankedItem], int]:
        candidates: list[tuple[int, int, str, RankedItem]] = []
        for item in seed_items:
            candidates.append(
                (
                    0,
                    item.rank,
                    item.evidence_id,
                    RankedItem(
                        evidence_id=item.evidence_id,
                        strategy=self.name,
                        rank=1,
                        score=round(1.0 / 1 + 1.0 / (item.rank + 1), 6),
                        target=item.target,
                        source_revision=item.source_revision,
                        provenance=item.provenance,
                        source="graph_seed",
                    ),
                )
            )
        seen = set(seed_rank)
        for path in paths:
            evidence_id = path.node.entity_id
            if evidence_id in seen:
                continue
            seen.add(evidence_id)
            origin_rank = seed_rank.get(path.origin_seed_id, len(seed_items) + 1)
            self._explanations[evidence_id] = path
            candidates.append(
                (
                    path.depth,
                    origin_rank,
                    evidence_id,
                    RankedItem(
                        evidence_id=evidence_id,
                        strategy=self.name,
                        rank=1,
                        score=round(1.0 / (path.depth + 1) + 1.0 / (origin_rank + 1), 6),
                        target=EvidenceTarget(
                            file=path.node.path or "",
                            symbol=path.node.qualified_name,
                            lines=_lines(path),
                        ),
                        source_revision=path.node.revision,
                        provenance=path.provenance,
                        source=path.source_label,
                    ),
                )
            )
        candidates.sort(key=lambda entry: (entry[0], entry[1], entry[2]))
        total_candidates = len(candidates)
        selected = candidates[:max_items]
        items: list[RankedItem] = []
        for rank, (_, _, _, item) in enumerate(selected, start=1):
            items.append(item.model_copy(update={"rank": rank}))
        return items, total_candidates


def _lines(path: GraphPath) -> tuple[int, int] | None:
    if path.node.start_line is None or path.node.end_line is None:
        return None
    return (path.node.start_line, path.node.end_line)
