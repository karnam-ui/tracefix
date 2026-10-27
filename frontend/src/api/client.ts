// TraceFix typed API client

import type {
  CaseSummary,
  ConnectRepositoryRequest,
  EvaluationReportSummary,
  GraphSummary,
  HealthResponse,
  IncidentMemoryItem,
  IngestProgressResponse,
  InvestigateRequest,
  InvestigateResponse,
  NeighborhoodResponse,
  RepositorySummary,
} from '../types'

const BASE_URL = import.meta.env.VITE_API_URL || ''

async function handleResponse<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let errorDetail = res.statusText
    try {
      const body = await res.json()
      if (body.detail) {
        errorDetail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail)
      }
    } catch {
      // Keep statusText fallback
    }
    throw new Error(`API Error ${res.status}: ${errorDetail}`)
  }
  return res.json()
}

export const api = {
  async getHealth(): Promise<HealthResponse> {
    const res = await fetch(`${BASE_URL}/api/health`)
    return handleResponse<HealthResponse>(res)
  },

  // -------------------------------------------------------------------------
  // Repositories
  // -------------------------------------------------------------------------

  async getRepositories(): Promise<RepositorySummary[]> {
    const res = await fetch(`${BASE_URL}/api/repos`)
    return handleResponse<RepositorySummary[]>(res)
  },

  async getActiveRepository(): Promise<RepositorySummary | null> {
    const res = await fetch(`${BASE_URL}/api/repos/active`)
    return handleResponse<RepositorySummary | null>(res)
  },

  async connectRepository(req: ConnectRepositoryRequest): Promise<RepositorySummary> {
    const res = await fetch(`${BASE_URL}/api/repos/connect`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(req),
    })
    return handleResponse<RepositorySummary>(res)
  },

  async selectRepository(repoId: string): Promise<RepositorySummary> {
    const res = await fetch(`${BASE_URL}/api/repos/select?repo_id=${encodeURIComponent(repoId)}`, {
      method: 'POST',
    })
    return handleResponse<RepositorySummary>(res)
  },

  async disconnectRepository(repoId: string): Promise<{ status: string; disconnected_repo_id: string }> {
    const res = await fetch(`${BASE_URL}/api/repos/${encodeURIComponent(repoId)}`, {
      method: 'DELETE',
    })
    return handleResponse<{ status: string; disconnected_repo_id: string }>(res)
  },

  async ingestRepository(repoId: string): Promise<IngestProgressResponse> {
    const res = await fetch(`${BASE_URL}/api/repos/${encodeURIComponent(repoId)}/ingest`, {
      method: 'POST',
    })
    return handleResponse<IngestProgressResponse>(res)
  },

  // -------------------------------------------------------------------------
  // Benchmark Cases & Graphs
  // -------------------------------------------------------------------------

  async getCases(): Promise<CaseSummary[]> {
    const res = await fetch(`${BASE_URL}/api/cases`)
    return handleResponse<CaseSummary[]>(res)
  },

  async getGraphs(): Promise<GraphSummary[]> {
    const res = await fetch(`${BASE_URL}/api/graphs`)
    return handleResponse<GraphSummary[]>(res)
  },

  async getNeighborhood(graphName: string, entityId?: string): Promise<NeighborhoodResponse> {
    const params = new URLSearchParams()
    if (entityId) {
      params.set('entity_id', entityId)
    }
    const url = `${BASE_URL}/api/graphs/${encodeURIComponent(graphName)}/neighborhood${
      params.toString() ? `?${params.toString()}` : ''
    }`
    const res = await fetch(url)
    return handleResponse<NeighborhoodResponse>(res)
  },

  async getMemoryRecords(): Promise<IncidentMemoryItem[]> {
    const res = await fetch(`${BASE_URL}/api/memory`)
    return handleResponse<IncidentMemoryItem[]>(res)
  },

  async investigate(req: InvestigateRequest): Promise<InvestigateResponse> {
    const res = await fetch(`${BASE_URL}/api/investigate`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(req),
    })
    return handleResponse<InvestigateResponse>(res)
  },

  async getEvaluations(): Promise<EvaluationReportSummary[]> {
    const res = await fetch(`${BASE_URL}/api/evaluations`)
    return handleResponse<EvaluationReportSummary[]>(res)
  },

  async getEvaluationReport(reportName: string): Promise<Record<string, unknown>> {
    const res = await fetch(`${BASE_URL}/api/evaluations/${encodeURIComponent(reportName)}`)
    return handleResponse<Record<string, unknown>>(res)
  },
}
