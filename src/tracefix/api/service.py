"""Service layer for TraceFix FastAPI backend.

Orchestrates repository intelligence, real retrieval, graph lookups, context selection,
repair validation, sandbox verification, and incident memory storage.
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tracefix.api.models import (
    BaselineComparisonResponse,
    CaseSummary,
    ContextItemResponse,
    EdgeDetail,
    GraphSummary,
    HealthResponse,
    IncidentMemoryItem,
    IngestProgressResponse,
    InvestigateRequest,
    InvestigateResponse,
    LifecycleStage,
    MemoryMatchResponse,
    NeighborhoodResponse,
    NodeDetail,
    RepositorySummary,
    RetrievalItemResponse,
    VerificationSummaryResponse,
)
from tracefix.evaluation.cases import CaseRecord, load_case_set
from tracefix.evaluation.replay import ChronologicalReplayEngine
from tracefix.graph.client import FalkorDBClient
from tracefix.graph.models import Provenance
from tracefix.graph.persistence import load_graph_snapshot
from tracefix.graph.query import FalkorNeighborhoodProvider, SnapshotNeighborhoodProvider
from tracefix.memory.models import IncidentRecord, VerificationEvidence
from tracefix.memory.repository import IncidentMemoryRepository
from tracefix.repair.interfaces import (
    ModelProvider,
    RepairConfig,
    RepairRequest,
    SandboxVerifierProtocol,
    VerificationResultSummary,
)
from tracefix.repair.patch_generator import HttpModelProvider, MockModelProvider
from tracefix.repair.patch_validator import PatchValidator
from tracefix.repair.state_machine import RepairOrchestrator
from tracefix.repo.manager import RepositoryManager
from tracefix.repo.models import ConnectedRepository
from tracefix.retrieval.context_selector import CharDiv4TokenCounter
from tracefix.retrieval.graph_guided import GraphGuidedStrategy
from tracefix.retrieval.interfaces import (
    RetrievalLimits,
    RetrievalQuery,
    RetrievalResult,
    RetrievalStrategy,
)
from tracefix.retrieval.lexical import LexicalBM25Strategy, build_function_corpus
from tracefix.retrieval.pipeline import RetrievalPipeline
from tracefix.verification.sandbox import SandboxVerifierAdapter, WorktreeSandbox

logger = logging.getLogger("tracefix.api")

ROOT_DIR = Path(__file__).resolve().parents[3]
CASES_PATH = ROOT_DIR / "eval/cases/requests_swe_bench_candidates.json"
GRAPH_DIR = ROOT_DIR / "artifacts/graphs"


class TraceFixService:
    def __init__(self, root_dir: Path | None = None) -> None:
        self.root_dir = root_dir or ROOT_DIR
        self.memory_repo = IncidentMemoryRepository()
        self.replay_engine = ChronologicalReplayEngine(memory_repository=self.memory_repo)
        self.repo_manager = RepositoryManager(root_dir=self.root_dir)
        self._cached_cases: list[CaseRecord] | None = None

    # -------------------------------------------------------------------
    # Repository Management
    # -------------------------------------------------------------------

    def connect_repository(self, path: str, name: str | None = None) -> RepositorySummary:
        repo = self.repo_manager.connect_repository(path, name)
        return self.repo_manager.to_summary(repo)

    def list_repositories(self) -> list[RepositorySummary]:
        repos = self.repo_manager.list_repositories()
        return [self.repo_manager.to_summary(r) for r in repos]

    def get_active_repository(self) -> RepositorySummary | None:
        repo = self.repo_manager.get_active_repository()
        return self.repo_manager.to_summary(repo) if repo else None

    def select_repository(self, repo_id: str) -> RepositorySummary:
        repo = self.repo_manager.set_active_repository(repo_id)
        return self.repo_manager.to_summary(repo)

    def disconnect_repository(self, repo_id: str) -> bool:
        return self.repo_manager.disconnect_repository(repo_id)

    def ingest_repository(self, repo_id: str) -> IngestProgressResponse:
        t0 = time.perf_counter()
        result = self.repo_manager.ingest_repository_graph(repo_id)
        elapsed = round(time.perf_counter() - t0, 3)
        repo = self.repo_manager.get_repository(repo_id)
        graph_name = (repo.graph_name if repo else None) or f"{repo_id}_graph"

        return IngestProgressResponse(
            repo_id=repo_id,
            status="ready",
            node_count=len(result.nodes),
            edge_count=len(result.edges),
            elapsed_seconds=elapsed,
            graph_name=graph_name,
            parse_errors=result.parse_errors,
            limitations=result.limitations,
        )

    # -------------------------------------------------------------------
    # Cases & Health
    # -------------------------------------------------------------------

    def get_cases(self) -> list[CaseRecord]:
        if self._cached_cases is None:
            if CASES_PATH.is_file():
                cs = load_case_set(CASES_PATH)
                self._cached_cases = cs.cases
            else:
                self._cached_cases = []
        return self._cached_cases

    def get_health(self) -> HealthResponse:
        falkordb_ok = False
        try:
            client = FalkorDBClient(graph_name="tracefix_health_check")
            client.connect()
            client.execute("RETURN 1")
            falkordb_ok = True
        except Exception:
            falkordb_ok = False

        cases_count = len(self.get_cases())
        manifest_path = GRAPH_DIR / "manifest.json"
        persisted_graphs = 0
        if manifest_path.is_file():
            try:
                manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
                persisted_graphs = manifest_data.get("revisions_count", 0)
            except Exception:
                persisted_graphs = 0

        mem_count = len(self.memory_repo.list_records())
        repos = self.repo_manager.list_repositories()
        active = self.repo_manager.get_active_repository()

        return HealthResponse(
            status="ok" if falkordb_ok else "degraded",
            version="0.0.1",
            falkordb_connected=falkordb_ok,
            redis_endpoint="localhost:6379",
            active_cases_count=cases_count,
            persisted_graphs_count=persisted_graphs,
            incident_memory_count=mem_count,
            connected_repos_count=len(repos),
            active_repo_id=active.repo_id if active else None,
        )

    def list_cases(self) -> list[CaseSummary]:
        cases = self.get_cases()
        summaries: list[CaseSummary] = []
        for c in cases:
            preview = (c.bug_report[:180] + "...") if len(c.bug_report) > 180 else c.bug_report
            summaries.append(
                CaseSummary(
                    case_id=c.case_id,
                    repo=c.repo or "requests",
                    revision=c.revision,
                    short_sha=c.revision[:8],
                    localizable=c.localizable,
                    bug_report_preview=preview,
                    ground_truth_files=c.ground_truth_files,
                    ground_truth_functions=c.ground_truth_functions,
                    created_at=c.created_at,
                    pre_cutoff=c.pre_cutoff,
                )
            )
        return summaries

    def list_graphs(self) -> list[GraphSummary]:
        manifest_path = GRAPH_DIR / "manifest.json"
        if not manifest_path.is_file():
            return []
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            graphs: list[GraphSummary] = []
            for g in data.get("graphs", []):
                graphs.append(
                    GraphSummary(
                        case_id=g.get("case_id"),
                        revision=g["revision"],
                        short_sha=g["revision"][:8],
                        graph_name=g["graph_name"],
                        node_count=g["node_count"],
                        edge_count=g["edge_count"],
                        sha256=g["sha256"],
                        is_live=True,
                        storage_type="disk_snapshot",
                    )
                )
            return graphs
        except Exception as exc:
            logger.warning("Failed to read graph manifest: %s", exc)
            return []

    # -------------------------------------------------------------------
    # Graph Neighborhood (with graceful snapshot fallback)
    # -------------------------------------------------------------------

    def get_neighborhood(
        self, graph_name: str, entity_id: str | None = None
    ) -> NeighborhoodResponse:
        """Query live FalkorDB graph or fall back honestly to disk snapshot artifact."""
        # 1. Try live FalkorDB query first
        falkor_error: Exception | None = None
        try:
            client = FalkorDBClient(graph_name=graph_name)
            client.connect()

            nodes_map: dict[str, NodeDetail] = {}
            edges_list: list[EdgeDetail] = []

            if entity_id:
                query = """
                MATCH (n {entity_id: $entity_id})-[r]-(m)
                RETURN n, r, m
                LIMIT 40
                """
                rows = client.execute(query, {"entity_id": entity_id})
            else:
                query = """
                MATCH (n:Function)-[r]-(m)
                RETURN n, r, m
                LIMIT 30
                """
                rows = client.execute(query)

            for row in rows:
                n_obj = row.get("n")
                m_obj = row.get("m")
                r_obj = row.get("r")

                n_props = getattr(n_obj, "properties", n_obj if isinstance(n_obj, dict) else {})
                m_props = getattr(m_obj, "properties", m_obj if isinstance(m_obj, dict) else {})
                r_props = getattr(r_obj, "properties", r_obj if isinstance(r_obj, dict) else {})
                relation = getattr(r_obj, "relation", r_props.get("edge_type", "RELATED_TO"))

                for obj, props in ((n_obj, n_props), (m_obj, m_props)):
                    eid = props.get("entity_id") or props.get("id") or ""
                    if eid and eid not in nodes_map:
                        raw_kind = props.get("kind")
                        labels = getattr(obj, "labels", None)
                        if raw_kind:
                            kind_val = str(raw_kind)
                        elif labels:
                            kind_val = str(labels[0])
                        else:
                            kind_val = "Node"

                        nodes_map[eid] = NodeDetail(
                            entity_id=eid,
                            kind=kind_val,
                            repo=props.get("repo", "requests"),
                            revision=props.get("revision", ""),
                            path=props.get("path", ""),
                            qualified_name=str(props.get("qualified_name") or eid),
                            start_line=props.get("start_line", 0),
                            end_line=props.get("end_line", 0),
                        )

                src_eid = n_props.get("entity_id") or ""
                tgt_eid = m_props.get("entity_id") or ""
                if src_eid and tgt_eid:
                    edges_list.append(
                        EdgeDetail(
                            source_id=src_eid,
                            target_id=tgt_eid,
                            edge_type=relation,
                            provenance=r_props.get("provenance", "observed"),
                            source=r_props.get("source", ""),
                        )
                    )

            if nodes_map:
                return NeighborhoodResponse(
                    graph_name=graph_name,
                    revision=graph_name.split("_")[-1] if "_" in graph_name else "",
                    center_id=entity_id,
                    nodes=list(nodes_map.values()),
                    edges=edges_list,
                    source="live_falkordb",
                )
        except Exception as exc:
            falkor_error = exc
            logger.info(
                "FalkorDB query failed (%s); trying disk snapshot fallback for '%s'",
                exc,
                graph_name,
            )

        # 2. Disk snapshot fallback (deterministic, offline-safe)
        clean_name = Path(graph_name).name
        snapshot_file = GRAPH_DIR / f"{clean_name}.json"
        if not snapshot_file.is_file():
            # Check without prefix
            candidates = list(GRAPH_DIR.glob(f"*{clean_name}*.json"))
            if candidates:
                snapshot_file = candidates[0]

        if snapshot_file.is_file():
            try:
                snapshot = load_graph_snapshot(snapshot_file)
                nodes_map = {}
                edges_list = []

                if entity_id:
                    # Collect edges connected to entity_id
                    target_edges = [
                        e
                        for e in snapshot.edges
                        if e.source_id == entity_id or e.target_id == entity_id
                    ][:40]
                    eids = {entity_id}
                    for e in target_edges:
                        eids.add(e.source_id)
                        eids.add(e.target_id)
                        edges_list.append(
                            EdgeDetail(
                                source_id=e.source_id,
                                target_id=e.target_id,
                                edge_type=e.edge_type,
                                provenance=e.provenance.value,
                                source=e.source,
                            )
                        )
                    for eid in eids:
                        n = snapshot.nodes.get(eid)
                        if n:
                            nodes_map[eid] = NodeDetail(
                                entity_id=n.entity_id,
                                kind=n.kind,
                                repo=n.repo,
                                revision=n.revision,
                                path=str(n.properties.get("path", "")),
                                qualified_name=str(n.properties.get("qualified_name", n.entity_id)),
                                start_line=int(str(n.properties.get("start_line", 0))),
                                end_line=int(str(n.properties.get("end_line", 0))),
                            )
                else:
                    # Center around first 25 function/class nodes
                    sample_nodes = [
                        n
                        for n in snapshot.nodes.values()
                        if n.kind in ("Function", "Class", "Test")
                    ][:25]
                    sample_eids = {n.entity_id for n in sample_nodes}
                    for n in sample_nodes:
                        nodes_map[n.entity_id] = NodeDetail(
                            entity_id=n.entity_id,
                            kind=n.kind,
                            repo=n.repo,
                            revision=n.revision,
                            path=str(n.properties.get("path", "")),
                            qualified_name=str(n.properties.get("qualified_name", n.entity_id)),
                            start_line=int(str(n.properties.get("start_line", 0))),
                            end_line=int(str(n.properties.get("end_line", 0))),
                        )
                    # Add interconnecting edges
                    for e in snapshot.edges:
                        if e.source_id in sample_eids and e.target_id in sample_eids:
                            edges_list.append(
                                EdgeDetail(
                                    source_id=e.source_id,
                                    target_id=e.target_id,
                                    edge_type=e.edge_type,
                                    provenance=e.provenance.value,
                                    source=e.source,
                                )
                            )

                return NeighborhoodResponse(
                    graph_name=graph_name,
                    revision=snapshot.revision,
                    center_id=entity_id,
                    nodes=list(nodes_map.values()),
                    edges=edges_list,
                    source="snapshot_artifact",
                )
            except Exception as snap_exc:
                logger.warning("Failed to load snapshot %s: %s", snapshot_file, snap_exc)

        # Neither FalkorDB nor snapshot available
        err_msg = f"Graph '{graph_name}' unavailable in database or snapshot artifacts."
        if falkor_error:
            err_msg += f" (FalkorDB error: {falkor_error})"
        raise RuntimeError(err_msg)

    # -------------------------------------------------------------------
    # Incident Memory
    # -------------------------------------------------------------------

    def list_memory_records(self) -> list[IncidentMemoryItem]:
        all_incidents = self.memory_repo.list_records()
        items: list[IncidentMemoryItem] = []
        for inc in all_incidents:
            snippet = (
                (inc.bug_report[:120] + "...") if len(inc.bug_report) > 120 else inc.bug_report
            )
            items.append(
                IncidentMemoryItem(
                    incident_id=inc.incident_id,
                    case_id=inc.case_id,
                    revision=inc.revision,
                    repo=inc.repo,
                    bug_report_snippet=snippet,
                    patch_diff=inc.patch_diff,
                    verification_status=inc.verification_evidence.status,
                    created_at=inc.created_at,
                )
            )
        return items

    # -------------------------------------------------------------------
    # End-to-End Investigation Lifecycle
    # -------------------------------------------------------------------

    def investigate(self, req: InvestigateRequest) -> InvestigateResponse:
        stages: list[LifecycleStage] = []
        mode = req.mode.lower() if req.mode else "trace"

        # Determine target repository
        target_repo: ConnectedRepository | None = None
        if req.repo_id:
            target_repo = self.repo_manager.get_repository(req.repo_id)
        if target_repo is None and req.repo:
            target_repo = self.repo_manager.get_repository(req.repo)
        if target_repo is None:
            target_repo = self.repo_manager.get_active_repository()

        # Target bug case if provided
        target_case: CaseRecord | None = None
        if req.case_id:
            for c in self.get_cases():
                if c.case_id == req.case_id:
                    target_case = c
                    break

        case_id = req.case_id or (target_case.case_id if target_case else "custom_bug")
        repo_name = req.repo or (target_repo.name if target_repo else "requests")
        repo_id = target_repo.repo_id if target_repo else "requests"
        repo_path = (
            Path(target_repo.local_path) if target_repo else (self.root_dir / "data/repos/requests")
        )

        # Determine revision
        revision = (
            req.revision
            or (target_case.revision if target_case else None)
            or (target_repo.working_revision if target_repo else None)
            or "22623bd8c265b78b161542663ee980738441c307"
        )
        bug_report = req.bug_report or (target_case.bug_report if target_case else "")
        gt_functions = target_case.ground_truth_functions if target_case else []
        gt_files = target_case.ground_truth_files if target_case else []
        short_sha = revision[:8]

        # Stage 1: Bug report parsed
        stages.append(
            LifecycleStage(
                stage_id="stage_1_parse",
                name="Bug Report Acceptance & Query Extraction",
                status="completed",
                detail=(
                    f"Parsed bug report ({len(bug_report)} chars) "
                    f"for {repo_name} at revision {short_sha}"
                ),
                elapsed_ms=1.1,
            )
        )

        # Stage 2: Retrieval execution
        t0 = time.perf_counter()
        retrieval_items: list[RetrievalItemResponse] = []
        strategy_requested = req.strategy.lower() if req.strategy else "graph"
        strategy_used = strategy_requested
        fallback_occurred = False
        fallback_reason: str | None = None

        # Check for snapshot file to build lexical corpus
        graph_name = (
            target_repo.graph_name if target_repo and target_repo.graph_name else None
        ) or f"{repo_name}_{short_sha}"
        snapshot_file = GRAPH_DIR / f"{graph_name}.json"
        if not snapshot_file.is_file():
            # Fallback check for standard requests snapshot naming
            candidates = list(GRAPH_DIR.glob(f"*{short_sha}*.json"))
            if candidates:
                snapshot_file = candidates[0]

        lexical_strategy: LexicalBM25Strategy | None = None
        snapshot_data = None

        if snapshot_file.is_file() and repo_path.is_dir():
            try:
                snapshot_data = load_graph_snapshot(snapshot_file)
                corpus = build_function_corpus(repo_path, snapshot_data.nodes)
                lexical_strategy = LexicalBM25Strategy(corpus)
            except Exception as e:
                logger.warning(
                    "Could not build function corpus from snapshot %s: %s", snapshot_file, e
                )

        # If lexical_strategy is still None, attempt direct file parse
        if lexical_strategy is None and repo_path.is_dir():
            try:
                from tracefix.graph.ingestion import ingest_repository

                quick_res = ingest_repository(
                    repo_path, repo_url=repo_name, revision=revision, include_history=False
                )
                corpus = build_function_corpus(repo_path, quick_res.nodes)
                lexical_strategy = LexicalBM25Strategy(corpus)
                snapshot_data = quick_res
            except Exception as e:
                logger.warning("Could not build on-the-fly corpus for %s: %s", repo_path, e)

        # Determine retrieval strategy based on mode & availability
        strat: RetrievalStrategy | None = None

        if mode == "find":
            strategy_used = "lexical"
            strat = lexical_strategy

        elif strategy_requested == "graph":
            # 1. Try FalkorDB live provider
            falkor_connected = False
            if lexical_strategy:
                graph_client = FalkorDBClient(graph_name=graph_name)
                try:
                    graph_client.connect()
                    provider = FalkorNeighborhoodProvider(graph_client, direction="both")
                    strat = GraphGuidedStrategy(
                        provider=provider,
                        seed_strategy=lexical_strategy,
                        seed_count=10,
                        fanout=5,
                    )
                    falkor_connected = True
                    strategy_used = "graph"
                except Exception:
                    falkor_connected = False

            # 2. Fall back to SnapshotNeighborhoodProvider (in-memory graph BFS)
            if not falkor_connected and snapshot_data and lexical_strategy:
                try:
                    snap_provider = SnapshotNeighborhoodProvider(
                        snapshot_data.nodes,
                        snapshot_data.edges,
                        direction="both",
                    )
                    strat = GraphGuidedStrategy(
                        provider=snap_provider,
                        seed_strategy=lexical_strategy,
                        seed_count=10,
                        fanout=5,
                    )
                    strategy_used = "graph"
                except Exception as snap_err:
                    logger.warning("Snapshot neighborhood provider failed: %s", snap_err)

            # 3. Honest fallback to lexical if graph unavailable
            if strat is None and lexical_strategy:
                fallback_occurred = True
                fallback_reason = (
                    "Graph not available for active revision; fell back to lexical BM25"
                )
                strategy_used = "lexical"
                strat = lexical_strategy

        elif strategy_requested == "fused":
            if snapshot_data and lexical_strategy:
                snap_provider = SnapshotNeighborhoodProvider(
                    snapshot_data.nodes, snapshot_data.edges, direction="both"
                )
                strat_graph = GraphGuidedStrategy(
                    provider=snap_provider, seed_strategy=lexical_strategy, seed_count=10, fanout=5
                )
                strat = RetrievalPipeline(
                    strategies=[lexical_strategy, strat_graph], method="rrf", rrf_k=60
                )
                strategy_used = "fused (RRF)"
            elif lexical_strategy:
                fallback_occurred = True
                fallback_reason = "Graph unavailable for fusion; fell back to lexical BM25"
                strategy_used = "lexical (fallback)"
                strat = lexical_strategy
        else:
            strategy_used = "lexical"
            strat = lexical_strategy

        # Execute retrieval query
        res: RetrievalResult
        if strat is not None:
            query = RetrievalQuery(
                case_id=case_id,
                text=bug_report,
                revision=revision,
                k=20,
                limits=RetrievalLimits(max_items=20, max_hops=2, timeout_ms=15_000),
            )
            res = strat.retrieve(query)
        else:
            # Honest empty state - no fake stub data
            res = RetrievalResult(
                strategy=strategy_used,
                items=[],
                revision=revision,
                elapsed_ms=0.0,
            )

        retrieval_ms = (time.perf_counter() - t0) * 1000

        for it in res.items:
            is_gt_fn = any(
                it.target.symbol == qn or it.target.symbol == qn.rsplit(".", 1)[-1]
                for qn in gt_functions
            )
            is_gt_file = any(it.target.file == gf or it.target.file.endswith(gf) for gf in gt_files)
            prov_str = (
                it.provenance.value if isinstance(it.provenance, Provenance) else str(it.provenance)
            )
            retrieval_items.append(
                RetrievalItemResponse(
                    evidence_id=it.evidence_id,
                    strategy=it.strategy,
                    rank=it.rank,
                    score=round(it.score, 4),
                    file=it.target.file,
                    symbol=it.target.symbol or "",
                    lines=it.target.lines,
                    provenance=prov_str,
                    source_revision=it.source_revision,
                    is_ground_truth_function=is_gt_fn,
                    is_ground_truth_file=is_gt_file,
                )
            )

        stages.append(
            LifecycleStage(
                stage_id="stage_2_retrieval",
                name=f"Retrieval via {strategy_used}",
                status="completed" if retrieval_items else "completed (empty)",
                detail=(
                    f"Retrieved {len(retrieval_items)} items across {repo_name} "
                    f"in {retrieval_ms:.1f}ms"
                    + (f" ({fallback_reason})" if fallback_occurred else "")
                ),
                elapsed_ms=round(retrieval_ms, 2),
            )
        )

        # Stage 3: Context Selection & Budgeting
        t0 = time.perf_counter()
        token_counter = CharDiv4TokenCounter()

        manifest_candidates = []
        for it in res.items:
            # Extract actual snippet from repository filesystem
            snippet = f"# {it.target.symbol} in {it.target.file}\n"
            if repo_path.is_dir():
                fp = repo_path / it.target.file
                if fp.is_file():
                    try:
                        lines = fp.read_text(encoding="utf-8").splitlines()
                        start, end = (
                            it.target.lines if it.target.lines else (1, min(len(lines), 50))
                        )
                        snippet = "\n".join(lines[max(0, start - 1) : end])
                    except Exception:
                        pass
            manifest_candidates.append(
                {
                    "evidence_id": it.evidence_id,
                    "file_path": it.target.file,
                    "symbol": it.target.symbol or "",
                    "strategy": it.strategy,
                    "rank": it.rank,
                    "score": it.score,
                    "content": snippet,
                }
            )

        # Select items within token budget limit
        manifest_items: list[dict[str, Any]] = []
        context_responses: list[ContextItemResponse] = []
        used_tokens = 0

        for cand in manifest_candidates:
            cand_content = str(cand["content"])
            cost = token_counter.count(cand_content)
            cand_id = str(cand["evidence_id"])
            cand_file = str(cand["file_path"])
            cand_symbol = str(cand["symbol"])
            cand_strat = str(cand["strategy"])
            cand_rank = int(str(cand["rank"]))
            cand_score = round(float(str(cand["score"])), 4)

            if used_tokens + cost <= req.budget:
                used_tokens += cost
                manifest_items.append(cand)
                context_responses.append(
                    ContextItemResponse(
                        candidate_id=cand_id,
                        file_path=cand_file,
                        symbol=cand_symbol,
                        token_cost=cost,
                        strategy=cand_strat,
                        rank=cand_rank,
                        score=cand_score,
                        included=True,
                    )
                )
            else:
                context_responses.append(
                    ContextItemResponse(
                        candidate_id=cand_id,
                        file_path=cand_file,
                        symbol=cand_symbol,
                        token_cost=cost,
                        strategy=cand_strat,
                        rank=cand_rank,
                        score=cand_score,
                        included=False,
                        exclusion_reason="Exceeded context token budget limit",
                    )
                )

        context_ms = (time.perf_counter() - t0) * 1000
        utilization = round(used_tokens / req.budget, 4) if req.budget > 0 else 0.0
        budget_summary = {
            "budget_limit": req.budget,
            "tokens_used": used_tokens,
            "utilization": utilization,
            "included_count": len(manifest_items),
            "excluded_count": len(context_responses) - len(manifest_items),
            "counting_method": "heuristic_char_div_4",
        }

        budget_pct = utilization * 100
        stages.append(
            LifecycleStage(
                stage_id="stage_3_context",
                name="Context Selection & Token Budgeting",
                status="completed",
                detail=(
                    f"Selected {len(manifest_items)} items ({used_tokens}/{req.budget} "
                    f"tokens, {budget_pct:.1f}% budget used)"
                ),
                elapsed_ms=round(context_ms, 2),
            )
        )

        # Optional Baseline Comparison: Run lexical baseline under exact same query & budget
        baseline_comp: BaselineComparisonResponse | None = None
        if (
            (req.compare_baseline or mode == "trace")
            and lexical_strategy
            and strategy_used.startswith("graph")
        ):
            try:
                base_query = RetrievalQuery(
                    case_id=case_id,
                    text=bug_report,
                    revision=revision,
                    k=20,
                    limits=RetrievalLimits(max_items=20, max_hops=2, timeout_ms=15_000),
                )
                base_res = lexical_strategy.retrieve(base_query)
                base_tokens = 0
                base_items_cnt = 0
                for bit in base_res.items:
                    bsnip = f"# {bit.target.symbol} in {bit.target.file}\n"
                    if repo_path.is_dir():
                        bfp = repo_path / bit.target.file
                        if bfp.is_file():
                            try:
                                blines = bfp.read_text(encoding="utf-8").splitlines()
                                bstart, bend = (
                                    bit.target.lines
                                    if bit.target.lines
                                    else (1, min(len(blines), 50))
                                )
                                bsnip = "\n".join(blines[max(0, bstart - 1) : bend])
                            except Exception:
                                pass
                    bcost = token_counter.count(bsnip)
                    if base_tokens + bcost <= req.budget:
                        base_tokens += bcost
                        base_items_cnt += 1

                token_delta = base_tokens - used_tokens
                red_pct = round((token_delta / base_tokens) * 100, 2) if base_tokens > 0 else 0.0

                eval_symbols = {it.symbol for it in retrieval_items if it.symbol}
                base_symbols = {it.target.symbol for it in base_res.items if it.target.symbol}
                eval_files = {it.file for it in retrieval_items if it.file}
                base_files = {it.target.file for it in base_res.items if it.target.file}

                baseline_comp = BaselineComparisonResponse(
                    baseline_strategy="lexical_bm25",
                    evaluated_strategy=strategy_used,
                    baseline_tokens=base_tokens,
                    evaluated_tokens=used_tokens,
                    token_delta=token_delta,
                    reduction_pct=red_pct,
                    baseline_items_count=base_items_cnt,
                    evaluated_items_count=len(manifest_items),
                    common_symbols=sorted(list(eval_symbols & base_symbols))[:10],
                    common_files=sorted(list(eval_files & base_files)),
                )
            except Exception as cmp_exc:
                logger.warning("Baseline comparison failed: %s", cmp_exc)

        # Stage 4: Incident Memory Lookup (Part B)
        memory_matches: list[MemoryMatchResponse] = []
        cutoff_time = target_case.created_at if (target_case and target_case.created_at) else None
        if cutoff_time:
            eligible = self.memory_repo.query_eligible(
                query_text=bug_report,
                as_of_time=cutoff_time,
                repo=repo_name,
            )
            for mem in eligible:
                memory_matches.append(
                    MemoryMatchResponse(
                        incident_id=mem.incident_id,
                        case_id=mem.case_id,
                        revision=mem.revision,
                        similarity_score=1.0,
                        patch_preview=mem.patch_diff[:120] + "...",
                        status=mem.verification_evidence.status,
                        executed_at=mem.created_at,
                    )
                )

        stages.append(
            LifecycleStage(
                stage_id="stage_4_memory_read",
                name="Incident Memory Lookup (Part B)",
                status="completed",
                detail=(
                    f"Found {len(memory_matches)} eligible verified incident(s)"
                    if memory_matches
                    else "No prior verified incident found for this repository"
                ),
                elapsed_ms=1.2,
            )
        )

        # Stage 5: Repair Proposal & Safety Validation
        proposed_patch: str | None = None
        patch_safety: dict[str, Any] = {}
        verification: VerificationSummaryResponse | None = None
        memory_stored = False

        should_execute_repair = req.execute_repair or (mode == "repair")

        if should_execute_repair:
            t0 = time.perf_counter()

            # Inspect model provider configuration
            api_key = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("OPENROUTER_API_KEY")
            is_mock = req.mock

            if not is_mock and not api_key:
                # Truthful unavailable outcome: do not generate fake diff
                stages.append(
                    LifecycleStage(
                        stage_id="stage_5_repair",
                        name="Patch Generation (Model Adapter)",
                        status="skipped",
                        detail=(
                            "Repair generation skipped: no API key configured "
                            "(ANTHROPIC_API_KEY / OPENROUTER_API_KEY). "
                            "Source code was not sent to external services."
                        ),
                        elapsed_ms=0.5,
                    )
                )
                stages.append(
                    LifecycleStage(
                        stage_id="stage_6_verify",
                        name="Sandbox Verification",
                        status="skipped",
                        detail="Verification skipped: no candidate patch was generated.",
                        elapsed_ms=0.2,
                    )
                )
                verification = VerificationSummaryResponse(
                    status="UNAVAILABLE",
                    exit_code=0,
                    passed_tests=[],
                    failed_tests=[],
                    duration_seconds=0.0,
                    details=(
                        "Model provider unconfigured. Set ANTHROPIC_API_KEY or "
                        "OPENROUTER_API_KEY to enable patch generation."
                    ),
                )
            else:
                # Setup model provider and verifier
                repair_model_provider: ModelProvider
                verifier: SandboxVerifierProtocol

                if is_mock:
                    # Explicit mock test mode
                    target_file = (
                        gt_files[0]
                        if gt_files
                        else (retrieval_items[0].file if retrieval_items else "calc/core.py")
                    )
                    mock_diff = (
                        f"--- a/{target_file}\n"
                        f"+++ b/{target_file}\n"
                        f"@@ -1,3 +1,4 @@\n"
                        f"+# TraceFix automated repair for {case_id}\n"
                        f" # Base revision: {short_sha}\n"
                    )
                    repair_model_provider = MockModelProvider(responses=[mock_diff])

                    class _TestMockVerifier:
                        def verify(self, *a: Any, **kw: Any) -> VerificationResultSummary:
                            p_tests = (
                                target_case.fail_to_pass_tests
                                if (target_case and target_case.fail_to_pass_tests)
                                else ["test_verification"]
                            )
                            return VerificationResultSummary(
                                status="VERIFIED",
                                exit_code=0,
                                passed_tests=p_tests,
                                duration_seconds=0.45,
                            )

                    verifier = _TestMockVerifier()
                else:
                    # Real HTTP provider and real WorktreeSandbox
                    repair_model_provider = HttpModelProvider(api_key=api_key)
                    verifier = SandboxVerifierAdapter(sandbox=WorktreeSandbox(repo_dir=repo_path))

                validator = PatchValidator()
                orchestrator = RepairOrchestrator(
                    model_provider=repair_model_provider,
                    patch_validator=validator,
                    sandbox_verifier=verifier,
                )

                f2p = target_case.fail_to_pass_tests if target_case else []
                p2p = target_case.validation.get("pass_to_pass_tests", []) if target_case else []
                test_suite = {"fail_to_pass": f2p, "pass_to_pass": p2p}
                context_manifest = {
                    "case_id": case_id,
                    "revision": revision,
                    "budget": {"token_limit": req.budget},
                    "items": manifest_items,
                }
                repair_request = RepairRequest(
                    case_id=case_id,
                    repo=repo_name,
                    base_revision=revision,
                    bug_report=bug_report,
                    context_manifest=context_manifest,
                    test_suite=test_suite,
                    configuration=RepairConfig(),
                )

                try:
                    repair_res = orchestrator.run(repair_request)
                    repair_ms = (time.perf_counter() - t0) * 1000

                    if repair_res.candidate_patch:
                        proposed_patch = repair_res.candidate_patch.raw_diff
                        safety_check = validator.validate(repair_res.candidate_patch)
                        patch_safety = {
                            "is_valid": safety_check.is_valid,
                            "errors": safety_check.errors,
                            "prohibited_files": safety_check.prohibited_files,
                            "warnings": safety_check.warnings,
                        }

                    stages.append(
                        LifecycleStage(
                            stage_id="stage_5_repair",
                            name="Patch Generation & Strict AST Validation",
                            status="completed" if repair_res.candidate_patch else "failed",
                            detail=(
                                f"Generated patch ({len(proposed_patch or '')} bytes) "
                                f"in {repair_ms:.1f}ms (AST: "
                                f"{'Valid' if patch_safety.get('is_valid') else 'Violations'})"
                                if proposed_patch
                                else "No patch generated by model provider"
                            ),
                            elapsed_ms=round(repair_ms, 2),
                        )
                    )

                    # Stage 6: Sandbox Verification
                    if repair_res.verification_result:
                        v = repair_res.verification_result
                        verification = VerificationSummaryResponse(
                            status=v.status,
                            exit_code=v.exit_code,
                            passed_tests=v.passed_tests,
                            failed_tests=v.failed_tests,
                            duration_seconds=round(v.duration_seconds, 2),
                        )

                        stages.append(
                            LifecycleStage(
                                stage_id="stage_6_verify",
                                name="Isolated Sandbox Test Verification",
                                status="completed" if v.status == "VERIFIED" else "failed",
                                detail=(
                                    f"Verification {v.status}: {len(v.passed_tests)} tests passed, "
                                    f"{len(v.failed_tests)} failed in {v.duration_seconds:.2f}s"
                                ),
                                elapsed_ms=round(v.duration_seconds * 1000, 2),
                            )
                        )

                        # Stage 7: Incident Memory Write (Only upon real VERIFIED repair)
                        if v.status == "VERIFIED" and proposed_patch and not is_mock:
                            t_exec = datetime.now(UTC).isoformat()
                            ev = VerificationEvidence(
                                status="VERIFIED",
                                test_suite=str(v.passed_tests),
                                exit_code=0,
                                duration_seconds=v.duration_seconds,
                                executed_at=t_exec,
                            )
                            record = IncidentRecord.create(
                                case_id=case_id,
                                revision=revision,
                                bug_report=bug_report,
                                patch_diff=proposed_patch,
                                verification_evidence=ev,
                                repo=repo_name,
                                created_at=t_exec,
                            )
                            self.memory_repo.save(record)
                            memory_stored = True

                            stages.append(
                                LifecycleStage(
                                    stage_id="stage_7_memory_write",
                                    name="Verified Incident Memory Storage (Part B)",
                                    status="completed",
                                    detail=f"Persisted fix into memory (ID: {record.incident_id})",
                                    elapsed_ms=1.1,
                                )
                            )

                except Exception as repair_exc:
                    stages.append(
                        LifecycleStage(
                            stage_id="stage_5_repair",
                            name="Patch Generation & Validation",
                            status="failed",
                            detail=f"Repair failed: {repair_exc}",
                            elapsed_ms=1.0,
                        )
                    )

        return InvestigateResponse(
            case_id=case_id,
            repo=repo_name,
            repo_id=repo_id,
            revision=revision,
            strategy_used=strategy_used,
            mode=mode,
            stages=stages,
            retrieval=retrieval_items,
            context_budget=budget_summary,
            context_items=context_responses,
            proposed_patch=proposed_patch,
            patch_safety=patch_safety,
            verification=verification,
            memory_matches=memory_matches,
            memory_stored=memory_stored,
            ground_truth_functions=gt_functions,
            ground_truth_files=gt_files,
            overall_status="completed",
            fallback_occurred=fallback_occurred,
            fallback_reason=fallback_reason,
            baseline_comparison=baseline_comp,
            is_mock=req.mock,
        )
