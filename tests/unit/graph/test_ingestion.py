"""Ingestion tests: AST parsing, provenance, errors, idempotency, revision (A1.4-A1.7)."""

from __future__ import annotations

from pathlib import Path

import pytest

from tracefix.graph.ingestion import (
    IngestionError,
    ingest_repository,
    is_test_file,
    module_qualified_name,
)
from tracefix.graph.models import Provenance


def _qid(repo_url: str, kind: str, key: str) -> str:
    return f"https://github.com/tracefix/mini-repo#{kind}:{key}"


@pytest.fixture
def snapshot(mini_repo: Path, mini_repo_url: str):
    return ingest_repository(mini_repo, mini_repo_url, ingested_at="2026-10-16T00:00:00+00:00")


def test_module_qualified_name_variants() -> None:
    assert module_qualified_name("src/pkg/mod.py") == "pkg.mod"
    assert module_qualified_name("pkg/__init__.py") == "pkg"
    assert module_qualified_name("top.py") == "top"


def test_is_test_file_detection() -> None:
    assert is_test_file("tests/test_core.py")
    assert is_test_file("pkg/tests/helper_test.py")
    assert not is_test_file("calc/core.py")


def test_expected_symbols_extracted(snapshot) -> None:
    kinds = {n.properties.get("qualified_name"): n.kind for n in snapshot.nodes.values()}
    assert kinds["calc.core.add"] == "Function"
    assert kinds["calc.core.Calculator"] == "Class"
    assert kinds["calc.core.Calculator.total"] == "Function"
    assert kinds["tests.test_core.test_add"] == "Test"
    assert kinds["calc.utils.scale"] == "Function"  # added by second fixture commit


def test_contains_and_import_edges(snapshot) -> None:
    by_type = {}
    for e in snapshot.edges:
        by_type.setdefault(e.edge_type, []).append(e)
    assert by_type["CONTAINS"], "expected CONTAINS edges"
    imports = by_type["IMPORTS"]
    assert any(
        e.source_id == _qid("", "Module", "calc.utils")
        and e.target_id == _qid("", "Module", "calc.core")
        for e in imports
    ), "calc.utils should import calc.core"
    assert all(e.provenance is Provenance.OBSERVED for e in imports)


def test_call_resolution_provenance(snapshot) -> None:
    calls = {
        (e.source_id, e.target_id, e.provenance) for e in snapshot.edges if e.edge_type == "CALLS"
    }
    accumulate = _qid("", "Function", "calc.core.accumulate")
    add = _qid("", "Function", "calc.core.add")
    assert (accumulate, add, Provenance.OBSERVED) in calls
    total = _qid("", "Function", "calc.core.Calculator.total")
    assert (total, accumulate, Provenance.OBSERVED) in calls
    sum_list = _qid("", "Function", "calc.utils.sum_list")
    assert (sum_list, add, Provenance.OBSERVED) in calls


def test_external_import_creates_no_edge(snapshot) -> None:
    core_file = next(
        n
        for n in snapshot.nodes.values()
        if n.kind == "File" and n.properties["path"] == "calc/core.py"
    )
    assert "os" in core_file.properties["imports_declared"]
    module_ids = {n.entity_id for n in snapshot.nodes.values() if n.kind == "Module"}
    assert _qid("", "Module", "os") not in module_ids


def test_covered_by_is_inferred(snapshot) -> None:
    coverage = [e for e in snapshot.edges if e.edge_type == "COVERED_BY"]
    assert coverage, "expected heuristic coverage edges"
    assert all(e.provenance is Provenance.INFERRED for e in coverage)
    assert all(e.confidence == "heuristic" for e in coverage)
    add = _qid("", "Function", "calc.core.add")
    assert any(e.source_id == add for e in coverage)


def test_parse_errors_recorded_and_file_node_kept(snapshot) -> None:
    assert any("syntax error" in e["error"] for e in snapshot.parse_errors)
    broken = [
        n
        for n in snapshot.nodes.values()
        if n.kind == "File" and "syntax_error" in n.properties["path"]
    ]
    assert broken, "file with syntax error still gets a File node"


def test_every_node_stamped_with_revision(snapshot) -> None:
    assert all(n.revision == snapshot.revision for n in snapshot.nodes.values())
    assert all(e.revision == snapshot.revision for e in snapshot.edges)


def test_ingestion_is_idempotent(mini_repo: Path, mini_repo_url: str) -> None:
    stamp = "2026-10-16T00:00:00+00:00"
    first = ingest_repository(mini_repo, mini_repo_url, ingested_at=stamp)
    second = ingest_repository(mini_repo, mini_repo_url, ingested_at=stamp)
    assert first.node_properties() == second.node_properties()
    assert first.edge_identities() == second.edge_identities()


def test_history_can_be_disabled(snapshot) -> None:
    assert snapshot.history_available is True
    kinds = {n.kind for n in snapshot.nodes.values()}
    assert "Commit" in kinds and "Person" in kinds


def test_include_history_false_hides_history(mini_repo: Path, mini_repo_url: str) -> None:
    result = ingest_repository(
        mini_repo, mini_repo_url, include_history=False, ingested_at="2026-10-16T00:00:00+00:00"
    )
    assert result.history_available is False
    assert "Commit" not in {n.kind for n in result.nodes.values()}


def test_missing_revision_on_non_git_tree_raises(tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    with pytest.raises(IngestionError, match="revision required"):
        ingest_repository(plain, "https://github.com/tracefix/plain")


def test_unreadable_file_is_reported_not_fatal(mini_repo: Path, mini_repo_url: str) -> None:
    # invalid utf-8 bytes -> unreadable, recorded, ingestion continues
    bad = mini_repo / "calc" / "binary.py"
    bad.write_bytes(b"\xff\xfe\x00invalid")
    result = ingest_repository(mini_repo, mini_repo_url, ingested_at="2026-10-16T00:00:00+00:00")
    assert any("unreadable" in e["error"] for e in result.parse_errors)
    assert any(
        n.kind == "Function" and "calc.core.add" in str(n.properties.get("qualified_name"))
        for n in result.nodes.values()
    )
