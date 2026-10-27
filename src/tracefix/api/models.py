"""Pydantic schemas for TraceFix API (FastAPI integration contract)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from tracefix.repo.models import (
    ConnectedRepository,
    ConnectRepositoryRequest,
    IngestProgressResponse,
    RepositoryStatus,
    RepositorySummary,
)


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str = "0.0.1"
    falkordb_connected: bool
    redis_endpoint: str
    active_cases_count: int
    persisted_graphs_count: int
    incident_memory_count: int
    connected_repos_count: int = 0
    active_repo_id: str | None = None


class CaseSummary(BaseModel):
    case_id: str
    repo: str
    revision: str
    short_sha: str
    localizable: bool
    bug_report_preview: str
    ground_truth_files: list[str] = Field(default_factory=list)
    ground_truth_functions: list[str] = Field(default_factory=list)
    created_at: str | None = None
    pre_cutoff: bool | None = None


class GraphSummary(BaseModel):
    case_id: str | None = None
    revision: str
    short_sha: str
    graph_name: str
    node_count: int
    edge_count: int
    sha256: str
    is_live: bool = True
    storage_type: str = "falkordb"  # "falkordb" or "disk_snapshot"


class NodeDetail(BaseModel):
    entity_id: str
    kind: str
    repo: str
    revision: str
    path: str = ""
    qualified_name: str = ""
    start_line: int = 0
    end_line: int = 0


class EdgeDetail(BaseModel):
    source_id: str
    target_id: str
    edge_type: str
    provenance: str = "observed"
    source: str = ""
    confidence: str | None = None


class NeighborhoodResponse(BaseModel):
    graph_name: str
    revision: str
    center_id: str | None = None
    nodes: list[NodeDetail]
    edges: list[EdgeDetail]
    source: str = "live_falkordb"  # "live_falkordb" or "snapshot_artifact"


class InvestigateRequest(BaseModel):
    case_id: str | None = None
    repo_id: str | None = Field(
        default=None, description="Registered repo_id, defaults to active repo"
    )
    repo: str = "requests"
    revision: str | None = Field(
        default=None, description="Target revision SHA, defaults to repo active SHA"
    )
    bug_report: str = ""
    mode: str = Field(default="trace", description="trace, find, snippets, or repair")
    strategy: str = Field(default="graph", description="lexical, graph, fused, or memory")
    budget: int = Field(default=4000, description="Token budget limit")
    mock: bool = Field(default=False, description="True for deterministic offline mock/test")
    execute_repair: bool = Field(
        default=False, description="Run repair generation & sandbox verification"
    )
    compare_baseline: bool = Field(
        default=False, description="Run simultaneous lexical baseline comparison"
    )


class RetrievalItemResponse(BaseModel):
    evidence_id: str
    strategy: str
    rank: int
    score: float
    file: str
    symbol: str
    lines: tuple[int, int] | None = None
    provenance: str
    source_revision: str
    is_ground_truth_function: bool = False
    is_ground_truth_file: bool = False


class ContextItemResponse(BaseModel):
    candidate_id: str
    file_path: str
    symbol: str
    token_cost: int
    strategy: str
    rank: int
    score: float
    included: bool
    exclusion_reason: str | None = None


class VerificationSummaryResponse(BaseModel):
    status: str
    exit_code: int
    passed_tests: list[str] = Field(default_factory=list)
    failed_tests: list[str] = Field(default_factory=list)
    duration_seconds: float = 0.0
    command: str | None = None
    details: str | None = None


class MemoryMatchResponse(BaseModel):
    incident_id: str
    case_id: str
    revision: str
    similarity_score: float = 1.0
    patch_preview: str
    status: str
    executed_at: str


class LifecycleStage(BaseModel):
    stage_id: str
    name: str
    status: str = Field(description="pending, running, completed, failed, skipped")
    detail: str = ""
    elapsed_ms: float = 0.0


class BaselineComparisonResponse(BaseModel):
    baseline_strategy: str = "lexical"
    evaluated_strategy: str = "graph"
    baseline_tokens: int
    evaluated_tokens: int
    token_delta: int  # baseline_tokens - evaluated_tokens (positive = reduction)
    reduction_pct: float | None = None  # None if baseline_tokens <= 0
    baseline_items_count: int
    evaluated_items_count: int
    common_symbols: list[str] = Field(default_factory=list)
    common_files: list[str] = Field(default_factory=list)


class InvestigateResponse(BaseModel):
    case_id: str
    repo: str
    repo_id: str | None = None
    revision: str
    strategy_used: str
    mode: str = "trace"
    stages: list[LifecycleStage]
    retrieval: list[RetrievalItemResponse] = Field(default_factory=list)
    context_budget: dict[str, Any] = Field(default_factory=dict)
    context_items: list[ContextItemResponse] = Field(default_factory=list)
    proposed_patch: str | None = None
    patch_safety: dict[str, Any] = Field(default_factory=dict)
    verification: VerificationSummaryResponse | None = None
    memory_matches: list[MemoryMatchResponse] = Field(default_factory=list)
    memory_stored: bool = False
    ground_truth_functions: list[str] = Field(default_factory=list)
    ground_truth_files: list[str] = Field(default_factory=list)
    overall_status: str = "completed"
    error: str | None = None
    fallback_occurred: bool = False
    fallback_reason: str | None = None
    baseline_comparison: BaselineComparisonResponse | None = None
    is_mock: bool = False


class IncidentMemoryItem(BaseModel):
    incident_id: str
    case_id: str
    revision: str
    repo: str
    bug_report_snippet: str
    patch_diff: str
    verification_status: str
    created_at: str


__all__ = [
    "BaselineComparisonResponse",
    "CaseSummary",
    "ConnectRepositoryRequest",
    "ConnectedRepository",
    "ContextItemResponse",
    "EdgeDetail",
    "GraphSummary",
    "HealthResponse",
    "IncidentMemoryItem",
    "IngestProgressResponse",
    "InvestigateRequest",
    "InvestigateResponse",
    "LifecycleStage",
    "MemoryMatchResponse",
    "NeighborhoodResponse",
    "NodeDetail",
    "RepositoryStatus",
    "RepositorySummary",
    "RetrievalItemResponse",
    "VerificationSummaryResponse",
]
