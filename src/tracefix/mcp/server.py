"""TraceFix Model Context Protocol (MCP) STDIO Server.

Provides read-only repository intelligence tools to compatible coding agents:
- list_repositories: List connected repositories and their status.
- find_relevant_code: Locate symbols and files relevant to a query.
- trace_dependencies: Explore structural callers, callees, definitions, and tests.
- build_investigation_context: Assemble budget-constrained context for an agent.
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import MCPServer

from tracefix.api.models import InvestigateRequest
from tracefix.api.service import TraceFixService

logger = logging.getLogger("tracefix.mcp")


def create_mcp_server(service: TraceFixService | None = None) -> MCPServer:
    """Instantiate and configure the TraceFix MCP server."""
    app_service = service or TraceFixService()
    server = MCPServer(
        name="tracefix",
        instructions=(
            "TraceFix is a graph-native repository intelligence and code investigation engine. "
            "Use its tools to locate code relevant to a bug report, trace dependencies, "
            "and build token-budgeted investigation contexts without bloating agent memory."
        ),
    )

    @server.tool()
    def list_repositories() -> str:
        """List all connected repositories available for investigation in TraceFix.

        Returns a JSON string containing repository id, name, local path, branch, revision, status,
        node count, edge count, and whether it is active.
        """
        repos = app_service.list_repositories()
        data = [
            {
                "repo_id": r.repo_id,
                "name": r.name,
                "path": r.local_path,
                "branch": r.default_branch,
                "revision": r.working_revision,
                "short_sha": r.short_sha,
                "status": r.status,
                "node_count": r.node_count,
                "edge_count": r.edge_count,
                "is_active": r.is_active,
                "is_demo": (r.repo_id == "requests"),
            }
            for r in repos
        ]
        return json.dumps({"repositories": data, "count": len(data)}, indent=2)

    @server.tool()
    def find_relevant_code(repository_id: str, query: str, limit: int = 10) -> str:
        """Find functions, classes, and code locations relevant to a query.

        Args:
            repository_id: Identifier of the repository (e.g. 'requests').
            query: The search query, error message, or symbol name.
            limit: Maximum number of relevant code items to return (default 10).

        Returns:
            JSON string containing ranked code locations with file path, line numbers,
            symbols, relevance scores, and provenance.
        """
        repo = app_service.repo_manager.get_repository(repository_id)
        if not repo:
            available = [r.repo_id for r in app_service.list_repositories()]
            return json.dumps(
                {
                    "error": f"Repository '{repository_id}' not found.",
                    "available_repositories": available,
                },
                indent=2,
            )

        req = InvestigateRequest(
            repo_id=repository_id,
            bug_report=query,
            mode="find",
            strategy="graph",
            budget=8000,
        )
        res = app_service.investigate(req)

        items: list[dict[str, Any]] = []
        for r_item in res.retrieval[:limit]:
            start_l, end_l = r_item.lines if r_item.lines else (0, 0)
            items.append(
                {
                    "evidence_id": r_item.evidence_id,
                    "symbol": r_item.symbol,
                    "file_path": r_item.file,
                    "start_line": start_l,
                    "end_line": end_l,
                    "score": round(r_item.score, 4),
                    "provenance": r_item.provenance,
                    "strategy": r_item.strategy,
                }
            )

        return json.dumps(
            {
                "repository_id": repository_id,
                "query": query,
                "strategy_used": res.strategy_used,
                "total_found": len(res.retrieval),
                "returned_count": len(items),
                "items": items,
            },
            indent=2,
        )

    @server.tool()
    def trace_dependencies(repository_id: str, symbol_or_path: str, max_hops: int = 2) -> str:
        """Trace the structural dependency graph around a function, class, or source file.

        Args:
            repository_id: Identifier of the repository (e.g. 'requests').
            symbol_or_path: Symbol (e.g. 'Session.send') or path (e.g. 'requests/sessions.py').
            max_hops: Maximum graph traversal hops (default 2).

        Returns:
            JSON string detailing caller, callee, import, definition, and test relationships.
        """
        repo = app_service.repo_manager.get_repository(repository_id)
        if not repo:
            available = [r.repo_id for r in app_service.list_repositories()]
            return json.dumps(
                {
                    "error": f"Repository '{repository_id}' not found.",
                    "available_repositories": available,
                },
                indent=2,
            )

        graph_name = repo.graph_name or f"{repository_id}_graph"

        # Attempt to find neighborhood around the symbol_or_path
        resp = app_service.get_neighborhood(graph_name, entity_id=symbol_or_path)

        # If not directly found by entity_id, search nodes matching path or symbol
        if not resp.nodes and resp.source != "empty":
            default_resp = app_service.get_neighborhood(graph_name, entity_id=None)
            matching = [
                n
                for n in default_resp.nodes
                if symbol_or_path.lower() in n.qualified_name.lower()
                or symbol_or_path.lower() in n.path.lower()
            ]
            if matching:
                target_id = matching[0].entity_id
                resp = app_service.get_neighborhood(graph_name, entity_id=target_id)

        nodes_data = [
            {
                "entity_id": n.entity_id,
                "kind": n.kind,
                "qualified_name": n.qualified_name,
                "path": n.path,
                "start_line": n.start_line,
                "end_line": n.end_line,
            }
            for n in resp.nodes
        ]

        edges_data = [
            {
                "source": e.source_id,
                "target": e.target_id,
                "relation": e.edge_type,
                "provenance": e.provenance,
            }
            for e in resp.edges
        ]

        return json.dumps(
            {
                "repository_id": repository_id,
                "symbol_or_path": symbol_or_path,
                "graph_name": graph_name,
                "source": resp.source,
                "nodes_count": len(nodes_data),
                "edges_count": len(edges_data),
                "nodes": nodes_data,
                "relationships": edges_data,
            },
            indent=2,
        )

    @server.tool()
    def build_investigation_context(
        repository_id: str, bug_report: str, token_budget: int = 4000
    ) -> str:
        """Assemble an optimal, budget-constrained investigation context for a reported bug.

        Executes graph-guided retrieval and context packing to deliver exact grounded evidence
        without exceeding the agent's token budget.

        Args:
            repository_id: Identifier of the repository (e.g. 'requests').
            bug_report: The reproduction steps, error message, or stack trace.
            token_budget: Target token budget (e.g. 2000, 4000, 8000; default 4000).

        Returns:
            JSON string containing token budget accounting, ranked evidence snippets with
            exact line numbers, baseline lexical savings, and key graph relationships.
        """
        repo = app_service.repo_manager.get_repository(repository_id)
        if not repo:
            available = [r.repo_id for r in app_service.list_repositories()]
            return json.dumps(
                {
                    "error": f"Repository '{repository_id}' not found.",
                    "available_repositories": available,
                },
                indent=2,
            )

        req = InvestigateRequest(
            repo_id=repository_id,
            bug_report=bug_report,
            mode="trace",
            strategy="graph",
            budget=token_budget,
            compare_baseline=True,
        )
        res = app_service.investigate(req)

        # Build evidence items from retained context items
        evidence_items: list[dict[str, Any]] = []
        for c in res.context_items:
            # Try to grab file snippet preview if file exists
            preview = ""
            full_path = Path(repo.local_path) / c.file_path
            if full_path.is_file():
                try:
                    lines = full_path.read_text(encoding="utf-8", errors="replace").splitlines()
                    preview = "\n".join(lines[:40])
                except Exception:
                    preview = ""

            evidence_items.append(
                {
                    "candidate_id": c.candidate_id,
                    "file_path": c.file_path,
                    "symbol": c.symbol,
                    "token_cost": c.token_cost,
                    "score": round(c.score, 4),
                    "included": c.included,
                    "exclusion_reason": c.exclusion_reason,
                    "snippet_preview": preview[:400] if preview else "",
                }
            )

        payload = {
            "repository_id": repository_id,
            "strategy_used": res.strategy_used,
            "overall_status": res.overall_status,
            "fallback_occurred": res.fallback_occurred,
            "graph_summary": {
                "graph_name": repo.graph_name or f"{repository_id}_graph",
                "node_count": repo.node_count,
                "edge_count": repo.edge_count,
                "status": repo.status,
            },
            "token_budget": {
                "budget_limit": res.context_budget.get("budget_limit", token_budget),
                "tokens_selected": res.context_budget.get("total_tokens_selected", 0),
                "utilization_pct": res.context_budget.get("utilization_pct", 0.0),
                "retained_count": res.context_budget.get(
                    "retained_candidates_count", len(evidence_items)
                ),
                "dropped_count": res.context_budget.get("dropped_candidates_count", 0),
            },
            "evidence": evidence_items,
            "baseline_comparison": {
                "baseline_tokens": res.baseline_comparison.baseline_tokens,
                "graph_tokens": res.baseline_comparison.evaluated_tokens,
                "token_delta": res.baseline_comparison.token_delta,
                "reduction_pct": res.baseline_comparison.reduction_pct,
            }
            if res.baseline_comparison
            else None,
        }

        return json.dumps(payload, indent=2)

    return server


def main() -> None:
    """CLI entry point for running the TraceFix MCP server via STDIO."""
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    server = create_mcp_server()
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
