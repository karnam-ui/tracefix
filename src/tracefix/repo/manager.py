"""Repository Manager for discovering, connecting, validating, and ingesting local Git repos."""

from __future__ import annotations

import json
import logging
import re
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tracefix.graph.client import FalkorDBClient
from tracefix.graph.ingestion import (
    IngestionError,
    IngestionResult,
    git_head,
    ingest_repository,
)
from tracefix.graph.persistence import (
    get_revision_graph_name,
    persist_snapshot_to_falkordb,
    save_graph_snapshot,
)
from tracefix.repo.models import (
    ConnectedRepository,
    RepositoryStatus,
    RepositorySummary,
)

logger = logging.getLogger("tracefix.repo")


class RepositoryValidationError(Exception):
    """Raised when repository path or git state is invalid."""


class RepositoryManager:
    """Manages connected local Git repositories and their ingestion lifecycle."""

    def __init__(self, persistence_file: Path | None = None, root_dir: Path | None = None) -> None:
        self.root_dir = root_dir or Path(__file__).resolve().parents[3]
        self.artifacts_dir = self.root_dir / "artifacts"
        self.graphs_dir = self.artifacts_dir / "graphs"
        self.persistence_file = persistence_file or (self.artifacts_dir / "repositories.json")

        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        self.graphs_dir.mkdir(parents=True, exist_ok=True)

        self._repositories: dict[str, ConnectedRepository] = {}
        self._active_repo_id: str | None = None
        self._load_state()

    def _load_state(self) -> None:
        if self.persistence_file.is_file():
            try:
                data = json.loads(self.persistence_file.read_text(encoding="utf-8"))
                for r_data in data.get("repositories", []):
                    repo = ConnectedRepository.model_validate(r_data)
                    self._repositories[repo.repo_id] = repo
                self._active_repo_id = data.get("active_repo_id")
            except Exception as exc:
                logger.warning(
                    "Failed to load repositories state from %s: %s", self.persistence_file, exc
                )

        # Seed pre-existing bundled repository if none registered
        if not self._repositories:
            bundled_requests = self.root_dir / "data/repos/requests"
            if bundled_requests.is_dir() and (bundled_requests / ".git").exists():
                head_sha = git_head(bundled_requests)
                if head_sha:
                    short_sha = head_sha[:8]
                    snapshot_file = self.graphs_dir / f"requests_{short_sha}.json"
                    has_snapshot = snapshot_file.is_file()
                    node_cnt = 0
                    edge_cnt = 0
                    if has_snapshot:
                        try:
                            s_data = json.loads(snapshot_file.read_text(encoding="utf-8"))
                            node_cnt = s_data.get("node_count", 0)
                            edge_cnt = s_data.get("edge_count", 0)
                        except Exception:
                            pass

                    repo = ConnectedRepository(
                        repo_id="requests",
                        name="requests",
                        local_path=str(bundled_requests.resolve()),
                        default_branch="master",
                        working_revision=head_sha,
                        indexed_revision=head_sha if has_snapshot else None,
                        status=RepositoryStatus.READY
                        if has_snapshot
                        else RepositoryStatus.NOT_INDEXED,
                        python_file_count=self._count_python_files(bundled_requests),
                        graph_available=has_snapshot,
                        graph_name=f"requests_{short_sha}" if has_snapshot else None,
                        node_count=node_cnt,
                        edge_count=edge_cnt,
                        is_active=True,
                    )
                    self._repositories[repo.repo_id] = repo
                    self._active_repo_id = repo.repo_id
                    self._save_state()

    def _save_state(self) -> None:
        payload = {
            "version": "1.0.0",
            "active_repo_id": self._active_repo_id,
            "repositories": [r.model_dump() for r in self._repositories.values()],
        }
        self.persistence_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _count_python_files(self, path: Path) -> int:
        count = 0
        skip = {".git", ".venv", "venv", "__pycache__", "build", "dist", ".tox"}
        for p in path.rglob("*.py"):
            rel_parts = p.relative_to(path).parts
            if not any(part in skip or part.startswith(".") for part in rel_parts):
                count += 1
        return count

    def validate_local_path(self, raw_path: str) -> tuple[Path, str, str]:
        """Validate local directory path is a valid git repository.

        Returns: (resolved_path, head_sha, branch_name)
        """
        path = Path(raw_path).expanduser().resolve()
        if not path.exists():
            raise RepositoryValidationError(f"Path does not exist: {path}")
        if not path.is_dir():
            raise RepositoryValidationError(f"Path is not a directory: {path}")

        # Check git repository
        try:
            res = subprocess.run(
                ["git", "-C", str(path), "rev-parse", "--is-inside-work-tree"],
                capture_output=True,
                text=True,
                check=False,
                timeout=10,
            )
            if res.returncode != 0 or res.stdout.strip() != "true":
                raise RepositoryValidationError(f"Path is not a valid Git repository: {path}")
        except subprocess.TimeoutExpired as exc:
            raise RepositoryValidationError(f"Git check timed out for {path}") from exc
        except OSError as exc:
            raise RepositoryValidationError(f"Failed to execute git on {path}: {exc}") from exc

        # Read HEAD revision
        sha = git_head(path)
        if not sha:
            raise RepositoryValidationError(f"Unable to read Git HEAD revision from {path}")

        # Read branch name
        branch = "unknown"
        try:
            b_res = subprocess.run(
                ["git", "-C", str(path), "rev-parse", "--abbrev-ref", "HEAD"],
                capture_output=True,
                text=True,
                check=False,
                timeout=10,
            )
            if b_res.returncode == 0:
                branch = b_res.stdout.strip()
        except Exception:
            pass

        return path, sha, branch

    def connect_repository(self, raw_path: str, name: str | None = None) -> ConnectedRepository:
        """Connect and register a new local Git repository."""
        resolved_path, head_sha, branch = self.validate_local_path(raw_path)

        repo_name = name or resolved_path.name
        slug = re.sub(r"[^A-Za-z0-9_-]", "_", repo_name).lower().strip("_")
        if not slug:
            slug = f"repo_{int(time.time())}"

        # If repo_id already exists pointing to different path, generate unique slug
        repo_id = slug
        if repo_id in self._repositories and self._repositories[repo_id].local_path != str(
            resolved_path
        ):
            repo_id = f"{slug}_{int(time.time())}"

        py_count = self._count_python_files(resolved_path)

        # Check if already indexed snapshot exists
        graph_name = get_revision_graph_name(repo_name, head_sha)
        snapshot_file = self.graphs_dir / f"{graph_name}.json"
        is_indexed = snapshot_file.is_file()

        node_cnt = 0
        edge_cnt = 0
        if is_indexed:
            try:
                s_data = json.loads(snapshot_file.read_text(encoding="utf-8"))
                node_cnt = s_data.get("node_count", 0)
                edge_cnt = s_data.get("edge_count", 0)
            except Exception:
                pass

        is_first = len(self._repositories) == 0

        repo = ConnectedRepository(
            repo_id=repo_id,
            name=repo_name,
            local_path=str(resolved_path),
            default_branch=branch,
            working_revision=head_sha,
            indexed_revision=head_sha if is_indexed else None,
            status=RepositoryStatus.READY if is_indexed else RepositoryStatus.NOT_INDEXED,
            python_file_count=py_count,
            graph_available=is_indexed,
            graph_name=graph_name if is_indexed else None,
            node_count=node_cnt,
            edge_count=edge_cnt,
            is_active=is_first or self._active_repo_id is None,
        )

        self._repositories[repo_id] = repo
        if repo.is_active:
            self._active_repo_id = repo_id
            for other_id, other in self._repositories.items():
                if other_id != repo_id:
                    other.is_active = False

        self._save_state()
        return repo

    def get_repository(self, repo_id: str) -> ConnectedRepository | None:
        repo = self._repositories.get(repo_id)
        if repo:
            self._refresh_working_revision(repo)
        return repo

    def get_active_repository(self) -> ConnectedRepository | None:
        if self._active_repo_id:
            repo = self._repositories.get(self._active_repo_id)
            if repo:
                self._refresh_working_revision(repo)
                return repo
        if self._repositories:
            first_id = next(iter(self._repositories))
            repo = self._repositories[first_id]
            self.set_active_repository(first_id)
            return repo
        return None

    def set_active_repository(self, repo_id: str) -> ConnectedRepository:
        if repo_id not in self._repositories:
            raise KeyError(f"Repository {repo_id} not found")

        self._active_repo_id = repo_id
        for rid, r in self._repositories.items():
            r.is_active = rid == repo_id
        self._save_state()
        active_repo = self._repositories[repo_id]
        self._refresh_working_revision(active_repo)
        return active_repo

    def list_repositories(self) -> list[ConnectedRepository]:
        for repo in self._repositories.values():
            self._refresh_working_revision(repo)
        return list(self._repositories.values())

    def disconnect_repository(self, repo_id: str) -> bool:
        if repo_id not in self._repositories:
            return False
        del self._repositories[repo_id]
        if self._active_repo_id == repo_id:
            self._active_repo_id = next(iter(self._repositories)) if self._repositories else None
            if self._active_repo_id:
                self._repositories[self._active_repo_id].is_active = True
        self._save_state()
        return True

    def _refresh_working_revision(self, repo: ConnectedRepository) -> None:
        path = Path(repo.local_path)
        if path.is_dir():
            sha = git_head(path)
            if sha:
                repo.working_revision = sha
                if repo.indexed_revision and repo.working_revision != repo.indexed_revision:
                    repo.status = RepositoryStatus.STALE

    def ingest_repository_graph(
        self,
        repo_id: str,
        falkordb_client: FalkorDBClient | None = None,
        max_commits: int = 200,
    ) -> IngestionResult:
        """Execute ingestion lifecycle: parse AST, save snapshot, and persist to FalkorDB."""
        repo = self._repositories.get(repo_id)
        if not repo:
            raise KeyError(f"Repository {repo_id} not registered")

        repo_path = Path(repo.local_path)
        if not repo_path.is_dir():
            repo.status = RepositoryStatus.FAILED
            repo.last_error = f"Directory not found: {repo.local_path}"
            self._save_state()
            raise IngestionError(repo.last_error)

        # Update status
        repo.status = RepositoryStatus.INDEXING
        repo.last_error = None
        self._save_state()

        try:
            head_sha = git_head(repo_path)
            if not head_sha:
                raise IngestionError("Cannot resolve Git HEAD revision")

            # 1. Parse repository AST & Git metadata
            result = ingest_repository(
                repo_root=repo_path,
                repo_url=repo.name,
                revision=head_sha,
                include_history=True,
                max_commits=max_commits,
            )

            # 2. Persist snapshot to disk artifact
            graph_name = get_revision_graph_name(repo.name, head_sha)
            snapshot_path = self.graphs_dir / f"{graph_name}.json"
            save_graph_snapshot(result, snapshot_path)

            # 3. Update manifest
            self._update_graph_manifest(
                repo_name=repo.name,
                revision=head_sha,
                graph_name=graph_name,
                result=result,
                snapshot_path=snapshot_path,
            )

            # 4. Attempt FalkorDB persistence if client provided or available
            client = falkordb_client or FalkorDBClient(graph_name=graph_name)
            try:
                client.connect()
                persist_snapshot_to_falkordb(client, result, clear_existing=True)
            except Exception as db_exc:
                logger.info(
                    "FalkorDB persistence skipped/offline (%s); disk snapshot preserved.", db_exc
                )

            # 5. Update repository record
            repo.status = RepositoryStatus.READY
            repo.working_revision = head_sha
            repo.indexed_revision = head_sha
            repo.graph_available = True
            repo.graph_name = graph_name
            repo.node_count = len(result.nodes)
            repo.edge_count = len(result.edges)
            repo.python_file_count = self._count_python_files(repo_path)
            repo.last_ingested_at = datetime.now(UTC).isoformat()
            repo.last_error = None
            self._save_state()

            return result

        except Exception as exc:
            repo.status = RepositoryStatus.FAILED
            repo.last_error = str(exc)
            self._save_state()
            raise

    def _update_graph_manifest(
        self,
        repo_name: str,
        revision: str,
        graph_name: str,
        result: IngestionResult,
        snapshot_path: Path,
    ) -> None:
        manifest_path = self.graphs_dir / "manifest.json"
        manifest_data: dict[str, Any] = {
            "schema_version": "0.2.0",
            "revisions_count": 0,
            "graphs": [],
        }
        if manifest_path.is_file():
            try:
                manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
            except Exception:
                pass

        # Calculate sha256 of snapshot
        import hashlib

        snapshot_bytes = snapshot_path.read_bytes()
        sha256 = hashlib.sha256(snapshot_bytes).hexdigest()

        existing_graphs: list[dict[str, Any]] = manifest_data.get("graphs", [])
        updated_graphs = [g for g in existing_graphs if g.get("graph_name") != graph_name]
        updated_graphs.append(
            {
                "graph_name": graph_name,
                "revision": revision,
                "repo": repo_name,
                "node_count": len(result.nodes),
                "edge_count": len(result.edges),
                "sha256": sha256,
                "snapshot_file": snapshot_path.name,
                "updated_at": datetime.now(UTC).isoformat(),
            }
        )

        manifest_data["graphs"] = updated_graphs
        manifest_data["revisions_count"] = len(updated_graphs)
        manifest_path.write_text(json.dumps(manifest_data, indent=2), encoding="utf-8")

    def to_summary(self, repo: ConnectedRepository) -> RepositorySummary:
        return RepositorySummary(
            repo_id=repo.repo_id,
            name=repo.name,
            local_path=repo.local_path,
            default_branch=repo.default_branch,
            working_revision=repo.working_revision,
            short_sha=repo.working_revision[:8],
            indexed_revision=repo.indexed_revision,
            indexed_short_sha=repo.indexed_revision[:8] if repo.indexed_revision else None,
            status=repo.status.value,
            is_stale=repo.is_stale(),
            graph_available=repo.graph_available,
            graph_name=repo.graph_name,
            node_count=repo.node_count,
            edge_count=repo.edge_count,
            python_file_count=repo.python_file_count,
            last_ingested_at=repo.last_ingested_at,
            last_error=repo.last_error,
            is_active=repo.is_active,
        )
