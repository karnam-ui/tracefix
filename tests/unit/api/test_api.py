"""Unit tests for TraceFix FastAPI endpoints."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tracefix.api.app import app


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_health_endpoint(client: TestClient) -> None:
    res = client.get("/api/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] in ("ok", "degraded")
    assert data["version"] == "0.0.1"
    assert "falkordb_connected" in data
    assert "active_cases_count" in data
    assert data["active_cases_count"] >= 5


def test_list_cases_endpoint(client: TestClient) -> None:
    res = client.get("/api/cases")
    assert res.status_code == 200
    cases = res.json()
    assert isinstance(cases, list)
    assert len(cases) >= 5
    first = cases[0]
    assert "case_id" in first
    assert "revision" in first
    assert "localizable" in first
    assert "bug_report_preview" in first


def test_list_graphs_endpoint(client: TestClient) -> None:
    res = client.get("/api/graphs")
    assert res.status_code == 200
    graphs = res.json()
    assert isinstance(graphs, list)
    assert len(graphs) >= 5
    first = graphs[0]
    assert "graph_name" in first
    assert "node_count" in first
    assert "edge_count" in first


def test_investigate_endpoint(client: TestClient) -> None:
    payload = {
        "case_id": "psf__requests-1142",
        "strategy": "graph",
        "budget": 4000,
        "mock": True,
        "execute_repair": True,
    }
    res = client.post("/api/investigate", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["case_id"] == "psf__requests-1142"
    assert data["strategy_used"] == "graph"
    assert len(data["stages"]) >= 6
    assert len(data["retrieval"]) > 0
    assert "tokens_used" in data["context_budget"]
    assert data["proposed_patch"] is not None
    assert data["verification"]["status"] == "VERIFIED"


def test_list_evaluations_endpoint(client: TestClient) -> None:
    res = client.get("/api/evaluations")
    assert res.status_code == 200
    evals = res.json()
    assert isinstance(evals, list)
    assert len(evals) > 0
    assert any("retrieval_pilot_report" in e["file_name"] for e in evals)


def test_neighborhood_endpoint(client: TestClient) -> None:
    res = client.get("/api/graphs/requests_22623bd8/neighborhood")
    assert res.status_code == 200
    data = res.json()
    assert data["graph_name"] == "requests_22623bd8"
    assert "nodes" in data
    assert "edges" in data


def test_memory_endpoint(client: TestClient) -> None:
    res = client.get("/api/memory")
    assert res.status_code == 200
    data = res.json()
    assert isinstance(data, list)


def test_repository_endpoints(client: TestClient, tmp_path: Path) -> None:
    # 1. List repos
    res = client.get("/api/repos")
    assert res.status_code == 200
    repos = res.json()
    assert isinstance(repos, list)

    # 2. Connect invalid path
    res = client.post("/api/repos/connect", json={"path": str(tmp_path / "missing")})
    assert res.status_code == 400

    # 3. Create dummy git repo and connect
    import subprocess

    repo_dir = tmp_path / "test_api_repo"
    repo_dir.mkdir()
    subprocess.run(["git", "-C", str(repo_dir), "init", "-q"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(repo_dir),
            "-c",
            "user.email=t@t.com",
            "-c",
            "user.name=T",
            "commit",
            "--allow-empty",
            "-m",
            "init",
        ],
        check=True,
    )
    (repo_dir / "app.py").write_text("def hello():\n    return 'world'\n")
    subprocess.run(["git", "-C", str(repo_dir), "add", "app.py"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(repo_dir),
            "-c",
            "user.email=t@t.com",
            "-c",
            "user.name=T",
            "commit",
            "-m",
            "add app",
        ],
        check=True,
    )

    res = client.post("/api/repos/connect", json={"path": str(repo_dir), "name": "api-test-repo"})
    assert res.status_code == 200
    r_data = res.json()
    assert r_data["name"] == "api-test-repo"
    repo_id = r_data["repo_id"]

    # Ingest repo
    res = client.post(f"/api/repos/{repo_id}/ingest")
    assert res.status_code == 200
    ing_data = res.json()
    assert ing_data["status"] == "ready"
    assert ing_data["node_count"] > 0

    # Disconnect repo
    res = client.delete(f"/api/repos/{repo_id}")
    assert res.status_code == 200
