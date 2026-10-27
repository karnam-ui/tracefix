// TraceFix API TypeScript definitions

export interface HealthResponse {
  status: string
  version: string
  falkordb_connected: boolean
  redis_endpoint: string
  active_cases_count: number
  persisted_graphs_count: number
  incident_memory_count: number
  connected_repos_count: number
  active_repo_id?: string
}

export interface RepositorySummary {
  repo_id: string
  name: string
  local_path: string
  default_branch: string
  working_revision: string
  short_sha: string
  indexed_revision?: string | null
  indexed_short_sha?: string | null
  status: 'not_indexed' | 'indexing' | 'ready' | 'stale' | 'failed' | 'partially_indexed' | string
  is_stale: boolean
  graph_available: boolean
  graph_name?: string | null
  node_count: number
  edge_count: number
  python_file_count: number
  last_ingested_at?: string | null
  last_error?: string | null
  is_active: boolean
}

export interface ConnectRepositoryRequest {
  path: string
  name?: string
}

export interface IngestProgressResponse {
  repo_id: string
  status: string
  node_count: number
  edge_count: number
  elapsed_seconds: number
  graph_name: string
  parse_errors: Array<Record<string, unknown>>
  limitations: string[]
}

export interface CaseSummary {
  case_id: string
  repo: string
  revision: string
  short_sha: string
  localizable: boolean
  bug_report_preview: string
  ground_truth_files: string[]
  ground_truth_functions: string[]
  created_at?: string
  pre_cutoff?: boolean
}

export interface GraphSummary {
  case_id?: string
  revision: string
  short_sha: string
  graph_name: string
  node_count: number
  edge_count: number
  sha256: string
  is_live: boolean
  storage_type?: string
}

export interface NodeDetail {
  entity_id: string
  kind: string
  repo: string
  revision: string
  path: string
  qualified_name: string
  start_line: number
  end_line: number
}

export interface EdgeDetail {
  source_id: string
  target_id: string
  edge_type: string
  provenance: string
  source: string
  confidence?: string
}

export interface NeighborhoodResponse {
  graph_name: string
  revision: string
  center_id?: string
  nodes: NodeDetail[]
  edges: EdgeDetail[]
  source?: string
}

export interface RetrievalItem {
  evidence_id: string
  strategy: string
  rank: number
  score: number
  file: string
  symbol: string
  lines?: [number, number]
  provenance: string
  source_revision: string
  is_ground_truth_function: boolean
  is_ground_truth_file: boolean
}

export interface ContextItem {
  candidate_id: string
  file_path: string
  symbol: string
  token_cost: number
  strategy: string
  rank: number
  score: number
  included: boolean
  exclusion_reason?: string
}

export interface VerificationSummary {
  status: 'VERIFIED' | 'FAILED' | 'REJECTED' | 'TIMEOUT' | 'UNAVAILABLE' | string
  exit_code: number
  passed_tests: string[]
  failed_tests: string[]
  duration_seconds: number
  details?: string
}

export interface MemoryMatch {
  incident_id: string
  case_id: string
  revision: string
  similarity_score: number
  patch_preview: string
  status: string
  executed_at: string
}

export interface LifecycleStage {
  stage_id: string
  name: string
  status: 'pending' | 'running' | 'completed' | 'failed' | 'skipped' | string
  detail: string
  elapsed_ms: number
}

export interface BaselineComparisonResponse {
  baseline_strategy: string
  evaluated_strategy: string
  baseline_tokens: number
  evaluated_tokens: number
  token_delta: number
  reduction_pct?: number | null
  baseline_items_count: number
  evaluated_items_count: number
  common_symbols: string[]
  common_files: string[]
}

export type InvestigationMode = 'trace' | 'find' | 'snippets' | 'repair'

export interface InvestigateRequest {
  case_id?: string
  repo_id?: string
  repo?: string
  revision?: string
  bug_report?: string
  mode?: InvestigationMode
  strategy?: 'graph' | 'fused' | 'lexical' | 'memory' | string
  budget?: number
  mock?: boolean
  execute_repair?: boolean
  compare_baseline?: boolean
}

export interface InvestigateResponse {
  case_id: string
  repo: string
  repo_id?: string
  revision: string
  strategy_used: string
  mode?: string
  stages: LifecycleStage[]
  retrieval: RetrievalItem[]
  context_budget: {
    budget_limit: number
    tokens_used: number
    utilization: number
    included_count: number
    excluded_count: number
    counting_method?: string
  }
  context_items: ContextItem[]
  proposed_patch?: string
  patch_safety: {
    is_valid?: boolean
    errors?: string[]
    prohibited_files?: string[]
    warnings?: string[]
  }
  verification?: VerificationSummary
  memory_matches: MemoryMatch[]
  memory_stored: boolean
  ground_truth_functions: string[]
  ground_truth_files: string[]
  overall_status: string
  error?: string
  fallback_occurred?: boolean
  fallback_reason?: string
  baseline_comparison?: BaselineComparisonResponse | null
  is_mock?: boolean
}

export interface IncidentMemoryItem {
  incident_id: string
  case_id: string
  revision: string
  repo: string
  bug_report_snippet: string
  patch_diff: string
  verification_status: string
  created_at: string
}

export interface EvaluationReportSummary {
  file_name: string
  title: string
  dataset_fingerprint?: string
  cases_count: number
}
