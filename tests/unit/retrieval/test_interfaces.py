"""Retrieval interface invariants (C2 semantics)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from tracefix.graph.models import Provenance
from tracefix.retrieval.interfaces import (
    EvidenceTarget,
    PartialReason,
    RankedItem,
    RetrievalLimits,
    RetrievalQuery,
    RetrievalResult,
)

REV = "e" * 40


def _item(rank: int, evidence_id: str = "x") -> RankedItem:
    return RankedItem(
        evidence_id=evidence_id,
        strategy="lexical",
        rank=rank,
        score=1.0,
        target=EvidenceTarget(file="a.py"),
        source_revision=REV,
        provenance=Provenance.OBSERVED,
        source="bm25",
    )


def _query(k: int = 5) -> RetrievalQuery:
    return RetrievalQuery(
        case_id="c1",
        text="bug",
        revision=REV,
        k=k,
        limits=RetrievalLimits(max_items=10, max_hops=0, timeout_ms=1000),
    )


def test_query_bounds_validated() -> None:
    with pytest.raises(ValidationError):
        RetrievalQuery(
            case_id="c",
            text="x",
            revision=REV,
            k=0,
            limits=RetrievalLimits(max_items=10, max_hops=0, timeout_ms=1000),
        )
    with pytest.raises(ValidationError):
        RetrievalLimits(max_items=0, max_hops=0, timeout_ms=1000)


def test_dense_1_based_ranks_required() -> None:
    with pytest.raises(ValidationError, match="dense"):
        RetrievalResult(
            items=[_item(2)],
            complete=True,
            strategy="lexical",
            revision=REV,
            elapsed_ms=1.0,
        )


def test_incomplete_result_requires_partial_reason() -> None:
    with pytest.raises(ValidationError, match="partial_reason"):
        RetrievalResult(items=[], complete=False, strategy="lexical", revision=REV, elapsed_ms=1.0)


def test_failure_result_cannot_carry_items() -> None:
    from tracefix.retrieval.interfaces import Failure

    with pytest.raises(ValidationError, match="must not carry items"):
        RetrievalResult(
            items=[_item(1)],
            complete=False,
            partial_reason=PartialReason.GRAPH_UNAVAILABLE,
            failure=Failure(error_type="GraphConnectionError", detail="down"),
            strategy="graph_guided",
            revision=REV,
            elapsed_ms=1.0,
        )


def test_valid_degraded_result() -> None:
    result = RetrievalResult(
        items=[_item(1, "a"), _item(2, "b")],
        complete=False,
        partial_reason=PartialReason.LIMIT_REACHED,
        strategy="lexical",
        revision=REV,
        elapsed_ms=2.0,
    )
    assert result.partial_reason is PartialReason.LIMIT_REACHED
