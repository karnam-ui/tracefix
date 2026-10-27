"""Deterministic, token-budget-aware context selection (A3.5).

Turns ranked retrieval items (C2 `RankedItem`, e.g. from `GraphGuidedStrategy`)
into a budget-bounded, diversity-aware evidence package with an explicit
selection or exclusion reason for every input.

Scope and non-finalization
--------------------------
This is **not** `manifest.py` (A5.2) and does not finalize `context_manifest.json`
(C3). It produces the per-item material the draft manifest needs (evidence id,
source revision, provenance, source, token contribution, selection reason) plus
the budget/totals accounting, and nothing that belongs to the still-open
Workstream B questions:

- the token budget is **supplied by the caller** and only recorded here (Q-B1);
- budget scope is evidence-only in this component and left open (Q-B2);
- the tokenizer is configurable and every count is labeled exact or estimated
  (D4 / `token_accounting`);
- raw content is provided by the caller; no transport or raw-content policy is
  chosen (Q-B5, Q-B6);
- manifest-level fields (`run_id`, `created_at`) are A5's responsibility.

Tokenizers
----------
Every counter exposes `count(text) -> int` and a `config()` matching
`token_accounting.config` (`name`, `encoding`, `method`, `estimated`).
`CharDiv4TokenCounter` is a deterministic, dependency-free estimator
(`estimated=true`). `TiktokenTokenCounter` is exact (`estimated=false`) but only
constructible when `tiktoken` is installed, and records its encoding.

Budget behavior
---------------
Selection is a single greedy pass in deterministic rank order. Items that exceed
the *remaining* budget are excluded (`over_budget`) and the scan continues, so
the package is packed with later items that do fit; an item larger than the whole
budget is excluded as `item_too_large`. Diversity caps
(`max_items_per_file`, `max_items_per_source`) are hard: an item over a cap is
excluded as `diversity_cap`, so the budget may be left under-filled when caps
bind. An item that introduces a not-yet-represented file is labeled
`diversity_spread`; other selections are `top_ranked`.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, Field, model_validator

from tracefix.graph.models import Provenance
from tracefix.graph.query import GraphPath
from tracefix.retrieval.interfaces import RankedItem, RetrievalResult


class SelectionReason(StrEnum):
    TOP_RANKED = "top_ranked"
    DIVERSITY_SPREAD = "diversity_spread"


class ExclusionReason(StrEnum):
    DUPLICATE = "duplicate"
    DIVERSITY_CAP = "diversity_cap"
    OVER_BUDGET = "over_budget"
    ITEM_TOO_LARGE = "item_too_large"


@runtime_checkable
class TokenCounter(Protocol):
    name: str
    method: str
    encoding: str | None
    estimated: bool

    def count(self, text: str) -> int: ...

    def config(self) -> dict[str, Any]: ...


class CharDiv4TokenCounter:
    """Deterministic estimator: one token per 4 characters (estimated=true)."""

    def __init__(self) -> None:
        self.name = "char_div_4"
        self.method = "char_div_4"
        self.encoding = None
        self.estimated = True

    def count(self, text: str) -> int:
        return (len(text) + 3) // 4

    def config(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "encoding": self.encoding,
            "method": self.method,
            "estimated": self.estimated,
        }


class TiktokenTokenCounter:
    """Exact tokenizer via `tiktoken`; records the encoding (estimated=false)."""

    def __init__(self, encoding: str = "cl100k_base") -> None:
        try:
            import tiktoken
        except ImportError as exc:  # pragma: no cover - depends on environment
            raise RuntimeError(
                "tiktoken is not installed; install it or use CharDiv4TokenCounter"
            ) from exc
        self._encoding = tiktoken.get_encoding(encoding)
        self.name = "tiktoken"
        self.method = "tiktoken"
        self.encoding = encoding
        self.estimated = False

    def count(self, text: str) -> int:
        return len(self._encoding.encode(text))

    def config(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "encoding": self.encoding,
            "method": self.method,
            "estimated": self.estimated,
        }


class ContextCandidate(BaseModel):
    """A ranked item plus the text and optional graph explanation to select."""

    item: RankedItem
    content: str = ""
    graph_path: tuple[str, ...] | None = None
    expansion_explanation: str | None = None
    evidence_type: str | None = None
    repo: str | None = None

    @property
    def evidence_id(self) -> str:
        return self.item.evidence_id

    @classmethod
    def from_item(
        cls,
        item: RankedItem,
        content: str = "",
        *,
        graph_path: tuple[str, ...] | None = None,
        expansion_explanation: str | None = None,
        evidence_type: str | None = None,
        repo: str | None = None,
    ) -> ContextCandidate:
        return cls(
            item=item,
            content=content,
            graph_path=graph_path,
            expansion_explanation=expansion_explanation,
            evidence_type=evidence_type,
            repo=repo,
        )


class SelectedItem(BaseModel):
    """One kept evidence item; field names align with the draft `evidence_item`.

    Manifest-level fields (`run_id`, `created_at`) are intentionally absent —
    they belong to A5.2 and remain blocked on C3 finalization.
    """

    evidence_id: str
    evidence_type: str | None = None
    repo: str | None = None
    revision: str
    file_path: str
    symbol: str | None = None
    lines: tuple[int, int] | None = None
    strategy: str
    rank: int = Field(ge=1)
    score: float
    provenance: Provenance
    source: str
    graph_path: tuple[str, ...] | None = None
    expansion_explanation: str | None = None
    selection_reason: SelectionReason
    token_contribution: int = Field(ge=0)


class ExcludedItem(BaseModel):
    evidence_id: str
    strategy: str
    rank: int = Field(ge=1)
    reason: ExclusionReason
    token_contribution: int | None = Field(default=None, ge=0)


class ContextBudget(BaseModel):
    token_limit: int = Field(gt=0)
    tokenizer: dict[str, Any]
    estimated: bool


class ContextTotals(BaseModel):
    tokens: int = Field(ge=0)
    item_count: int = Field(ge=0)
    duplicates: int = Field(ge=0)


class ContextSelection(BaseModel):
    """Selection output. `totals.tokens <= budget.token_limit` is enforced."""

    items: list[SelectedItem] = Field(default_factory=list)
    excluded: list[ExcludedItem] = Field(default_factory=list)
    budget: ContextBudget
    totals: ContextTotals
    config: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_bounds(self) -> ContextSelection:
        if self.totals.tokens > self.budget.token_limit:
            raise ValueError(
                f"totals.tokens {self.totals.tokens} exceeds token_limit {self.budget.token_limit}"
            )
        if self.totals.item_count != len(self.items):
            raise ValueError("totals.item_count must equal len(items)")
        accounted = sum(item.token_contribution for item in self.items)
        if accounted != self.totals.tokens:
            raise ValueError("totals.tokens must equal the sum of item contributions")
        return self


class ContextSelector:
    """Deterministic budget/diversity selection over ranked candidates."""

    def __init__(
        self,
        counter: TokenCounter,
        *,
        max_items_per_file: int | None = None,
        max_items_per_source: int | None = None,
    ) -> None:
        if max_items_per_file is not None and max_items_per_file < 1:
            raise ValueError("max_items_per_file must be >= 1 or None")
        if max_items_per_source is not None and max_items_per_source < 1:
            raise ValueError("max_items_per_source must be >= 1 or None")
        self.counter = counter
        self.max_items_per_file = max_items_per_file
        self.max_items_per_source = max_items_per_source

    def select(
        self, candidates: Sequence[ContextCandidate], *, token_limit: int
    ) -> ContextSelection:
        if token_limit < 1:
            raise ValueError("token_limit must be >= 1")
        budget = ContextBudget(
            token_limit=token_limit,
            tokenizer=self.counter.config(),
            estimated=self.counter.estimated,
        )
        config: dict[str, Any] = {
            "selector": "context_selector",
            "max_items_per_file": self.max_items_per_file,
            "max_items_per_source": self.max_items_per_source,
            "ordering": "rank_then_evidence_id",
        }

        ordered = sorted(candidates, key=lambda c: (c.item.rank, c.evidence_id))

        kept: list[tuple[ContextCandidate, int, SelectionReason]] = []
        excluded: list[ExcludedItem] = []
        seen: set[str] = set()
        duplicates = 0
        tokens = 0
        file_counts: dict[str, int] = {}
        source_counts: dict[str, int] = {}

        for cand in ordered:
            if cand.evidence_id in seen:
                duplicates += 1
                excluded.append(self._excluded(cand, ExclusionReason.DUPLICATE, None))
                continue
            seen.add(cand.evidence_id)
            cost = self._cost(cand)

            if cost > token_limit:
                excluded.append(self._excluded(cand, ExclusionReason.ITEM_TOO_LARGE, cost))
                continue
            if self._over_cap(cand, file_counts, source_counts):
                excluded.append(self._excluded(cand, ExclusionReason.DIVERSITY_CAP, cost))
                continue
            if cost > token_limit - tokens:
                excluded.append(self._excluded(cand, ExclusionReason.OVER_BUDGET, cost))
                continue
            reason = (
                SelectionReason.DIVERSITY_SPREAD
                if file_counts.get(cand.item.target.file, 0) == 0
                else SelectionReason.TOP_RANKED
            )
            kept.append((cand, cost, reason))
            tokens += cost
            self._account(cand, file_counts, source_counts)

        items = [self._selected(cand, cost, reason) for cand, cost, reason in kept]
        return ContextSelection(
            items=items,
            excluded=excluded,
            budget=budget,
            totals=ContextTotals(tokens=tokens, item_count=len(items), duplicates=duplicates),
            config=config,
        )

    def _cost(self, cand: ContextCandidate) -> int:
        return self.counter.count(cand.content)

    def _over_cap(
        self,
        cand: ContextCandidate,
        file_counts: dict[str, int],
        source_counts: dict[str, int],
    ) -> bool:
        if (
            self.max_items_per_file is not None
            and file_counts.get(cand.item.target.file, 0) >= self.max_items_per_file
        ):
            return True
        return (
            self.max_items_per_source is not None
            and source_counts.get(cand.item.source, 0) >= self.max_items_per_source
        )

    @staticmethod
    def _account(
        cand: ContextCandidate,
        file_counts: dict[str, int],
        source_counts: dict[str, int],
    ) -> None:
        file_counts[cand.item.target.file] = file_counts.get(cand.item.target.file, 0) + 1
        source_counts[cand.item.source] = source_counts.get(cand.item.source, 0) + 1

    @staticmethod
    def _selected(cand: ContextCandidate, cost: int, reason: SelectionReason) -> SelectedItem:
        item = cand.item
        return SelectedItem(
            evidence_id=item.evidence_id,
            evidence_type=cand.evidence_type,
            repo=cand.repo,
            revision=item.source_revision,
            file_path=item.target.file,
            symbol=item.target.symbol,
            lines=item.target.lines,
            strategy=item.strategy,
            rank=item.rank,
            score=item.score,
            provenance=item.provenance,
            source=item.source,
            graph_path=cand.graph_path,
            expansion_explanation=cand.expansion_explanation,
            selection_reason=reason,
            token_contribution=cost,
        )

    @staticmethod
    def _excluded(
        cand: ContextCandidate, reason: ExclusionReason, cost: int | None
    ) -> ExcludedItem:
        return ExcludedItem(
            evidence_id=cand.evidence_id,
            strategy=cand.item.strategy,
            rank=cand.item.rank,
            reason=reason,
            token_contribution=cost,
        )


def candidates_from_result(
    result: RetrievalResult,
    content_resolver: Callable[[RankedItem], str],
    *,
    explain: Callable[[str], GraphPath | None] | None = None,
    repo: str | None = None,
    evidence_type: str | None = None,
) -> list[ContextCandidate]:
    """Adapt a C2 `RetrievalResult` (e.g. pipeline output) into candidates.

    `content_resolver` supplies the text to token-count per item; `explain`
    (optional) supplies the graph path for expanded items. This is the only
    coupling needed between retrieval and context selection.
    """
    candidates: list[ContextCandidate] = []
    for item in result.items:
        path = explain(item.evidence_id) if explain is not None else None
        candidates.append(
            ContextCandidate.from_item(
                item,
                content_resolver(item),
                graph_path=path.node_ids if path is not None else None,
                expansion_explanation=path.source_label if path is not None else None,
                repo=repo,
                evidence_type=evidence_type,
            )
        )
    return candidates
