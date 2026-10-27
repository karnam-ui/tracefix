"""Instance-level contract tests for contracts/graph_schema.json (task A1.1).

A valid snapshot validates; invalid snapshots are rejected with
SchemaValidationError. The final test validates a real ingestion snapshot.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tracefix.graph.ingestion import ingest_repository
from tracefix.graph.models import Edge, Node, Provenance
from tracefix.graph.schema import GraphSchema, SchemaValidationError

REV = "b" * 40


def _node(entity_id: str, kind: str, **props: object) -> Node:
    return Node(
        entity_id=entity_id,
        kind=kind,
        repo="https://github.com/tracefix/mini-repo",
        revision=REV,
        properties=dict(props),
        ingested_at="2026-10-16T00:00:00+00:00",
    )


@pytest.fixture
def schema() -> GraphSchema:
    return GraphSchema.load()


@pytest.fixture
def valid_snapshot() -> tuple[list[Node], list[Edge]]:
    repo = "https://github.com/tracefix/mini-repo"
    nodes = [
        _node(f"{repo}#Repository:{repo}", "Repository", url=repo),
        _node(f"{repo}#File:core.py", "File", path="core.py", imports_declared=[]),
        _node(f"{repo}#Module:core", "Module", qualified_name="core", path="core.py"),
        _node(
            f"{repo}#Function:core.add",
            "Function",
            qualified_name="core.add",
            path="core.py",
            start_line=1,
            end_line=2,
        ),
    ]
    edges = [
        Edge(
            edge_type="CONTAINS",
            source_id=f"{repo}#File:core.py",
            target_id=f"{repo}#Module:core",
            provenance=Provenance.OBSERVED,
            source="python-ast",
            revision=REV,
        ),
        Edge(
            edge_type="CONTAINS",
            source_id=f"{repo}#Module:core",
            target_id=f"{repo}#Function:core.add",
            provenance=Provenance.OBSERVED,
            source="python-ast",
            revision=REV,
        ),
    ]
    return nodes, edges


def test_valid_snapshot_passes(
    schema: GraphSchema, valid_snapshot: tuple[list[Node], list[Edge]]
) -> None:
    nodes, edges = valid_snapshot
    schema.validate_snapshot(nodes, edges)


def test_undeclared_kind_rejected(
    schema: GraphSchema, valid_snapshot: tuple[list[Node], list[Edge]]
) -> None:
    nodes, edges = valid_snapshot
    nodes.append(
        _node(
            "x#Function:ghost",
            "Ghost",
            path="g.py",
            qualified_name="g",
            start_line=1,
            end_line=1,
        )
    )
    with pytest.raises(SchemaValidationError, match="undeclared node kind"):
        schema.validate_snapshot(nodes, edges)


def test_missing_required_property_rejected(
    schema: GraphSchema, valid_snapshot: tuple[list[Node], list[Edge]]
) -> None:
    nodes, edges = valid_snapshot
    nodes.append(_node("x#File:bad.py", "File"))  # no path property
    with pytest.raises(SchemaValidationError, match="missing required properties"):
        schema.validate_snapshot(nodes, edges)


def test_duplicate_entity_id_rejected(
    schema: GraphSchema, valid_snapshot: tuple[list[Node], list[Edge]]
) -> None:
    nodes, edges = valid_snapshot
    dup = nodes[1]
    nodes.append(_node(dup.entity_id, "File", path="core.py", imports_declared=[]))
    with pytest.raises(SchemaValidationError, match="duplicate entity_id"):
        schema.validate_snapshot(nodes, edges)


def test_edge_with_wrong_source_kind_rejected(
    schema: GraphSchema, valid_snapshot: tuple[list[Node], list[Edge]]
) -> None:
    nodes, edges = valid_snapshot
    edges.append(
        Edge(
            edge_type="CALLS",
            source_id="https://github.com/tracefix/mini-repo#File:core.py",
            target_id="https://github.com/tracefix/mini-repo#Function:core.add",
            provenance=Provenance.OBSERVED,
            source="name-resolution",
            revision=REV,
        )
    )
    with pytest.raises(SchemaValidationError, match="source kind"):
        schema.validate_snapshot(nodes, edges)


def test_edge_with_dangling_endpoint_rejected(
    schema: GraphSchema, valid_snapshot: tuple[list[Node], list[Edge]]
) -> None:
    nodes, edges = valid_snapshot
    edges.append(
        Edge(
            edge_type="CALLS",
            source_id="https://github.com/tracefix/mini-repo#Function:core.add",
            target_id="https://github.com/tracefix/mini-repo#Function:missing",
            provenance=Provenance.OBSERVED,
            source="name-resolution",
            revision=REV,
        )
    )
    with pytest.raises(SchemaValidationError, match="not present in snapshot"):
        schema.validate_snapshot(nodes, edges)


def test_duplicate_edge_rejected(
    schema: GraphSchema, valid_snapshot: tuple[list[Node], list[Edge]]
) -> None:
    nodes, edges = valid_snapshot
    edges.append(edges[0].model_copy())
    with pytest.raises(SchemaValidationError, match="duplicate edge"):
        schema.validate_snapshot(nodes, edges)


def test_real_ingestion_snapshot_validates(mini_repo: Path, mini_repo_url: str) -> None:
    """Acceptance evidence for A1.1: a real snapshot validates against C1."""
    result = ingest_repository(mini_repo, mini_repo_url, ingested_at="2026-10-16T00:00:00+00:00")
    GraphSchema.load().validate_snapshot(list(result.nodes.values()), result.edges)
    assert result.stats["node_count"] > 0
    assert result.parse_errors  # broken/syntax_error.py is in the fixture
