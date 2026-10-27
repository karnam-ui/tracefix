"""End-to-End Acceptance Test for TraceFix Local Developer Tool.

Validates the full developer journey using a real Git repository fixture:
1. Register / connect local Git repository
2. Inspect revision & detect working tree state
3. Ingest supported source files & build revision graph snapshot
4. Submit a real bug report
5. Run graph-guided investigation across lifecycle
6. Retrieve actual evidence grounded in repository symbols
7. Produce bounded context manifest with token accounting
8. Run simultaneous lexical baseline comparison
9. Query graph neighborhood from generated snapshot
10. Truthful repair availability check without synthetic success
11. Disconnect repository cleanly
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from tracefix.api.app import app


def test_full_developer_tool_journey(mini_repo: Path) -> None:
    client = TestClient(app)

    # 1. Connect local Git repository
    connect_res = client.post(
        "/api/repos/connect",
        json={"path": str(mini_repo), "name": "mini-calc-fixture"},
    )
    assert connect_res.status_code == 200, connect_res.text
    repo_data = connect_res.json()
    repo_id = repo_data["repo_id"]
    assert repo_data["name"] == "mini-calc-fixture"
    assert len(repo_data["working_revision"]) == 40
    assert repo_data["python_file_count"] >= 3
    assert repo_data["status"] == "not_indexed"

    # 2. Ingest repository AST & Git metadata into graph
    ingest_res = client.post(f"/api/repos/{repo_id}/ingest")
    assert ingest_res.status_code == 200, ingest_res.text
    ingest_data = ingest_res.json()
    assert ingest_data["status"] == "ready"
    assert ingest_data["node_count"] > 0
    assert ingest_data["edge_count"] > 0
    graph_name = ingest_data["graph_name"]

    # 3. Select as active repository and verify
    select_res = client.post(f"/api/repos/select?repo_id={repo_id}")
    assert select_res.status_code == 200
    active_repo = select_res.json()
    assert active_repo["repo_id"] == repo_id
    assert active_repo["graph_available"] is True
    assert active_repo["indexed_revision"] == active_repo["working_revision"]

    active_res = client.get("/api/repos/active")
    assert active_res.status_code == 200
    assert active_res.json()["repo_id"] == repo_id

    # 4. Submit known bug report for graph-guided investigation
    investigate_payload = {
        "repo_id": repo_id,
        "bug_report": "Error in add function inside calc.core when operating on numbers",
        "mode": "trace",
        "strategy": "graph",
        "budget": 2000,
        "compare_baseline": True,
        "mock": False,
        "execute_repair": False,
    }
    inv_res = client.post("/api/investigate", json=investigate_payload)
    assert inv_res.status_code == 200, inv_res.text
    inv_data = inv_res.json()

    # 5. Verify investigation results are grounded in real repo files
    assert inv_data["repo_id"] == repo_id
    assert inv_data["strategy_used"] == "graph"
    assert len(inv_data["stages"]) >= 4

    retrieval_items = inv_data["retrieval"]
    assert len(retrieval_items) > 0
    # Must retrieve calc/core.py or calc/utils.py
    files_retrieved = {it["file"] for it in retrieval_items}
    assert any("calc" in f for f in files_retrieved)

    # 6. Verify context budgeting
    budget = inv_data["context_budget"]
    assert budget["budget_limit"] == 2000
    assert budget["tokens_used"] > 0
    assert budget["tokens_used"] <= 2000
    assert budget["included_count"] > 0

    context_items = inv_data["context_items"]
    assert len(context_items) > 0
    first_context = context_items[0]
    assert first_context["included"] is True
    assert first_context["token_cost"] > 0

    # 7. Verify baseline comparison
    comp = inv_data["baseline_comparison"]
    assert comp is not None
    assert comp["baseline_strategy"] == "lexical_bm25"
    assert comp["evaluated_strategy"] == "graph"
    assert comp["baseline_tokens"] > 0
    assert comp["evaluated_tokens"] > 0

    # 8. Verify graph neighborhood query on the generated graph
    neighborhood_res = client.get(f"/api/graphs/{graph_name}/neighborhood")
    assert neighborhood_res.status_code == 200, neighborhood_res.text
    nb_data = neighborhood_res.json()
    assert len(nb_data["nodes"]) > 0
    assert len(nb_data["edges"]) > 0
    assert nb_data["source"] in ("snapshot_artifact", "live_falkordb")

    # 9. Verify repair mode when model provider is unconfigured (truthful UNAVAILABLE)
    repair_payload = {
        "repo_id": repo_id,
        "bug_report": "Error in add function inside calc.core",
        "mode": "repair",
        "strategy": "graph",
        "budget": 2000,
        "mock": False,
        "execute_repair": True,
    }
    rep_res = client.post("/api/investigate", json=repair_payload)
    assert rep_res.status_code == 200, rep_res.text
    rep_data = rep_res.json()
    # When no API key is in environment, repair is skipped/unavailable, never fabricated
    assert rep_data["verification"] is not None
    assert rep_data["verification"]["status"] in ("UNAVAILABLE", "NOT_RUN")
    assert rep_data["proposed_patch"] is None

    # 10. Verify single-container SPA root serving
    spa_res = client.get("/")
    assert spa_res.status_code == 200
    assert "TraceFix" in spa_res.text or "<!doctype html>" in spa_res.text.lower()

    # 11. Clean disconnect
    del_res = client.delete(f"/api/repos/{repo_id}")
    assert del_res.status_code == 200
