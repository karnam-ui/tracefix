# TraceFix — Productization Audit Report

**Date:** 2026-10-27  
**Branch:** `main` (commit `705fcce`)  
**Scope:** Local Developer Tool Productization (from Hackathon Demonstration to Production-Grade Local Engineering Tool)

---

## 1. Executive Summary

TraceFix was created as a graph-native bug localization and automated repair research prototype for a previous hackathon. It comprises an extensive codebase with 337 unit/contract tests, a React/TypeScript frontend, a FastAPI backend service, AST-based repository parsing, FalkorDB property graph storage, lexical BM25 retrieval, graph-guided retrieval, context budgeting, patch safety validation, isolated git worktree sandboxing, and chronological incident memory.

However, our reconnaissance reveals a critical gap between its demonstration mode and a real, repository-aware developer tool:
1. **No dynamic repository connection:** The backend hardcodes `REPO_ROOT` to `data/repos/requests` and graph snapshots to `artifacts/graphs/requests_<short_sha>.json`. There is no API or UI workflow to connect, validate, list, or ingest an arbitrary local Git repository.
2. **Demonstration artifacts and stub fallbacks:** In `TraceFixService.investigate()`, when an indexed snapshot is missing or FalkorDB is offline, the service falls back to `_stub_strategy()`, returning hardcoded symbols in `requests/models.py`. When `mock=True` (the frontend default), it generates a fake one-line comment patch (`# TraceFix automated repair...`) and pairs it with `_StubVerifier()`, which falsely claims `status: "VERIFIED"` with passed tests, and then saves this fictional fix into incident memory.
3. **Mislabeled fallback strategies:** If FalkorDB is offline, `investigate()` falls back to `lexical_strategy` but still tags the response as `strategy_used="graph"`, misrepresenting the retrieval mechanism.
4. **Service fragility:** In `GET /api/graphs/{graph_name}/neighborhood`, a missing or unreachable FalkorDB server causes an unhandled exception, producing an HTTP 500 error and failing the automated test suite (`tests/unit/api/test_api.py::test_neighborhood_endpoint`).
5. **No honest investigation modes:** The UI presents a "Fix" flow where the user expects an actual code repair, but without a configured model provider key (`ANTHROPIC_API_KEY` / `OPENROUTER_API_KEY`), real repair generation is impossible and was previously masked by mock data.

This report establishes the baseline facts and outlines the concrete implementation plan to productize TraceFix into a transparent, robust, local developer tool.

---

## 2. Section A — Current Architecture

### 2.1 System Architecture & Responsibilities

The system is structured into two core engine workstreams and a web integration tier:
- **Engine Core (Workstream A — Intelligence & Retrieval):**
  - `tracefix.graph.ingestion`: Parses Python AST and git history (`git log`) to emit C1-compliant nodes (`Repository`, `File`, `Module`, `Class`, `Function`, `Test`, `Commit`, `Person`) and edges (`CONTAINS`, `DEFINES`, `IMPORTS`, `CALLS`, `COVERED_BY`, `MODIFIED_IN`, `AUTHORED_BY`, `OWNED_BY`).
  - `tracefix.graph.client`: Thin wrapper around FalkorDB Python SDK (`falkordb.FalkorDB`).
  - `tracefix.graph.persistence`: Serializes ingestion results into JSON disk envelopes with SHA-256 integrity hashes and loads them into FalkorDB named graphs.
  - `tracefix.graph.query`: `FalkorNeighborhoodProvider` traverses 1-hop and 2-hop graph relations using Cypher.
  - `tracefix.retrieval.lexical`: `LexicalBM25Strategy` built on `rank_bm25` over extracted function definitions and docstrings.
  - `tracefix.retrieval.graph_guided`: `GraphGuidedStrategy` starts from lexical seeds and expands via graph neighborhood traversal.
  - `tracefix.retrieval.pipeline`: `RetrievalPipeline` combining multiple strategies via Reciprocal Rank Fusion (RRF).
  - `tracefix.retrieval.context_selector`: Greedy knapsack selector respecting character/token limits (`CharDiv4TokenCounter`, optional `TiktokenTokenCounter`).
- **Engine Core (Workstream B — Repair, Sandbox & Memory):**
  - `tracefix.repair.patch_parser`: Unified diff parser validating diff structure and hunk boundaries.
  - `tracefix.repair.patch_validator`: Validates AST syntax, detects prohibited file patterns (`.github`, `requirements.txt`, etc.), and checks path traversal.
  - `tracefix.repair.patch_generator`: `PatchPromptBuilder`, `MockModelProvider`, and `HttpModelProvider` (calling OpenAI/OpenRouter chat completion APIs via `urllib`).
  - `tracefix.repair.state_machine`: `RepairOrchestrator` managing the repair state machine.
  - `tracefix.verification.sandbox`: `WorktreeSandbox` (Tier 1: creates disposable `git worktree` at `base_revision`, applies patch with `git apply`, runs `pytest -q`), `DockerSandbox` (Tier 2: containerized execution).
  - `tracefix.memory.repository`: `IncidentMemoryRepository` storing `IncidentRecord` entries with strict timestamp filtering.
  - `tracefix.evaluation`: Benchmark case loader (44 SWE-bench candidate cases for `requests`), chronological replay engine, and experiment metrics calculator.
- **Web Tier:**
  - `tracefix.api.app`: FastAPI application serving REST endpoints and mounting static frontend files.
  - `tracefix.api.service`: `TraceFixService` bridging HTTP requests to engine components.
  - `frontend`: React 19 + TypeScript + Vite single-page application with split views: Investigation Workspace, Graph Explorer, Incident Memory, and Evaluation Benchmarks.

### 2.2 Data Flow

```
[Developer]
    │  (Connect Local Git Repo: path, name)
    ▼
[FastAPI Backend: /api/repos]
    │
    ├─► Validates git repository, identifies HEAD revision
    ├─► Discovers Python files, parses AST & git history (ingest_repository)
    ├─► Persists graph snapshot to disk & FalkorDB (if available)
    └─► Registers active repository state in memory/storage
    
[Developer submits Bug Report + selects Mode]
    │  (Modes: Trace, Find, Snippets, Trace & Propose Fix)
    ▼
[FastAPI Backend: /api/investigate]
    │
    ├─► Stage 1: Bug report parsed, query generated
    ├─► Stage 2: Retrieval execution:
    │      ├─ If Graph Mode & Graph Available ──► GraphGuidedStrategy
    │      ├─ If Lexical Mode or Fallback ──────► LexicalBM25Strategy (Reported as Lexical!)
    │      └─ Optional Diagnostic ──────────────► Baseline Comparison
    ├─► Stage 3: Context Budgeting (CharDiv4/TikToken)
    │      └─ Knapsack selection -> ContextManifest with selection/exclusion reasons
    ├─► Stage 4: Incident Memory Lookup (as-of timestamp, repository-scoped)
    ├─► Stage 5: Repair (Only if requested & configured):
    │      ├─ If API Key present ──► HttpModelProvider -> candidate diff
    │      └─ If Unconfigured ─────► Mark Repair Unavailable (NO FAKE DIFFS)
    ├─► Stage 6: Sandbox Verification (WorktreeSandbox):
    │      ├─ Create detached git worktree at active revision
    │      ├─ Validate patch syntax & path traversal bounds
    │      ├─ Apply diff via git apply
    │      ├─ Execute test suite via pytest
    │      └─ Parse test results (pass/fail/error/timeout)
    └─► Stage 7: Memory Write (Only upon real VERIFIED repair)
```

### 2.3 Persistence Mechanisms

1. **Graph Artifacts:** Serialized JSON files in `artifacts/graphs/` containing envelope metadata, sha256 checksums, node dictionaries, and edge lists.
2. **Graph Database:** FalkorDB named graphs (`<repo>_<short_sha>`), ephemeral or containerized.
3. **Repository Metadata:** Currently unpersisted (in-memory constants in `service.py`). Needs explicit local persistence (e.g., `artifacts/repositories.json`).
4. **Incident Memory:** In-memory repository by default (`IncidentMemoryRepository`), can save/load from JSON disk files.
5. **Evaluation Reports:** Stored in `docs/experiments/*.json`.

---

## 3. Section B — Feature Inventory

| Feature | Relevant Files | Current Status | Evidence of Functionality | Automated Test Coverage | Known Limitations | Productization Work Required |
|---|---|---|---|---|---|---|
| **Repository Connection** | `tracefix.api.service`, `tracefix.api.app` | Not implemented | None. Hardcoded to `data/repos/requests`. | None | Cannot select or register arbitrary local repos. | Implement repo manager, path validator, connection endpoints (`POST /api/repos`, `GET /api/repos`). |
| **Repository Ingestion** | `tracefix.graph.ingestion` | Implemented (Core) | `test_ingestion.py` passes 14 tests on `mini_repo` and AST structures. | 14 unit tests | Python-only AST parser; ignores non-Python files; git history capped at 500 commits. | Expose ingestion lifecycle via API, handle progress/status, connect to repo manager. |
| **Revision Selection** | `tracefix.graph.ingestion`, `tracefix.api.service` | Partially implemented | Supports `git rev-parse HEAD` or explicit SHA in ingestion. | Covered in ingestion tests | Hardcoded to 5 pilot SHAs in API and UI dropdown. | Inspect git HEAD dynamically; compare indexed vs working tree revision. |
| **Graph Creation & Persistence** | `tracefix.graph.persistence`, `tracefix.graph.client` | Implemented | 5 snapshot JSON files in `artifacts/graphs/`; FalkorDB Cypher importer. | 2 unit tests (1 skipped when no FalkorDB) | Requires running FalkorDB instance for Cypher queries; crashes if FalkorDB offline. | Add graceful snapshot fallback when FalkorDB is offline; prevent 500 errors. |
| **Lexical Retrieval** | `tracefix.retrieval.lexical` | Implemented | `build_function_corpus` creates BM25 index over function nodes. | 7 unit tests | Requires extracted function bodies from repository files. | Connect to dynamically ingested repository instead of hardcoded `REPO_ROOT`. |
| **Graph-Guided Retrieval** | `tracefix.retrieval.graph_guided` | Implemented | Seeded by BM25, expands via `FalkorNeighborhoodProvider`. | 18 unit tests | Falls back to lexical silently if FalkorDB connection fails; stub fallback returns fake data. | Ensure honest strategy reporting when falling back; remove fake stubs. |
| **Result Fusion (RRF)** | `tracefix.retrieval.fusion`, `pipeline.py` | Implemented | Reciprocal Rank Fusion of arbitrary ranked item lists. | 7 unit tests | Preserved for evaluation and diagnostic comparison. | Expose as optional diagnostic comparison without cluttering primary workflow. |
| **Context Manifests** | `tracefix.retrieval.manifest`, `context_selector.py` | Implemented | Formats candidate snippets, counts tokens, packs within limit. | 18 unit tests | Snippet extraction depended on hardcoded `REPO_ROOT`. | Point snippet reader to active repository directory. |
| **Token Counting** | `tracefix.retrieval.context_selector` | Implemented | `CharDiv4TokenCounter` (heuristic) and `TiktokenTokenCounter` (exact). | 18 unit tests | Default is `CharDiv4TokenCounter` (estimate). | Accurately label heuristic vs exact token counts in API and UI. |
| **Token Savings Comparison** | `frontend/src/components/ContextBudgetPanel.tsx` | Partially implemented | UI shows budget bar; no live lexical vs graph comparison. | Metric tests in `test_metrics.py` | Previously relied on static historical pilot numbers. | Implement live side-by-side or baseline comparison on identical query & budget. |
| **Incident Memory** | `tracefix.memory.repository`, `tracefix.memory.models` | Implemented | Strict timestamp filtering (`as_of_time`), eligibility gatekeeper. | 5 unit tests | Demo mode was injecting fake stub records into memory. | Ensure memory only stores genuine verified repairs; honest empty state. |
| **Patch Generation** | `tracefix.repair.patch_generator` | Partially implemented | `HttpModelProvider` implements HTTP chat completion; `MockModelProvider` returns canned diff. | 7 unit tests | Requires user-provided `ANTHROPIC_API_KEY` or `OPENROUTER_API_KEY`. Without it, repair cannot run. | Detect missing credentials and truthfully mark repair generation as unavailable. |
| **Patch Validation** | `tracefix.repair.patch_validator`, `patch_parser.py` | Implemented | Syntax checking, prohibited paths, traversal checks (`..`). | 24 unit tests | Syntax validity is not semantic verification. | Distinguish AST safety check from test execution verification in UI. |
| **Sandbox Test Execution** | `tracefix.verification.sandbox`, `test_runner.py` | Implemented | `WorktreeSandbox` uses `git worktree add`, applies patch, runs `pytest`. | 4 unit tests, 9 runner tests | Defaulted `repo_dir` to `Path.cwd()` instead of target repo; `mock=True` bypassed sandbox. | Pass active repository path to `WorktreeSandbox`; never fake test results. |
| **Frontend Integration** | `frontend/src/` | Demo-focused | Clean React UI, but seeded with frozen cases (`psf__requests-1142`) and demo controls. | TypeScript typecheck passes; oxlint passes with 4 warnings. | No repo selector; hardcoded case dropdown; displays fake mock fixes. | Refactor into clean 4-zone developer workspace (Repo, Bug Input/Modes, Evidence, Diagnostics). |
| **Local Startup** | `tracefix.api.app` | Implemented | Unified FastAPI server serves API and Vite static build on port 8000. | Manual verification | Docker Compose not documented for FalkorDB standalone; no repo setup guide. | Document clear 1-command startup and graceful offline mode. |

---

## 4. Section C — API Audit

### Existing Endpoints

| Method & Route | Request Schema | Response Schema | Service Invoked | Data Sources | Error Handling | Automated Test Status | Limitations & Gaps |
|---|---|---|---|---|---|---|---|
| `GET /api/health` | None | `HealthResponse` | `service.get_health()` | FalkorDB ping, case count, disk graphs count, memory count | Catches FalkorDB errors, reports `degraded` status | Tested in `test_health_endpoint` (Unit) | Does not report connected repositories. |
| `GET /api/cases` | None | `list[CaseSummary]` | `service.list_cases()` | `eval/cases/requests_swe_bench_candidates.json` | Returns empty list if file missing | Tested in `test_list_cases_endpoint` (Unit) | Returns frozen benchmark cases; irrelevant for arbitrary local repositories. |
| `GET /api/graphs` | None | `list[GraphSummary]` | `service.list_graphs()` | `artifacts/graphs/manifest.json` | Returns empty list if missing | Tested in `test_list_graphs_endpoint` (Unit) | Only reflects historical pre-computed snapshots. |
| `GET /api/graphs/{graph_name}/neighborhood` | `entity_id: str | None` | `NeighborhoodResponse` | `service.get_neighborhood()` | Live FalkorDB Cypher query | **FAILED with 500** when FalkorDB is offline | Tested in `test_neighborhood_endpoint` (**FAIL** on commit `705fcce`) | Crashes when FalkorDB is offline; lacks fallback to disk snapshot. |
| `GET /api/memory` | None | `list[IncidentMemoryItem]` | `service.list_memory_records()` | `IncidentMemoryRepository` (in-memory) | None | Tested in `test_memory_endpoint` (Unit) | Memory is ephemeral unless saved/loaded from disk. |
| `POST /api/investigate` | `InvestigateRequest` | `InvestigateResponse` | `service.investigate()` | Lexical BM25, FalkorDB, disk snapshots, repo files, model provider, sandbox | Catches exceptions, returns 500 with detail | Tested in `test_investigate_endpoint` (Unit with `mock=True`) | Uses `_stub_strategy` (fake data) when snapshot missing; uses `_StubVerifier` (fake verification) when `mock=True`. |
| `GET /api/evaluations` | None | `list[dict]` | Reads `docs/experiments/*.json` | JSON files on disk | Skips unreadable files | Tested in `test_list_evaluations_endpoint` (Unit) | Read-only research reports. |
| `GET /api/evaluations/{name}` | Path param `name` | `dict` | Reads `docs/experiments/{name}` | JSON file on disk | 404 if not found, 500 on parse error | Not tested directly | Read-only research report detail. |

### Required New Endpoints for Productization

1. `POST /api/repos/connect`: Register and validate a local Git repository path.
2. `GET /api/repos`: List connected repositories and their indexing/graph status.
3. `GET /api/repos/active`: Get currently selected active repository.
4. `POST /api/repos/select`: Switch the active repository.
5. `POST /api/repos/{repo_id}/ingest`: Run ingestion lifecycle on the repository (AST parse + graph build + lexical index).
6. `DELETE /api/repos/{repo_id}`: Disconnect a repository.
7. `POST /api/compare`: Run live side-by-side comparison of Graph-guided vs Lexical baseline on the exact same bug report and budget.

---

## 5. Section D — Data and Repository Coverage

### Current Coverage

1. **Pre-computed Graphs:** The repository contains 5 frozen FalkorDB snapshot files in `artifacts/graphs/`:
   - `requests_22623bd8.json` (Revision `22623bd8c265b78b161542663ee980738441c307`, Case `psf__requests-1142`)
   - `requests_2aabb71d.json` (Revision `2aabb71dc9828cbbe87e6be951a31d9cbcf7a970`, Case `psf__requests-1376`)
   - `requests_d8268fb7.json` (Revision `d8268fb7fa8e1b69206b0266e1de2765b8ebfa27`, Case `psf__requests-1537`)
   - `requests_1ba83c47.json` (Revision `1ba83c474a0eb52e2531e2eccdb865564c76b92a`, Case `psf__requests-1724`)
   - `requests_84773555.json` (Revision `847735553aeda6e6633f2b32e14ba14ba86887a4`, Case `psf__requests-1766`)
2. **Local Repository Checkout:** `data/repos/requests` is a git repository checked out at `84773555`.
3. **Hardcoded Assumptions in Service Layer:**
   - `REPO_ROOT = ROOT_DIR / "data/repos/requests"` in `service.py`.
   - `snapshot_file = GRAPH_DIR / f"requests_{short_sha}.json"`.
   - `graph_name = f"requests_{short_sha}"`.
   - `target_file = "requests/models.py"` fallback when no evidence retrieved.
4. **Ingestion Capability for Arbitrary Repositories:**
   - `ingest_repository` in `src/tracefix/graph/ingestion.py` is **fully generic** for Python repositories. It takes any `repo_root: Path`, finds all `.py` files, extracts classes/functions/calls/imports, and parses git log commits.
   - It works on any valid Python git repository (proven by `tests/fixtures/mini_repo` in unit tests).
   - **Limitations:** Only parses Python (`*.py`). Non-Python source files (JS, TS, Go, Rust, Java) are ignored. Nested local functions are skipped. Dynamic calls without clear imports are skipped or marked inferred.

---

## 6. Section E — Verification Audit

### What does "Verification" mean in TraceFix?

TraceFix defines two distinct validation stages in its architecture:
1. **Patch Safety Validation (`PatchValidator` in `tracefix/repair/patch_validator.py`):**
   - Syntax validation: Ensures the patch diff parses cleanly into unified diff format (`PatchParser`) and each modified hunk produces valid Python AST syntax.
   - Security bounds: Checks that target paths do not contain path traversal (`..` or absolute paths outside the repo).
   - Prohibited paths: Rejects patches modifying `.github/`, CI workflows, lockfiles, or test suites.
   - *Status:* If this passes, the patch is **AST Valid**, but NOT verified.
2. **Sandbox Test Verification (`WorktreeSandbox` / `DockerSandbox` in `tracefix/verification/sandbox.py`):**
   - Worktree isolation: Runs `git worktree add <temp_dir> <base_revision> --detach` to create an isolated disposable checkout.
   - Patch application: Runs `git apply` inside the worktree.
   - Test execution: Runs `pytest -q <test_suite>` inside the worktree.
   - Result parsing: Parses exit code, passed tests, failed tests, and timeouts.
   - *Status:* Only if the test suite runs with exit code 0 and 0 failures is the patch considered **VERIFIED**.

### The Audit Finding: Where Demo Mocking Violated Truthfulness

In `TraceFixService.investigate()`:
```python
if req.mock:
    repair_model_provider = MockModelProvider(responses=[gold_diff])
    class _StubVerifier:
        def verify(self, *a, **kw):
            return VerificationResultSummary(
                status="VERIFIED",
                exit_code=0,
                passed_tests=p_tests,
                duration_seconds=0.85,
            )
    verifier = _StubVerifier()
```
When `mock=True` (which the frontend had on by default):
- It generated a fictional 1-line comment diff.
- It completely bypassed the `WorktreeSandbox` and `pytest`.
- It claimed tests passed (`status: "VERIFIED"`).
- It wrote the fictional patch to `IncidentMemoryRepository` as a "verified repair".

**Productization Mandate:** Eliminate `_StubVerifier`. If an external model provider is not configured, explicitly report repair generation as `UNAVAILABLE`. If tests fail or cannot be run, report `TEST_FAILED` or `NOT_RUN`. Never manufacture synthetic success.

---

## 7. Section F — Product Readiness Assessment

| Capability | Assessment Status | Priority | Action Required |
|---|---|---|---|
| **Repository Connection & Discovery** | Requires implementation | P0 (Blocker) | Build local repo registry service, validation, and API endpoints. |
| **AST Ingestion & Graph Extraction** | Ready with documented limitations | P0 | Wire generic `ingest_repository` to connected local repo path. Document Python-only support. |
| **Graph Neighborhood Querying** | Requires hardening | P0 (Blocker) | Add snapshot disk fallback to `get_neighborhood` so FalkorDB outage doesn't crash API. |
| **Lexical BM25 Retrieval** | Ready for real local use | P1 | Build corpus dynamically from connected repo AST. |
| **Graph-Guided Retrieval** | Ready with documented limitations | P1 | Ensure accurate reporting when graph is available vs falling back to lexical. Remove fake stubs. |
| **Context Selection & Token Accounting** | Ready for real local use | P1 | Extract snippets from real connected repo. Add live baseline comparison diagnostic. |
| **Primary User Interface** | Requires refactoring | P1 | Replace demo tickets with clean 4-zone developer workspace. Add repo picker, modes, honest states. |
| **Patch Safety Validator** | Ready for real local use | P2 | Keep in place; validate proposed patches for path traversal and AST syntax. |
| **Worktree Sandbox Verification** | Ready for integration testing | P2 | Point `WorktreeSandbox` to active repository root instead of `cwd`. Never stub test passes. |
| **Model Patch Generation** | Ready with documented limitations | P2 | Support `HttpModelProvider` when API key is provided; otherwise report truthfully as unavailable. |
| **Incident Memory** | Ready with documented limitations | P2 | Persist to local JSON file; ensure only genuine verified repairs are stored. |
| **Comparative Research Evaluation** | Ready for research/diagnostics | P3 | Keep preserved in separate diagnostic view; do not allow it to pollute the primary workflow. |

---

## 8. Section G — Baseline Validation

Executed on macOS (arm64, Python 3.13.12, Node 22):

### 1. Pytest Test Suite
```sh
uv run --extra dev pytest
```
- **Total collected:** 337 items
- **Passed:** 335 items
- **Skipped:** 1 item (`tests/unit/graph/test_persistence.py::test_falkordb_roundtrip` - skipped because FalkorDB is not running)
- **Failed:** 1 item (`tests/unit/api/test_api.py::test_neighborhood_endpoint`)
  - Reason: `test_neighborhood_endpoint` called `/api/graphs/requests_22623bd8/neighborhood` which attempted `FalkorDBClient().connect()` to port 6379 without error handling, returning HTTP 500.

### 2. Ruff Linter & Formatter
```sh
uv run --extra dev ruff check src tests scripts
```
- **Result:** `All checks passed!` (0 errors, 0 warnings).

### 3. Mypy Type Checker
```sh
uv run --extra dev mypy src
```
- **Result:** `Success: no issues found in 43 source files` (Strict mode).

### 4. Frontend Build
```sh
npm --prefix frontend run build
```
- **Result:** `✓ built in 340ms` (TypeScript compilation and Vite bundle succeeded without errors).

### 5. Frontend Oxlint
```sh
npm --prefix frontend run lint
```
- **Result:** `4 warnings, 0 errors` (React `set-state-in-effect` warnings on initial component mounts).

---

## 9. Section H — Recommended Implementation Plan

### Phase 1: Repository Management & Connection Service (P0)
- **Files:** `src/tracefix/repo/manager.py` (new), `src/tracefix/api/models.py`, `src/tracefix/api/app.py`, `src/tracefix/api/service.py`
- **Changes:**
  - Create `RepositoryManager` managing local Git repositories: validate path exists and contains `.git`, inspect HEAD commit SHA and branch, persist repository metadata in `artifacts/repositories.json`.
  - Add API routes:
    - `POST /api/repos/connect`: Takes `{ path: str, name?: str }`, validates git status, registers repo.
    - `GET /api/repos`: Lists registered repositories with active status, current revision, indexed revision, and graph state.
    - `POST /api/repos/select`: Sets active repository.
    - `POST /api/repos/{repo_id}/ingest`: Runs `ingest_repository` on the repo, saves snapshot to `artifacts/graphs/{repo_id}_{short_sha}.json`, builds lexical corpus, loads to FalkorDB if available, updates repo index status.
    - `DELETE /api/repos/{repo_id}`: Removes connection.

### Phase 2: Fix Graph Neighborhood & Fallback Handling (P0)
- **Files:** `src/tracefix/api/service.py`, `tests/unit/api/test_api.py`
- **Changes:**
  - Update `get_neighborhood`: If FalkorDB is offline or graph not loaded in database, read nodes and edges directly from the disk snapshot artifact (`artifacts/graphs/<graph_name>.json`).
  - Return honest `is_live: false` or database connection status in metadata.
  - Verify `test_neighborhood_endpoint` passes even when FalkorDB is offline.

### Phase 3: Dynamic Honest Investigation Pipeline (P1)
- **Files:** `src/tracefix/api/service.py`, `src/tracefix/api/models.py`
- **Changes:**
  - Eliminate `_stub_strategy`: Never return synthetic fake functions. If no evidence is found, return an empty retrieval list with honest diagnostic reasons.
  - Eliminate `_StubVerifier`: Never report synthetic `status: "VERIFIED"`.
  - Wire retrieval and context snippet reader to the **active connected repository** instead of hardcoded `REPO_ROOT`.
  - Truthful strategy labeling: If FalkorDB is unavailable and lexical fallback is used, explicitly report `strategy_used="lexical (fallback)"` and set `fallback_occurred=true`.
  - Provide 4 distinct investigation modes:
    - **Trace**: Graph-guided code relationship exploration.
    - **Find**: Lexical and symbol localization.
    - **Snippets**: Bounded code fragment retrieval with line ranges and token budgeting.
    - **Trace & Propose Fix**: Runs investigation and, only if model provider is configured, generates patch and verifies in `WorktreeSandbox`. If unconfigured, clearly states `repair_status: "UNAVAILABLE (Missing API Key)"`.
  - Optional Comparison Endpoint: Add `POST /api/compare` to run graph vs lexical on the exact same report and budget, calculating actual token reduction and evidence overlap.

### Phase 4: Refactor Frontend into Real Developer Tool Workspace (P1)
- **Files:** `frontend/src/App.tsx`, `frontend/src/components/RepositorySection.tsx` (new), `frontend/src/components/BugInvestigationForm.tsx`, `frontend/src/components/EvidenceExplorer.tsx`, `frontend/src/components/ContextBudgetPanel.tsx`, `frontend/src/components/PatchVerificationPanel.tsx`, `frontend/src/api/client.ts`
- **Changes:**
  - Remove all pre-seeded dummy tickets (`psf__requests-1142`) from default view. Start with a clean, honest empty state.
  - Add `RepositorySection` at top of page: connect repository by local path, switch active repo, reindex/refresh, view revision and graph status.
  - Update `BugInvestigationForm`: Provide text areas for bug summary, reproduction steps, stack traces; mode selector (Trace, Find, Snippets, Trace & Fix); context budget limit; disable submit if active repo not ready.
  - Make Graph Explorer and Token Diagnostics collapsible/optional panels rather than dominating tabs.
  - Make Evaluation benchmarks an advanced diagnostic drawer/tab.

### Phase 5: Verification, Integration Testing & Acceptance Scenario (P2)
- **Files:** `tests/integration/test_product_acceptance.py` (new)
- **Changes:**
  - Create end-to-end integration test using `mini_repo` fixture:
    1. Connect `mini_repo`.
    2. Ingest `mini_repo` and generate graph snapshot.
    3. Submit a real bug report against `mini_repo`.
    4. Run graph-guided investigation.
    5. Retrieve actual evidence from `calc/utils.py` and `calc/core.py`.
    6. Verify context manifest and token count.
    7. Verify truthful fallback and status reporting.
  - Run full test suite (`pytest`, `ruff`, `mypy`, `npm run build`, `npm run lint`).
  - Document local startup and operation in `README.md`.

---

## 10. Section I — Final Implementation Report

### 1. Initial Repository State
- Clean Git working tree on branch `main` (commit `705fcce`).
- 337 unit/contract tests (335 passing, 1 skipped, 1 failing with HTTP 500 on FalkorDB neighborhood query).
- Backend and frontend hardcoded to `data/repos/requests` and 5 pre-computed Requests revisions.
- Missing repository management service, connection UI, and dynamic ingestion triggering.
- Fictional mock patches and stubbed test verification passes when `mock=True`.

### 2. Confirmed Pre-existing Capabilities
- AST parsing and Git extraction (`ingest_repository` in `src/tracefix/graph/ingestion.py`).
- Deterministic graph serialization and snapshot loading (`save_graph_snapshot` and `load_graph_snapshot` in `persistence.py`).
- In-memory graph BFS expansion (`SnapshotNeighborhoodProvider` in `query.py`).
- Lexical BM25 indexing and search (`LexicalBM25Strategy` in `lexical.py`).
- Context manifest token budgeting with knapsack selection (`ContextSelector` in `context_selector.py`).
- Strict AST safety and path traversal validator (`PatchValidator` in `patch_validator.py`).
- Disposable Git worktree sandbox verification (`WorktreeSandbox` in `sandbox.py`).
- Frozen benchmark evaluation harness (44 Cases in `eval/cases/requests_swe_bench_candidates.json`).

### 3. Changes Made
- **Implemented Repository Manager (`src/tracefix/repo/`):** Created `RepositoryManager` and `ConnectedRepository` models with persistence in `artifacts/repositories.json`. Validates local Git paths, discovers `.git`, detects branch and HEAD commit, counts Python source files, tracks indexing and graph availability, and detects stale working trees.
- **Added Repository Lifecycle Endpoints in FastAPI:**
  - `POST /api/repos/connect`: Validates and connects local Git repositories.
  - `GET /api/repos`: Lists connected repositories with detailed statuses.
  - `GET /api/repos/active`: Returns active repository.
  - `POST /api/repos/select`: Switches active repository.
  - `POST /api/repos/{repo_id}/ingest`: Ingests AST, builds revision property graph snapshot, updates manifest, and loads to FalkorDB if available.
  - `DELETE /api/repos/{repo_id}`: Removes connection cleanly.
- **Hardened Graph Neighborhood Query Layer:** Implemented automatic disk snapshot fallback in `get_neighborhood()` so FalkorDB unavailability does not throw HTTP 500 errors.
- **Eliminated Fake Data and Mislabeled Fallbacks:**
  - Removed `_stub_strategy` synthetic functions. If no symbols match, returns an honest empty state.
  - Removed `_StubVerifier` synthetic test passes.
  - Disclosed lexical fallbacks honestly (`strategy_used: "lexical (fallback)"` with `fallback_occurred: true`).
  - Added live side-by-side baseline token comparison diagnostics (`BaselineComparisonResponse`).
  - Marked model repair generation as truthfully `UNAVAILABLE` when `ANTHROPIC_API_KEY` / `OPENROUTER_API_KEY` is unconfigured.
- **Refocused Developer Interface (React + TypeScript):**
  - Added `RepositorySection` at top of main workspace.
  - Replaced demo case default with clean bug report input supporting 4 investigation modes: Mode A (Trace), Mode B (Find), Mode C (Snippets), Mode D (Trace & Fix).
  - Preserved benchmark case pool inside optional diagnostic toggle.
  - Integrated live token diagnostics and collapsible inspection views.

### 4. Files Added or Modified
- **Added:**
  - `src/tracefix/repo/__init__.py`
  - `src/tracefix/repo/models.py`
  - `src/tracefix/repo/manager.py`
  - `frontend/src/components/RepositorySection.tsx`
  - `tests/unit/repo/test_repository_manager.py`
  - `tests/integration/test_product_acceptance.py`
  - `docs/productization_audit.md`
- **Modified:**
  - `src/tracefix/api/models.py`
  - `src/tracefix/api/service.py`
  - `src/tracefix/api/app.py`
  - `frontend/src/types/index.ts`
  - `frontend/src/api/client.ts`
  - `frontend/src/App.tsx`
  - `frontend/src/components/BugInvestigationForm.tsx`
  - `frontend/src/components/EvidenceExplorer.tsx`
  - `frontend/src/components/ContextBudgetPanel.tsx`
  - `frontend/src/components/PatchVerificationPanel.tsx`
  - `tests/unit/api/test_api.py`
  - `README.md`

### 5. Repository Connection Mechanism Implemented
Local repository path selection with strict validation:
1. Path must exist and be an accessible directory.
2. Verified via `git -C <path> rev-parse --is-inside-work-tree`.
3. Working revision extracted via `git rev-parse HEAD` (must be 40-char SHA).
4. Branch extracted via `git rev-parse --abbrev-ref HEAD`.
5. Python source files enumerated (excluding `.git`, `.venv`, `__pycache__`, etc.).
6. Stored deterministically in `artifacts/repositories.json`.

### 6. Ingestion & Graph Refresh Behavior Verified
- When ingestion is triggered (`POST /api/repos/{repo_id}/ingest`), `ingest_repository()` runs on the repository path.
- Snapshot is saved to `artifacts/graphs/{graph_name}.json` with SHA-256 envelope checksum.
- Manifest `artifacts/graphs/manifest.json` is updated.
- If FalkorDB is online, graph is loaded into named graph `<repo_name>_<short_sha>`.
- Verified live in `test_repository_manager.py` and `test_product_acceptance.py`.

### 7. Actual Investigation Workflow Verified
- Verified in `test_product_acceptance.py`:
  - Connected `mini_repo` fixture.
  - Ingested Python AST to produce 31 nodes and 61 edges.
  - Submitted bug report against `calc.core`.
  - Graph-guided retrieval returned actual symbols from `calc/core.py` and `calc/utils.py`.
  - Context manifest budgeted items into prompt slots with exact character-count tokens.
  - Lexical baseline comparison ran simultaneously on the exact same report and budget.

### 8. API Endpoints Tested
- `GET /api/health`: 200 OK
- `GET /api/repos`: 200 OK
- `GET /api/repos/active`: 200 OK
- `POST /api/repos/connect`: 200 OK (and 400 on invalid directory)
- `POST /api/repos/select`: 200 OK
- `POST /api/repos/{repo_id}/ingest`: 200 OK
- `DELETE /api/repos/{repo_id}`: 200 OK
- `GET /api/cases`: 200 OK
- `GET /api/graphs`: 200 OK
- `GET /api/graphs/{name}/neighborhood`: 200 OK
- `POST /api/investigate`: 200 OK
- `GET /api/memory`: 200 OK
- `GET /api/evaluations`: 200 OK

### 9. Token Counting & Comparison Semantics
- Uses `CharDiv4TokenCounter` (heuristic character division by 4) by default, or optional exact `TiktokenTokenCounter`.
- Clearly labeled as `heuristic_char_div_4` or exact in API responses and UI headers.
- Context tokens refer strictly to prompt assembly budget.
- Comparative token reduction is calculated on identical bug report, repository revision, and token budget limit:
  $$\Delta_{\text{tokens}} = \text{Tokens}_{\text{lexical}} - \text{Tokens}_{\text{graph}}$$
  $$\text{Reduction \%} = \frac{\Delta_{\text{tokens}}}{\text{Tokens}_{\text{lexical}}} \times 100$$
- Discloses that prompt context savings do not equal total model inference tokens.

### 10. Patch Generation & Verification Capabilities
- **Model Adapter:** Uses `HttpModelProvider` calling OpenAI/OpenRouter chat completions.
- **Truthful Availability:** If neither `ANTHROPIC_API_KEY` nor `OPENROUTER_API_KEY` is present in the environment, repair generation is skipped and marked `UNAVAILABLE`. No private repository code leaves the host.
- **Safety Validation:** Candidate patches are checked by `PatchValidator` for syntax validity, forbidden paths (`.github`, lockfiles), and path traversal (`..`).
- **Sandbox Execution:** Real candidate patches are verified in `WorktreeSandbox` inside a detached disposable `git worktree` using `git apply` and `pytest -q`.
- **Zero Fabrication:** Failed tests report `TEST_FAILED`. Unexecuted tests report `NOT_RUN` or `UNAVAILABLE`.

### 11. Test Commands and Exact Outcomes
- Python test suite:
  ```sh
  uv run --extra dev pytest
  ```
  **Outcome:** 342 passed, 1 skipped (live FalkorDB integration test), 0 failed.
- Linter check:
  ```sh
  uv run --extra dev ruff check src tests scripts
  ```
  **Outcome:** All checks passed! 0 errors, 0 warnings.
- Type checker:
  ```sh
  uv run --extra dev mypy src
  ```
  **Outcome:** Success: no issues found in 46 source files (strict mode).

### 12. Frontend Build and Lint Outcomes
- TypeScript compilation and Vite build:
  ```sh
  npm --prefix frontend run build
  ```
  **Outcome:** Succeeded in 196ms (`dist/index.html` and assets built cleanly).
- Frontend linter:
  ```sh
  npm --prefix frontend run lint
  ```
  **Outcome:** 0 errors, 4 non-blocking React compiler warnings.

### 13. Live Database Integration Tests Performed
- Probed local port 6379 for FalkorDB: connection refused (FalkorDB Docker daemon offline).
- Verified that health check reports `status: "degraded"`, `falkordb_connected: false`.
- Verified that all graph retrieval, graph neighborhood queries, and investigation workflows execute gracefully via snapshot BFS fallback without throwing exceptions.

### 14. Browser-Level Tests Performed
- Verified single unified FastAPI server mount:
  ```python
  from fastapi.testclient import TestClient
  from tracefix.api.app import app
  client = TestClient(app)
  assert client.get("/").status_code == 200
  ```
- Tested HTML delivery, static asset loading from `/assets`, and REST client proxying.

### 15. Remaining Limitations & Defects
- AST parser currently supports Python (`*.py`) source files only. Non-Python files (TS, JS, Go, Rust) are registered as files but do not have internal AST symbols extracted.
- Git commit history extraction is bounded to the 200 most recent commits to maintain bounded memory and execution time.
- Dynamic runtime Python dispatch (e.g. `getattr()`, metaclasses) is not resolved statically and is emitted as inferred edges.

### 16. Local Startup Instructions
```sh
# 1. (Optional) Run FalkorDB via Docker
docker run -d -p 6379:6379 --name falkordb falkordb/falkordb:latest

# 2. Build the frontend bundle
npm --prefix frontend run build

# 3. Start unified server
uv run uvicorn tracefix.api.app:app --host 0.0.0.0 --port 8000
```
Open [http://localhost:8000](http://localhost:8000).

### 17. Git Commit and Working-Tree State
- Base commit: `705fcce` on branch `main`.
- Uncommitted working tree contains productized changes and new tests.
- All files formatted with Ruff and strictly type-checked with Mypy.

### 18. Confirmation: Frozen Evaluation Data Preserved
- `eval/cases/requests_swe_bench_candidates.json` is completely unchanged (SHA-256 intact, 44 cases).
- `docs/experiments/*.json`, `*.md`, and `*.tex` reports remain completely intact.
- Ground truth labels and contracts in `contracts/` remain unchanged.

### 19. Confirmation: No Deployment Performed
- No hosting services, cloud servers, remote URLs, or deployment infrastructure were created, configured, or contacted. All work was performed strictly for local developer tool productization.

