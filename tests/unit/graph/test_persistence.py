"""Unit and integration tests for graph persistence (Phase 2 / A6c)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tracefix.graph.client import FalkorDBClient
from tracefix.graph.models import Edge, Node, Provenance
from tracefix.graph.persistence import (
    get_revision_graph_name,
    load_graph_snapshot,
    persist_snapshot_to_falkordb,
    save_graph_snapshot,
)
from tracefix.graph.query import FalkorNeighborhoodProvider

REV = "a" * 40
REPO = "https://example.test/repo"


def test_get_revision_graph_name() -> None:
    rev1 = "22623bd8c265b78b161542663ee980738441c307"
    assert get_revision_graph_name("requests", rev1) == "requests_22623bd8"
    rev2 = "2aabb71dc8db434122c2e00c9d1313c6f368ce1c"
    assert get_revision_graph_name("psf/requests", rev2) == "psf_requests_2aabb71d"


def test_disk_snapshot_round_trip(tmp_path: Path) -> None:
    nodes = {
        f"{REPO}#Function:pkg.foo": Node(
            entity_id=f"{REPO}#Function:pkg.foo",
            kind="Function",
            repo=REPO,
            revision=REV,
            properties={
                "path": "pkg.py",
                "qualified_name": "pkg.foo",
                "start_line": 1,
                "end_line": 10,
            },
            ingested_at="2026-10-18T00:00:00+00:00",
        )
    }
    edges = [
        Edge(
            edge_type="CONTAINS",
            source_id=f"{REPO}#File:pkg.py",
            target_id=f"{REPO}#Function:pkg.foo",
            provenance=Provenance.OBSERVED,
            source="ast",
            revision=REV,
            confidence=None,
        )
    ]

    from tracefix.graph.ingestion import IngestionResult

    result = IngestionResult(
        repo=REPO,
        revision=REV,
        nodes=nodes,
        edges=edges,
        history_available=True,
        parse_errors=[],
        stats={"node_count": 1, "edge_count": 1},
        limitations=["test limitation"],
    )

    out_file = tmp_path / "snapshot.json"
    saved_path = save_graph_snapshot(result, out_file)
    assert saved_path.exists()

    envelope = json.loads(saved_path.read_text(encoding="utf-8"))
    assert envelope["schema_version"] == "0.2.0"
    assert envelope["node_count"] == 1
    assert envelope["edge_count"] == 1
    assert "sha256" in envelope

    loaded = load_graph_snapshot(saved_path)
    assert loaded.revision == REV
    assert loaded.repo == REPO
    assert len(loaded.nodes) == 1
    assert len(loaded.edges) == 1
    assert loaded.nodes[f"{REPO}#Function:pkg.foo"].kind == "Function"
    assert loaded.edges[0].edge_type == "CONTAINS"


def test_live_falkordb_persistence_and_neighborhood_query() -> None:
    """Integration test against live FalkorDB instance."""
    graph_name = "test_persistence_suite"
    client = FalkorDBClient(graph_name=graph_name)
    try:
        client.connect()
    except Exception as exc:
        pytest.skip(f"FalkorDB not available on localhost:6379: {exc}")

    # Build small fixture snapshot
    nodes = {
        f"{REPO}#Function:a": Node(
            entity_id=f"{REPO}#Function:a",
            kind="Function",
            repo=REPO,
            revision=REV,
            properties={"path": "m.py", "qualified_name": "m.a", "start_line": 1, "end_line": 5},
            ingested_at="2026-10-18T00:00:00+00:00",
        ),
        f"{REPO}#Function:b": Node(
            entity_id=f"{REPO}#Function:b",
            kind="Function",
            repo=REPO,
            revision=REV,
            properties={"path": "m.py", "qualified_name": "m.b", "start_line": 7, "end_line": 12},
            ingested_at="2026-10-18T00:00:00+00:00",
        ),
    }
    edges = [
        Edge(
            edge_type="CALLS",
            source_id=f"{REPO}#Function:a",
            target_id=f"{REPO}#Function:b",
            provenance=Provenance.OBSERVED,
            source="ast",
            revision=REV,
        )
    ]

    from tracefix.graph.ingestion import IngestionResult

    result = IngestionResult(
        repo=REPO,
        revision=REV,
        nodes=nodes,
        edges=edges,
        history_available=False,
    )

    try:
        counts = persist_snapshot_to_falkordb(client, result, clear_existing=True)
        assert counts["nodes_persisted"] == 2
        assert counts["edges_persisted"] == 1

        # Test querying with FalkorNeighborhoodProvider
        provider = FalkorNeighborhoodProvider(client, direction="both")
        res = provider.neighborhood([f"{REPO}#Function:a"], revision=REV, max_hops=1)
        assert len(res.paths) == 1
        assert res.paths[0].node.entity_id == f"{REPO}#Function:b"
        assert res.paths[0].edges[0].edge_type == "CALLS"

        # Verify revision isolation: querying with wrong revision yields empty
        wrong_res = provider.neighborhood([f"{REPO}#Function:a"], revision="b" * 40, max_hops=1)
        assert len(wrong_res.paths) == 0

    finally:
        try:
            if client._graph is not None:
                client._graph.delete()
        except Exception:
            pass
        client.close()
