import React, { useEffect, useState, useCallback } from 'react'
import { api } from './api/client'
import { InvestigationPanel } from './components/InvestigationPanel'
import { DependencyGraphPanel } from './components/DependencyGraphPanel'
import { FindingsPanel } from './components/FindingsPanel'
import { McpGuideModal } from './components/McpGuideModal'
import { DiagnosticsModal } from './components/DiagnosticsModal'
import type {
  CaseSummary,
  ConnectRepositoryRequest,
  HealthResponse,
  InvestigateRequest,
  InvestigateResponse,
  NeighborhoodResponse,
  RepositorySummary,
} from './types'

export const App: React.FC = () => {
  // Global & Health State
  const [health, setHealth] = useState<HealthResponse | null>(null)
  const [repositories, setRepositories] = useState<RepositorySummary[]>([])
  const [activeRepo, setActiveRepo] = useState<RepositorySummary | null>(null)
  const [cases, setCases] = useState<CaseSummary[]>([])

  // Investigation & Results State
  const [investigateResult, setInvestigateResult] = useState<InvestigateResponse | null>(null)
  const [isLoading, setIsLoading] = useState<boolean>(false)
  const [investigateError, setInvestigateError] = useState<string | null>(null)

  // Graph Neighborhood State
  const [neighborhood, setNeighborhood] = useState<NeighborhoodResponse | null>(null)
  const [graphLoading, setGraphLoading] = useState<boolean>(false)

  // Modals
  const [showMcpGuide, setShowMcpGuide] = useState<boolean>(false)
  const [showDiagnostics, setShowDiagnostics] = useState<boolean>(false)

  // Fetch Health
  const fetchHealth = async () => {
    try {
      const h = await api.getHealth()
      setHealth(h)
    } catch (err) {
      console.warn('Backend probe warning:', err)
      setHealth(null)
    }
  }

  // Fetch Repositories
  const fetchRepositories = async () => {
    try {
      const rList = await api.getRepositories()
      setRepositories(rList)
      const active = rList.find((r) => r.is_active) || (rList.length > 0 ? rList[0] : null)
      setActiveRepo(active)
      return active
    } catch (err) {
      console.warn('Failed to fetch repositories:', err)
      return null
    }
  }

  // Fetch Benchmark Cases
  const fetchCases = async () => {
    try {
      const cList = await api.getCases()
      setCases(cList)
    } catch (err) {
      console.warn('Failed to fetch benchmark cases:', err)
    }
  }

  // Fetch Graph Neighborhood for the current repo
  const fetchNeighborhood = useCallback(async (repo: RepositorySummary | null, centerId?: string) => {
    if (!repo) return
    const graphName = repo.graph_name || `${repo.repo_id}_graph`
    setGraphLoading(true)
    try {
      const res = await api.getNeighborhood(graphName, centerId)
      setNeighborhood(res)
    } catch (err) {
      console.warn('Could not load neighborhood for graph:', graphName, err)
    } finally {
      setGraphLoading(false)
    }
  }, [])

  // Initial load
  useEffect(() => {
    fetchHealth()
    fetchCases()
    fetchRepositories().then((active) => {
      if (active) {
        fetchNeighborhood(active)
      }
    })
    const timer = setInterval(fetchHealth, 15000)
    return () => clearInterval(timer)
  }, [fetchNeighborhood])

  // Select Repository
  const handleSelectRepo = async (repoId: string) => {
    try {
      const updated = await api.selectRepository(repoId)
      setActiveRepo(updated)
      await fetchRepositories()
      setInvestigateResult(null)
      fetchNeighborhood(updated)
    } catch (err) {
      setInvestigateError(err instanceof Error ? err.message : 'Failed to select repository')
    }
  }

  // Connect Local Repository
  const handleConnectRepo = async (req: ConnectRepositoryRequest) => {
    const connected = await api.connectRepository(req)
    setActiveRepo(connected)
    await fetchRepositories()
    fetchNeighborhood(connected)
  }

  // Ingest Repository
  const handleIngestRepo = async (repoId: string) => {
    await api.ingestRepository(repoId)
    const updated = await fetchRepositories()
    await fetchHealth()
    if (updated) {
      fetchNeighborhood(updated)
    }
  }

  // Disconnect Repository
  const handleDisconnectRepo = async (repoId: string) => {
    await api.disconnectRepository(repoId)
    const remaining = await fetchRepositories()
    setInvestigateResult(null)
    if (remaining) {
      fetchNeighborhood(remaining)
    } else {
      setNeighborhood(null)
    }
  }

  // Submit Investigation
  const handleInvestigate = async (req: InvestigateRequest) => {
    setIsLoading(true)
    setInvestigateError(null)

    try {
      const res = await api.investigate(req)
      setInvestigateResult(res)

      // Center graph on top retrieved evidence if available
      if (res.retrieval && res.retrieval.length > 0 && activeRepo) {
        const topSymbol = res.retrieval[0].symbol
        fetchNeighborhood(activeRepo, topSymbol)
      }
    } catch (err) {
      setInvestigateError(err instanceof Error ? err.message : 'Investigation failed')
    } finally {
      setIsLoading(false)
    }
  }

  // Reset Investigation
  const handleReset = () => {
    setInvestigateResult(null)
    setInvestigateError(null)
    if (activeRepo) {
      fetchNeighborhood(activeRepo)
    }
  }

  // User interactions across panels
  const handleFocusEvidenceInGraph = (_file: string, symbol: string) => {
    if (activeRepo) {
      fetchNeighborhood(activeRepo, symbol)
    }
  }

  const handleCenterGraphNode = (entityId: string) => {
    if (activeRepo) {
      fetchNeighborhood(activeRepo, entityId)
    }
  }

  // Calculate highlighted entity IDs in graph from investigation results
  const highlightedEntityIds = React.useMemo(() => {
    if (!investigateResult?.retrieval) return []
    const ids: string[] = []
    investigateResult.retrieval.forEach((item) => {
      ids.push(item.symbol)
      ids.push(item.file)
      ids.push(item.evidence_id)
    })
    return ids
  }, [investigateResult])

  return (
    <div className="min-h-screen bg-[#f3efe6] flex items-center justify-center p-3 md:p-5 antialiased font-sans">
      <div className="w-full max-w-[1640px] h-[calc(100vh-2rem)] flex flex-col justify-between">
        {investigateError && (
          <div className="mb-2 px-4 py-2 bg-rose-50 border border-rose-200 text-rose-800 rounded-xl text-xs flex items-center justify-between">
            <span>
              <strong>Investigation Error:</strong> {investigateError}
            </span>
            <button
              type="button"
              onClick={() => setInvestigateError(null)}
              className="text-rose-600 hover:text-rose-900 font-medium cursor-pointer"
            >
              Dismiss
            </button>
          </div>
        )}

        {/* 3 Floating Cards Layout */}
        <div className="flex-1 grid grid-cols-1 lg:grid-cols-12 gap-4 h-full min-h-0">
          {/* Card 1: Investigation Form (Col 1-3: ~25% width) */}
          <div className="lg:col-span-3 h-full min-h-0">
            <InvestigationPanel
              repositories={repositories}
              activeRepository={activeRepo}
              cases={cases}
              isLoading={isLoading}
              stages={investigateResult?.stages}
              onSelectRepo={handleSelectRepo}
              onConnectRepo={handleConnectRepo}
              onIngestRepo={handleIngestRepo}
              onDisconnectRepo={handleDisconnectRepo}
              onSubmit={handleInvestigate}
              onReset={handleReset}
              onOpenMcpGuide={() => setShowMcpGuide(true)}
              onOpenDiagnostics={() => setShowDiagnostics(true)}
            />
          </div>

          {/* Card 2: Dependency Graph (Col 4-9: ~50% width) */}
          <div className="lg:col-span-6 h-full min-h-0">
            <DependencyGraphPanel
              neighborhood={neighborhood}
              loading={graphLoading}
              highlightedEntityIds={highlightedEntityIds}
              onCenterEntityChange={handleCenterGraphNode}
            />
          </div>

          {/* Card 3: Findings Summary (Col 10-12: ~25% width) */}
          <div className="lg:col-span-3 h-full min-h-0">
            <FindingsPanel
              investigation={investigateResult}
              loading={isLoading}
              onSelectEvidence={handleFocusEvidenceInGraph}
            />
          </div>
        </div>
      </div>

      {/* MCP Integration Setup Modal */}
      <McpGuideModal
        isOpen={showMcpGuide}
        onClose={() => setShowMcpGuide(false)}
      />

      {/* Engineering Diagnostics & Incident Memory Modal */}
      <DiagnosticsModal
        isOpen={showDiagnostics}
        onClose={() => setShowDiagnostics(false)}
        health={health}
      />
    </div>
  )
}
