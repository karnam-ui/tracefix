"""Unit tests for the TraceFix Model Context Protocol (MCP) server."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from tracefix.api.service import TraceFixService
from tracefix.mcp.server import create_mcp_server


@pytest.fixture
def mcp_server() -> tuple[Any, TraceFixService]:
    service = TraceFixService(root_dir=Path(__file__).resolve().parents[3])
    server = create_mcp_server(service=service)
    return server, service


def test_mcp_list_tools(mcp_server: tuple[Any, TraceFixService]) -> None:
    async def _test() -> None:
        server, _ = mcp_server
        tools = await server.list_tools()
        tool_names = {t.name for t in tools}
        expected = {
            "list_repositories",
            "find_relevant_code",
            "trace_dependencies",
            "build_investigation_context",
        }
        assert expected.issubset(tool_names)

    asyncio.run(_test())


def test_mcp_list_repositories(mcp_server: tuple[Any, TraceFixService]) -> None:
    async def _test() -> None:
        server, _ = mcp_server
        result = await server.call_tool("list_repositories", {})
        assert not result.is_error
        assert len(result.content) > 0
        raw_json = result.content[0].text
        data = json.loads(raw_json)
        assert "repositories" in data
        assert data["count"] >= 1
        # Requests demo repo should be present
        req_repo = next((r for r in data["repositories"] if r["repo_id"] == "requests"), None)
        assert req_repo is not None
        assert req_repo["is_demo"] is True

    asyncio.run(_test())


def test_mcp_find_relevant_code(mcp_server: tuple[Any, TraceFixService]) -> None:
    async def _test() -> None:
        server, _ = mcp_server
        result = await server.call_tool(
            "find_relevant_code",
            {"repository_id": "requests", "query": "session redirect history", "limit": 5},
        )
        assert not result.is_error
        data = json.loads(result.content[0].text)
        assert data["repository_id"] == "requests"
        assert "items" in data
        assert len(data["items"]) <= 5
        if data["items"]:
            first = data["items"][0]
            assert "file_path" in first
            assert "symbol" in first
            assert "score" in first

    asyncio.run(_test())


def test_mcp_trace_dependencies(mcp_server: tuple[Any, TraceFixService]) -> None:
    async def _test() -> None:
        server, _ = mcp_server
        result = await server.call_tool(
            "trace_dependencies",
            {"repository_id": "requests", "symbol_or_path": "Session.send", "max_hops": 2},
        )
        assert not result.is_error
        data = json.loads(result.content[0].text)
        assert data["repository_id"] == "requests"
        assert "nodes" in data
        assert "relationships" in data

    asyncio.run(_test())


def test_mcp_build_investigation_context(mcp_server: tuple[Any, TraceFixService]) -> None:
    async def _test() -> None:
        server, _ = mcp_server
        result = await server.call_tool(
            "build_investigation_context",
            {
                "repository_id": "requests",
                "bug_report": (
                    "Infinite redirect loop occurs when Location header contains relative path."
                ),
                "token_budget": 3000,
            },
        )
        assert not result.is_error
        data = json.loads(result.content[0].text)
        assert data["repository_id"] == "requests"
        assert "token_budget" in data
        assert data["token_budget"]["budget_limit"] == 3000
        assert "evidence" in data
        assert "graph_summary" in data

    asyncio.run(_test())


def test_mcp_invalid_repo(mcp_server: tuple[Any, TraceFixService]) -> None:
    async def _test() -> None:
        server, _ = mcp_server
        result = await server.call_tool(
            "find_relevant_code",
            {"repository_id": "nonexistent_repo_xyz", "query": "test"},
        )
        assert not result.is_error
        data = json.loads(result.content[0].text)
        assert "error" in data
        assert "available_repositories" in data

    asyncio.run(_test())

