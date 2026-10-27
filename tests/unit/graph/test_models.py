"""Unit tests for C1 graph models."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from tracefix.graph.models import (
    Edge,
    Node,
    Provenance,
    content_hash,
    make_entity_id,
    normalize_repo_url,
)

REV = "a" * 40


def test_node_rejects_short_revision() -> None:
    with pytest.raises(ValidationError, match="full 40-char git SHA"):
        Node(
            entity_id="x",
            kind="File",
            repo="r",
            revision="abc",
            properties={"path": "a.py"},
            ingested_at="t",
        )


def test_inferred_edge_requires_confidence() -> None:
    with pytest.raises(ValidationError, match="confidence"):
        Edge(
            edge_type="CALLS",
            source_id="s",
            target_id="t",
            provenance=Provenance.INFERRED,
            source="name-heuristic",
            revision=REV,
        )


def test_observed_edge_without_confidence_is_valid() -> None:
    edge = Edge(
        edge_type="CALLS",
        source_id="s",
        target_id="t",
        provenance=Provenance.OBSERVED,
        source="name-resolution",
        revision=REV,
    )
    assert edge.confidence is None


def test_make_entity_id_is_revision_independent() -> None:
    a = make_entity_id("https://github.com/Org/Repo.git", "Function", "mod.fn")
    b = make_entity_id("https://github.com/org/repo", "Function", "mod.fn")
    assert a == b == "https://github.com/org/repo#Function:mod.fn"


def test_normalize_repo_url_handles_ssh_and_case() -> None:
    assert normalize_repo_url("git@github.com:Org/Repo.git") == "https://github.com/org/repo"


def test_content_hash_is_sha256_hex() -> None:
    digest = content_hash("hello")
    assert len(digest) == 64 and digest == content_hash("hello")
