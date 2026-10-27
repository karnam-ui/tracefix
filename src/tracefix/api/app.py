"""FastAPI application for TraceFix."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from tracefix.api.models import (
    CaseSummary,
    ConnectRepositoryRequest,
    GraphSummary,
    HealthResponse,
    IncidentMemoryItem,
    IngestProgressResponse,
    InvestigateRequest,
    InvestigateResponse,
    NeighborhoodResponse,
    RepositorySummary,
)
from tracefix.api.service import TraceFixService
from tracefix.repo.manager import RepositoryValidationError

app = FastAPI(
    title="TraceFix API",
    description="Graph-Native Bug Resolution and Verified Repair System API",
    version="0.0.1",
)

# CORS configuration for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

service = TraceFixService()
DOCS_DIR = Path(__file__).resolve().parents[3] / "docs/experiments"


# -------------------------------------------------------------------------
# Health & Status
# -------------------------------------------------------------------------


@app.get("/api/health", response_model=HealthResponse)
def get_health() -> HealthResponse:
    """Return system connection and environment health status."""
    return service.get_health()


# -------------------------------------------------------------------------
# Repository Connection & Lifecycle Management
# -------------------------------------------------------------------------


@app.get("/api/repos", response_model=list[RepositorySummary])
def list_repositories() -> list[RepositorySummary]:
    """List all connected local repositories."""
    return service.list_repositories()


@app.get("/api/repos/active", response_model=RepositorySummary | None)
def get_active_repository() -> RepositorySummary | None:
    """Return currently active repository."""
    return service.get_active_repository()


@app.post("/api/repos/connect", response_model=RepositorySummary)
def connect_repository(req: ConnectRepositoryRequest) -> RepositorySummary:
    """Connect, validate, and register a local Git repository."""
    try:
        return service.connect_repository(path=req.path, name=req.name)
    except RepositoryValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to connect repository: {exc}") from exc


@app.post("/api/repos/select", response_model=RepositorySummary)
def select_repository(
    repo_id: str = Query(..., description="ID of repository to activate"),
) -> RepositorySummary:
    """Switch the active repository."""
    try:
        return service.select_repository(repo_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.delete("/api/repos/{repo_id}")
def disconnect_repository(repo_id: str) -> dict[str, Any]:
    """Remove a connected repository."""
    removed = service.disconnect_repository(repo_id)
    if not removed:
        raise HTTPException(status_code=404, detail=f"Repository {repo_id} not found")
    return {"status": "ok", "disconnected_repo_id": repo_id}


@app.post("/api/repos/{repo_id}/ingest", response_model=IngestProgressResponse)
def ingest_repository(repo_id: str) -> IngestProgressResponse:
    """Ingest repository AST and build or refresh its revision property graph."""
    try:
        return service.ingest_repository(repo_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Ingestion failed: {exc}") from exc


# -------------------------------------------------------------------------
# Frozen Cases & Graphs
# -------------------------------------------------------------------------


@app.get("/api/cases", response_model=list[CaseSummary])
def list_cases() -> list[CaseSummary]:
    """Return available frozen evaluation bug cases."""
    return service.list_cases()


@app.get("/api/graphs", response_model=list[GraphSummary])
def list_graphs() -> list[GraphSummary]:
    """Return persisted historical base-revision graphs."""
    return service.list_graphs()


@app.get("/api/graphs/{graph_name}/neighborhood", response_model=NeighborhoodResponse)
def get_neighborhood(
    graph_name: str,
    entity_id: str | None = Query(default=None, description="Center node entity ID"),
) -> NeighborhoodResponse:
    """Query live FalkorDB graph or snapshot artifact for neighborhood of a symbol/entity."""
    try:
        return service.get_neighborhood(graph_name, entity_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Neighborhood query failed: {exc}") from exc


# -------------------------------------------------------------------------
# Incident Memory
# -------------------------------------------------------------------------


@app.get("/api/memory", response_model=list[IncidentMemoryItem])
def list_memory() -> list[IncidentMemoryItem]:
    """Return verified historical incidents in incident memory (Part B)."""
    return service.list_memory_records()


# -------------------------------------------------------------------------
# Investigation
# -------------------------------------------------------------------------


@app.post("/api/investigate", response_model=InvestigateResponse)
def investigate(req: InvestigateRequest) -> InvestigateResponse:
    """Run real end-to-end bug investigation lifecycle across retrieval, context, and repair."""
    try:
        return service.investigate(req)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Investigation failed: {exc}") from exc


# -------------------------------------------------------------------------
# Evaluation Reports
# -------------------------------------------------------------------------


@app.get("/api/evaluations")
def list_evaluations() -> list[dict[str, Any]]:
    """List stored research evaluation reports."""
    reports = []
    if DOCS_DIR.exists():
        for json_file in sorted(DOCS_DIR.glob("*.json")):
            try:
                data = json.loads(json_file.read_text(encoding="utf-8"))
                cnt = len(data.get("selected_case_ids", [])) or len(data.get("selected", []))
                reports.append(
                    {
                        "file_name": json_file.name,
                        "title": data.get("title") or json_file.stem.replace("_", " ").title(),
                        "dataset_fingerprint": data.get("dataset_fingerprint"),
                        "cases_count": cnt,
                    }
                )
            except Exception:
                pass
    return reports


@app.get("/api/evaluations/{report_name}")
def get_evaluation_report(report_name: str) -> dict[str, Any]:
    """Retrieve full stored evaluation report JSON."""
    safe_name = Path(report_name).name
    report_file = DOCS_DIR / safe_name
    if not report_file.is_file():
        raise HTTPException(status_code=404, detail="Evaluation report not found")
    try:
        return json.loads(report_file.read_text(encoding="utf-8"))  # type: ignore[no-any-return]
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Could not read report: {exc}") from exc


# -------------------------------------------------------------------------
# Static Frontend Mount
# -------------------------------------------------------------------------

DIST_DIR = Path(__file__).resolve().parents[3] / "frontend/dist"
if DIST_DIR.is_dir():
    from fastapi.responses import FileResponse
    from fastapi.staticfiles import StaticFiles

    assets_dir = DIST_DIR / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/{full_path:path}")
    def serve_spa(full_path: str) -> FileResponse:
        file_path = DIST_DIR / full_path
        if file_path.is_file():
            return FileResponse(file_path)
        return FileResponse(DIST_DIR / "index.html")
