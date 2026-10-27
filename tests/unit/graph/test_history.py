"""Git history ingestion tests (A1.5): commits, authors, file changes, ownership."""

from __future__ import annotations

from pathlib import Path

from tracefix.graph.ingestion import _parse_git_log, ingest_repository
from tracefix.graph.models import Provenance


def test_parse_git_log_handles_nul_separated_format() -> None:
    sep = "\x00"
    first = sep.join(
        ["a" * 40, "Ann", "ann@x.dev", "2026-01-01T00:00:00+00:00", "b" * 40, "msg one"]
    )
    second = sep.join(["c" * 40, "Bob", "bob@x.dev", "2026-01-02T00:00:00+00:00", "", "msg two"])
    raw = f"{first}\ncore.py\nutils.py\n{second}\n"
    commits = _parse_git_log(raw)
    assert [c["subject"] for c in commits] == ["msg one", "msg two"]
    assert commits[0]["files"] == ["core.py", "utils.py"]
    assert commits[0]["parents"] == "b" * 40
    assert commits[1]["parents"] == ""


def test_history_nodes_and_edges(mini_repo: Path, mini_repo_url: str) -> None:
    result = ingest_repository(mini_repo, mini_repo_url, ingested_at="2026-10-16T00:00:00+00:00")
    assert result.history_available is True
    commits = [n for n in result.nodes.values() if n.kind == "Commit"]
    people = [n for n in result.nodes.values() if n.kind == "Person"]
    assert len(commits) >= 2
    assert people and people[0].properties["identity"] == "fixture@tracefix.dev"

    authored = [e for e in result.edges if e.edge_type == "AUTHORED_BY"]
    assert len(authored) == len(commits)
    assert all(e.provenance is Provenance.OBSERVED for e in authored)

    modified = [e for e in result.edges if e.edge_type == "MODIFIED_IN"]
    core_files = {e.source_id for e in modified if e.source_id.endswith("#File:calc/core.py")}
    assert core_files, "core.py should be MODIFIED_IN at least one commit"

    owned = [e for e in result.edges if e.edge_type == "OWNED_BY"]
    assert owned, "expected inferred ownership edges"
    assert all(e.provenance is Provenance.INFERRED for e in owned)
    assert all("weight" in e.properties for e in owned)


def test_shallow_or_missing_git_reports_history_unavailable(
    tmp_path: Path, mini_repo_url: str
) -> None:
    repo = tmp_path / "nogit"
    repo.mkdir()
    (repo / "mod.py").write_text("def f():\n    return 1\n")
    result = ingest_repository(
        repo, mini_repo_url, revision="d" * 40, ingested_at="2026-10-16T00:00:00+00:00"
    )
    assert result.history_available is False
    assert "Commit" not in {n.kind for n in result.nodes.values()}
    assert any(n.kind == "Function" for n in result.nodes.values())
