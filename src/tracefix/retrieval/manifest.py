"""Context manifest (A5): reproducible context records built from selection.

This module assembles the **stable, contract-supported** subset of
`contracts/context_manifest.json` (v0.1.0-draft). It is deliberately *not* the
finalization of contract C3: the draft stays `draft-pending-workstream-b-review`
and every unresolved decision is isolated here rather than guessed.

What is recorded (derivable today)
----------------------------------
- ``repo`` and ``revision``: the source snapshot. ``revision`` comes from the
  retrieval result when present, otherwise from the caller, otherwise from the
  selected items. It is required once any item exists.
- ``budget`` / ``totals``: token-budget accounting carried straight from
  ``ContextSelection``, including the exact-vs-estimated label.
- ``strategy_config``: the retrieval and selector configuration that produced
  the items (a serializable dict).
- ``items``: one :class:`EvidenceItem` per selected item, preserving
  ``evidence_id``, ``strategy``, ``rank``, ``score``, ``source``,
  ``provenance``, target, ``selection_reason``, ``token_contribution``,
  ``graph_path`` and ``expansion_explanation`` for traceability.

What is intentionally left open (C3 / Workstream B)
---------------------------------------------------
- ``run_id`` / ``case_id`` / ``created_at`` are **optional** and never
  invented. Cross-run evidence identity (Q-B3) and budget ownership/scope
  (Q-B1/Q-B2) are unresolved, so the manifest records what it is given.
- The tokenizer is copied verbatim from the selection; tokenizer compatibility
  (D4) is the caller's concern.
- No raw content is stored (the draft ``evidence_item`` has no content field);
  transport and raw-content policy (Q-B5/Q-B6) are not chosen here.

Validation (enforced on construction)
-------------------------------------
- ``totals.item_count == len(items)``
- ``totals.tokens == sum(token_contribution)``
- ``totals.tokens <= budget.token_limit``
- ``evidence_id`` is unique within the manifest
- every item declares a non-empty ``provenance`` and ``source``
- every item's ``revision`` equals the manifest ``revision``

Serialization is deterministic: :meth:`ContextManifest.to_json` uses sorted
keys and omits ``None`` values, so identical inputs round-trip to identical
bytes.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field, model_validator

from tracefix.retrieval.context_selector import ContextSelection, SelectedItem
from tracefix.retrieval.interfaces import RetrievalResult

__all__ = [
    "ManifestError",
    "Budget",
    "Totals",
    "EvidenceItem",
    "ContextManifest",
    "build_manifest",
    "item_from_selected",
]


class ManifestError(ValueError):
    """The manifest cannot be assembled from the supplied artifacts."""


class Budget(BaseModel):
    """Token budget as recorded (ownership is a caller decision, Q-B1)."""

    token_limit: int = Field(gt=0)
    tokenizer: dict[str, Any]
    estimated: bool


class Totals(BaseModel):
    tokens: int = Field(ge=0)
    item_count: int = Field(ge=0)
    duplicates: int = Field(ge=0)


class EvidenceItem(BaseModel):
    """One traceable evidence record; mirrors the draft ``evidence_item``."""

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
    graph_path: tuple[str, ...] | None = None
    expansion_explanation: str | None = None
    selection_reason: str
    token_contribution: int = Field(ge=0)
    provenance: str
    source: str


class ContextManifest(BaseModel):
    """A reproducible record of the context selected for one case revision."""

    repo: str | None = None
    revision: str
    budget: Budget
    strategy_config: dict[str, Any] = Field(default_factory=dict)
    items: list[EvidenceItem] = Field(default_factory=list)
    totals: Totals
    run_id: str | None = None
    case_id: str | None = None
    created_at: str | None = None

    @model_validator(mode="after")
    def _check_invariants(self) -> ContextManifest:
        if self.totals.item_count != len(self.items):
            raise ValueError("totals.item_count != len(items)")
        accounted = sum(item.token_contribution for item in self.items)
        if accounted != self.totals.tokens:
            raise ValueError("totals.tokens != sum of item token contributions")
        if self.totals.tokens > self.budget.token_limit:
            raise ValueError("totals.tokens > budget.token_limit")
        ids = [item.evidence_id for item in self.items]
        if len(ids) != len(set(ids)):
            raise ValueError("evidence_id must be unique within the manifest")
        for item in self.items:
            if not item.provenance or not item.source:
                raise ValueError("every item must declare provenance and source")
            if not item.revision:
                raise ValueError("every item must carry a source revision")
            if item.revision != self.revision:
                raise ValueError(
                    f"item {item.evidence_id!r} revision {item.revision!r} "
                    f"!= manifest revision {self.revision!r}"
                )
        return self

    def to_json(self) -> str:
        """Deterministic serialization (sorted keys, ``None`` omitted)."""
        return json.dumps(self.model_dump(exclude_none=True), sort_keys=True)

    def explain(self, evidence_id: str) -> tuple[str, ...] | None:
        """Graph-path explanation for a selected item, when one was recorded."""
        for item in self.items:
            if item.evidence_id == evidence_id:
                return item.graph_path
        return None


def item_from_selected(selected: SelectedItem, repo: str | None = None) -> EvidenceItem:
    """Map a selector :class:`SelectedItem` onto a manifest ``evidence_item``."""
    return EvidenceItem(
        evidence_id=selected.evidence_id,
        evidence_type=selected.evidence_type,
        repo=repo if repo is not None else selected.repo,
        revision=selected.revision,
        file_path=selected.file_path,
        symbol=selected.symbol,
        lines=selected.lines,
        strategy=selected.strategy,
        rank=selected.rank,
        score=selected.score,
        graph_path=selected.graph_path,
        expansion_explanation=selected.expansion_explanation,
        selection_reason=selected.selection_reason.value,
        token_contribution=selected.token_contribution,
        provenance=selected.provenance.value,
        source=selected.source,
    )


def _resolve_revision(
    selection: ContextSelection,
    retrieval: RetrievalResult | None,
    revision: str | None,
) -> str:
    if revision:
        return revision
    if retrieval is not None and retrieval.revision:
        return retrieval.revision
    if selection.items:
        return selection.items[0].revision
    raise ManifestError("revision is required when there is no retrieval result and no items")


def build_manifest(
    selection: ContextSelection,
    retrieval: RetrievalResult | None = None,
    *,
    repo: str | None = None,
    revision: str | None = None,
    case_id: str | None = None,
    run_id: str | None = None,
    created_at: str | None = None,
) -> ContextManifest:
    """Assemble a validated :class:`ContextManifest` from a context selection.

    ``revision`` defaults to the retrieval result's revision; if neither is
    available and items exist, the items' revision is used. An empty selection
    with no revision supplied raises :class:`ManifestError` rather than
    inventing one.
    """
    strategy_config: dict[str, Any] = {}
    if retrieval is not None:
        strategy_config["retrieval"] = retrieval.config
    strategy_config["selector"] = selection.config

    resolved = _resolve_revision(selection, retrieval, revision)
    return ContextManifest(
        repo=repo,
        revision=resolved,
        budget=Budget(
            token_limit=selection.budget.token_limit,
            tokenizer=selection.budget.tokenizer,
            estimated=selection.budget.estimated,
        ),
        strategy_config=strategy_config,
        items=[item_from_selected(item, repo) for item in selection.items],
        totals=Totals(
            tokens=selection.totals.tokens,
            item_count=selection.totals.item_count,
            duplicates=selection.totals.duplicates,
        ),
        run_id=run_id,
        case_id=case_id,
        created_at=created_at,
    )
