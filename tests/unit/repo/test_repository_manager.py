"""Unit tests for RepositoryManager and local repository workflows."""

from __future__ import annotations

from pathlib import Path

import pytest

from tracefix.repo.manager import RepositoryManager, RepositoryValidationError
from tracefix.repo.models import RepositoryStatus


def test_validate_local_path_success(mini_repo: Path, tmp_path: Path) -> None:
    mgr = RepositoryManager(persistence_file=tmp_path / "repos.json", root_dir=tmp_path)
    resolved, sha, branch = mgr.validate_local_path(str(mini_repo))
    assert resolved == mini_repo.resolve()
    assert len(sha) == 40
    assert branch in ("master", "main")


def test_validate_local_path_not_exists(tmp_path: Path) -> None:
    mgr = RepositoryManager(persistence_file=tmp_path / "repos.json", root_dir=tmp_path)
    with pytest.raises(RepositoryValidationError, match="does not exist"):
        mgr.validate_local_path(str(tmp_path / "non_existent"))


def test_validate_local_path_not_git(tmp_path: Path) -> None:
    not_git = tmp_path / "regular_dir"
    not_git.mkdir()
    mgr = RepositoryManager(persistence_file=tmp_path / "repos.json", root_dir=tmp_path)
    with pytest.raises(RepositoryValidationError, match="not a valid Git repository"):
        mgr.validate_local_path(str(not_git))


def test_connect_and_switch_repository(mini_repo: Path, tmp_path: Path) -> None:
    mgr = RepositoryManager(persistence_file=tmp_path / "repos.json", root_dir=tmp_path)
    repo = mgr.connect_repository(str(mini_repo), name="mini-calc")

    assert repo.repo_id == "mini-calc"
    assert repo.name == "mini-calc"
    assert repo.status == RepositoryStatus.NOT_INDEXED
    assert repo.python_file_count >= 3
    assert repo.is_active is True

    # Check listing
    repos = mgr.list_repositories()
    assert len(repos) >= 1
    assert any(r.repo_id == "mini-calc" for r in repos)

    # Ingest repository
    res = mgr.ingest_repository_graph("mini-calc")
    assert len(res.nodes) > 0
    assert len(res.edges) > 0

    reloaded = mgr.get_repository("mini-calc")
    assert reloaded is not None
    assert reloaded.status == RepositoryStatus.READY
    assert reloaded.graph_available is True
    assert reloaded.indexed_revision == reloaded.working_revision
    assert reloaded.node_count == len(res.nodes)

    # Disconnect
    assert mgr.disconnect_repository("mini-calc") is True
    assert mgr.get_repository("mini-calc") is None
