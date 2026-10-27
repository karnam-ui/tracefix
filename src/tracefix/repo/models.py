"""Models for connected repository lifecycle and metadata."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class RepositoryStatus(StrEnum):
    NOT_INDEXED = "not_indexed"
    INDEXING = "indexing"
    READY = "ready"
    PARTIALLY_INDEXED = "partially_indexed"
    STALE = "stale"
    FAILED = "failed"


class ConnectedRepository(BaseModel):
    repo_id: str
    name: str
    local_path: str
    default_branch: str = "main"
    working_revision: str
    indexed_revision: str | None = None
    status: RepositoryStatus = RepositoryStatus.NOT_INDEXED
    detected_languages: list[str] = Field(default_factory=lambda: ["python"])
    python_file_count: int = 0
    last_ingested_at: str | None = None
    graph_available: bool = False
    graph_name: str | None = None
    node_count: int = 0
    edge_count: int = 0
    last_error: str | None = None
    is_active: bool = False

    def is_stale(self) -> bool:
        if not self.indexed_revision:
            return False
        return self.working_revision != self.indexed_revision


class ConnectRepositoryRequest(BaseModel):
    path: str
    name: str | None = None


class RepositorySummary(BaseModel):
    repo_id: str
    name: str
    local_path: str
    default_branch: str
    working_revision: str
    short_sha: str
    indexed_revision: str | None = None
    indexed_short_sha: str | None = None
    status: str
    is_stale: bool
    graph_available: bool
    graph_name: str | None
    node_count: int
    edge_count: int
    python_file_count: int
    last_ingested_at: str | None
    last_error: str | None
    is_active: bool


class IngestProgressResponse(BaseModel):
    repo_id: str
    status: str
    node_count: int
    edge_count: int
    elapsed_seconds: float
    graph_name: str
    parse_errors: list[dict[str, Any]] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
