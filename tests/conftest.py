"""Shared fixtures: a git-backed copy of tests/fixtures/mini_repo."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

FIXTURES = Path(__file__).resolve().parent / "fixtures"
MINI_REPO_SOURCE = FIXTURES / "mini_repo"


def _git(repo: Path, *args: str) -> str:
    out = subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.email=fixture@tracefix.dev",
            "-c",
            "user.name=TraceFix Fixture",
            *args,
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return out.stdout.strip()


@pytest.fixture
def mini_repo(tmp_path: Path) -> Path:
    """A real git repository (2 commits) built from the mini fixture tree."""
    repo = tmp_path / "mini_repo"
    shutil.copytree(MINI_REPO_SOURCE, repo)
    _git(repo, "init", "-q")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "initial fixture")
    utils = repo / "calc" / "utils.py"
    utils.write_text(utils.read_text() + "\n\ndef identity(x):\n    return x\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "add identity helper")
    return repo


@pytest.fixture
def mini_repo_url() -> str:
    return "https://github.com/tracefix/mini-repo.git"
