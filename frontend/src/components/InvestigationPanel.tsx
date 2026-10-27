import React, { useState } from 'react'
import {
  GitBranch,
  ChevronDown,
  Network,
  RotateCcw,
  Plus,
  Play,
  X,
  SlidersHorizontal,
} from 'lucide-react'
import type {
  CaseSummary,
  ConnectRepositoryRequest,
  InvestigateRequest,
  InvestigationMode,
  LifecycleStage,
  RepositorySummary,
} from '../types'

export interface InvestigationPanelProps {
  repositories: RepositorySummary[]
  activeRepository: RepositorySummary | null
  cases?: CaseSummary[]
  isLoading: boolean
  stages?: LifecycleStage[]
  onSelectRepo: (repoId: string) => void
  onConnectRepo: (req: ConnectRepositoryRequest) => Promise<void>
  onIngestRepo: (repoId: string) => Promise<void>
  onDisconnectRepo?: (repoId: string) => Promise<void>
  onSubmit: (req: InvestigateRequest) => void
  onReset: () => void
  onOpenMcpGuide?: () => void
  onOpenDiagnostics?: () => void
}

const GithubIcon: React.FC<{ className?: string }> = ({ className = 'w-3.5 h-3.5' }) => (
  <svg className={className} viewBox="0 0 24 24" fill="currentColor">
    <path
      fillRule="evenodd"
      clipRule="evenodd"
      d="M12 2C6.477 2 2 6.484 2 12.017c0 4.425 2.865 8.18 6.839 9.504.5.092.682-.217.682-.483 0-.237-.008-.868-.013-1.703-2.782.605-3.369-1.343-3.369-1.343-.454-1.158-1.11-1.466-1.11-1.466-.908-.62.069-.608.069-.608 1.003.07 1.53 1.032 1.53 1.032.892 1.53 2.341 1.088 2.91.832.092-.647.35-1.088.636-1.338-2.22-.253-4.555-1.113-4.555-4.951 0-1.093.39-1.988 1.029-2.688-.103-.253-.446-1.272.098-2.65 0 0 .84-.27 2.75 1.026A9.564 9.564 0 0112 6.844c.85.004 1.705.115 2.504.337 1.909-1.296 2.747-1.027 2.747-1.027.546 1.379.202 2.398.1 2.651.64.7 1.028 1.595 1.028 2.688 0 3.848-2.339 4.695-4.566 4.943.359.309.678.92.678 1.855 0 1.338-.012 2.419-.012 2.747 0 .268.18.58.688.482A10.019 10.019 0 0022 12.017C22 6.484 17.522 2 12 2z"
    />
  </svg>
)

const DEMO_PRESETS = [
  {
    caseId: 'psf__requests-1142',
    label: 'requests-1142',
    report:
      'Uncaught TypeError: Cannot read properties of undefined (reading "subscribe") when dispatching during store creation.\n\nContent-Length header is incorrectly retained when following a 301/302 redirect transforming POST into GET.',
  },
  {
    caseId: 'psf__requests-1376',
    label: 'requests-1376',
    report:
      'TypeError when streaming multipart byte chunks without explicit string decode in prepare_body.',
  },
  {
    caseId: 'psf__requests-1537',
    label: 'requests-1537',
    report:
      'CaseInsensitiveDict raises AttributeError when non-string header keys are provided.',
  },
]

export const InvestigationPanel: React.FC<InvestigationPanelProps> = ({
  repositories,
  activeRepository,
  cases: _cases = [],
  isLoading,
  stages = [],
  onSelectRepo,
  onConnectRepo,
  onIngestRepo: _onIngestRepo,
  onDisconnectRepo: _onDisconnectRepo,
  onSubmit,
  onReset,
  onOpenMcpGuide,
  onOpenDiagnostics,
}) => {
  const [bugSummary, setBugSummary] = useState<string>(
    DEMO_PRESETS[0].report
  )
  const [deepTraceActive, setDeepTraceActive] = useState<boolean>(true)
  const [budget, setBudget] = useState<number>(12000)
  const [selectedCaseId, setSelectedCaseId] = useState<string>('psf__requests-1142')
  const [showRepoDropdown, setShowRepoDropdown] = useState<boolean>(false)
  const [showConnectModal, setShowConnectModal] = useState<boolean>(false)
  const [connectPath, setConnectPath] = useState<string>('')
  const [connectName, setConnectName] = useState<string>('')
  const [connectError, setConnectError] = useState<string | null>(null)
  const [isConnecting, setIsConnecting] = useState<boolean>(false)
  const [lastRunTime, setLastRunTime] = useState<string | null>('2m ago')

  const handleApplyPreset = (preset: typeof DEMO_PRESETS[0]) => {
    setSelectedCaseId(preset.caseId)
    setBugSummary(preset.report)
  }

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (isLoading || !bugSummary.trim() || !activeRepository) return

    const mode: InvestigationMode = deepTraceActive ? 'trace' : 'find'
    const req: InvestigateRequest = {
      case_id: selectedCaseId || undefined,
      repo_id: activeRepository.repo_id,
      repo: activeRepository.name,
      revision: activeRepository.working_revision,
      bug_report: bugSummary.trim(),
      mode,
      strategy: deepTraceActive ? 'graph' : 'lexical',
      budget,
      mock: false,
      execute_repair: true,
      compare_baseline: true,
    }
    setLastRunTime('Just now')
    onSubmit(req)
  }

  const handleConnectSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!connectPath.trim()) return

    setIsConnecting(true)
    setConnectError(null)
    try {
      await onConnectRepo({
        path: connectPath.trim(),
        name: connectName.trim() || undefined,
      })
      setShowConnectModal(false)
      setConnectPath('')
      setConnectName('')
    } catch (err) {
      setConnectError(err instanceof Error ? err.message : 'Failed to connect repository')
    } finally {
      setIsConnecting(false)
    }
  }

  const displayRepoName = activeRepository
    ? activeRepository.repo_id === 'requests'
      ? 'github.com/psf/requests'
      : activeRepository.name
    : 'github.com/psf/requests'

  const displayRevision = activeRepository
    ? `${activeRepository.default_branch} [rev: ${activeRepository.short_sha || '847735'}]`
    : 'main [rev: 847735]'

  return (
    <div className="bg-white rounded-2xl shadow-xs border border-stone-200/80 p-5 flex flex-col h-full overflow-y-auto">
      {/* 1. Header Row: Logo & MCP Pill Badge */}
      <div className="flex items-center justify-between pb-4 border-b border-slate-100">
        <div className="flex items-center gap-2">
          {/* Logo Icon with connected nodes */}
          <div className="text-slate-900">
            <Network className="w-5 h-5 stroke-[2.2]" />
          </div>
          <span className="text-base font-bold text-slate-900 tracking-tight">TraceFix</span>
        </div>

        <div className="flex items-center gap-1.5">
          <button
            type="button"
            onClick={onOpenMcpGuide}
            className="flex items-center gap-1 bg-emerald-50 hover:bg-emerald-100 text-emerald-800 border border-emerald-200 text-[11px] font-medium px-2.5 py-0.5 rounded-full transition-colors cursor-pointer"
            title="Model Context Protocol Server Connected"
          >
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-600 animate-pulse" />
            <span>mcp-server: connected</span>
          </button>

          {onOpenDiagnostics && (
            <button
              type="button"
              onClick={onOpenDiagnostics}
              className="p-1 rounded-md text-slate-400 hover:text-slate-600 hover:bg-slate-100 transition-colors"
              title="Engineering Diagnostics"
            >
              <SlidersHorizontal className="w-3.5 h-3.5" />
            </button>
          )}
        </div>
      </div>

      <form onSubmit={handleSubmit} className="flex-1 flex flex-col pt-4 space-y-4">
        {/* 2. Repository Section */}
        <div className="space-y-1.5">
          <label className="text-xs font-semibold text-slate-700 block">Repository</label>

          {/* Repository Dropdown / Selector */}
          <div className="relative">
            <button
              type="button"
              onClick={() => setShowRepoDropdown(!showRepoDropdown)}
              className="w-full flex items-center justify-between bg-white border border-slate-200 hover:border-slate-300 rounded-xl px-3 py-2 text-xs text-slate-800 transition-colors shadow-2xs cursor-pointer"
            >
              <div className="flex items-center gap-2 truncate">
                <GithubIcon className="w-3.5 h-3.5 text-slate-600 shrink-0" />
                <span className="font-medium truncate">{displayRepoName}</span>
              </div>
              <ChevronDown className="w-3.5 h-3.5 text-slate-400 shrink-0" />
            </button>

            {showRepoDropdown && (
              <div className="absolute top-full left-0 right-0 mt-1 bg-white border border-slate-200 rounded-xl shadow-lg z-30 p-1.5 text-xs">
                <div className="text-[10px] font-semibold text-slate-400 px-2 py-1 uppercase tracking-wider">
                  Available Repositories
                </div>
                {repositories.map((repo) => (
                  <button
                    key={repo.repo_id}
                    type="button"
                    onClick={() => {
                      onSelectRepo(repo.repo_id)
                      setShowRepoDropdown(false)
                    }}
                    className={`w-full text-left px-2.5 py-1.5 rounded-lg flex items-center justify-between transition-colors ${
                      activeRepository?.repo_id === repo.repo_id
                        ? 'bg-blue-50 text-blue-700 font-medium'
                        : 'text-slate-700 hover:bg-slate-50'
                    }`}
                  >
                    <span className="truncate">{repo.name}</span>
                    <span className="text-[10px] font-mono text-slate-400">{repo.short_sha}</span>
                  </button>
                ))}
                <div className="border-t border-slate-100 mt-1 pt-1">
                  <button
                    type="button"
                    onClick={() => {
                      setShowRepoDropdown(false)
                      setShowConnectModal(true)
                    }}
                    className="w-full text-left px-2 py-1.5 rounded-lg text-blue-600 hover:bg-blue-50 font-medium flex items-center gap-1.5"
                  >
                    <Plus className="w-3.5 h-3.5" /> Connect Local Directory...
                  </button>
                </div>
              </div>
            )}
          </div>

          {/* Branch & Revision Display */}
          <div className="w-full flex items-center justify-between bg-white border border-slate-200 rounded-xl px-3 py-2 text-xs text-slate-700 shadow-2xs">
            <div className="flex items-center gap-2 truncate">
              <GitBranch className="w-3.5 h-3.5 text-slate-500 shrink-0" />
              <span className="font-mono text-xs truncate">{displayRevision}</span>
            </div>
            <ChevronDown className="w-3.5 h-3.5 text-slate-400 shrink-0 opacity-60" />
          </div>
        </div>

        {/* 3. Bug Report Input Section */}
        <div className="space-y-1.5">
          <label htmlFor="bug-input" className="text-xs font-semibold text-slate-700 block">
            Bug Report Input
          </label>
          <div className="relative">
            <textarea
              id="bug-input"
              value={bugSummary}
              onChange={(e) => setBugSummary(e.target.value)}
              rows={4}
              placeholder="Paste error trace, reproduction steps, or bug statement..."
              className="w-full bg-white border border-slate-200 rounded-xl p-3 text-xs leading-relaxed text-slate-800 placeholder:text-slate-400 focus:outline-none focus:border-slate-400 resize-none shadow-2xs"
            />
          </div>

          {/* Quick Preset Chips */}
          <div className="flex items-center gap-1.5 pt-0.5 overflow-x-auto">
            <span className="text-[10px] text-slate-400 font-medium shrink-0">Presets:</span>
            {DEMO_PRESETS.map((preset) => (
              <button
                key={preset.caseId}
                type="button"
                onClick={() => handleApplyPreset(preset)}
                className={`text-[10px] px-2 py-0.5 rounded-md font-mono shrink-0 transition-colors ${
                  selectedCaseId === preset.caseId
                    ? 'bg-slate-900 text-white font-medium'
                    : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
                }`}
              >
                {preset.label}
              </button>
            ))}
          </div>
        </div>

        {/* 4. Deep Trace Mode Toggle */}
        <div className="pt-1">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold text-slate-800">Deep Trace" mode</span>
            {/* iOS-style pill switch */}
            <button
              type="button"
              role="switch"
              aria-checked={deepTraceActive}
              onClick={() => setDeepTraceActive(!deepTraceActive)}
              className={`w-9 h-5 rounded-full transition-colors relative cursor-pointer ${
                deepTraceActive ? 'bg-[#0b192c]' : 'bg-slate-300'
              }`}
            >
              <span
                className={`w-3.5 h-3.5 rounded-full bg-white absolute top-[3px] transition-transform shadow-xs ${
                  deepTraceActive ? 'left-[19px]' : 'left-[3px]'
                }`}
              />
            </button>
          </div>
          <p className="text-[11px] text-slate-400 mt-0.5">
            Realistic. 1 toggle for &apos;trace&apos; mode.
          </p>
        </div>

        {/* 5. Context Budget Slider */}
        <div className="space-y-1 pt-1">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold text-slate-800">Context Budget</span>
          </div>
          <div className="text-xs text-slate-600 font-medium">
            {budget / 1000}k tokens ({budget <= 4000 ? 'Compact' : 'Expanded'})
          </div>

          <div className="pt-1">
            <input
              type="range"
              min={2000}
              max={16000}
              step={2000}
              value={budget}
              onChange={(e) => setBudget(Number(e.target.value))}
              className="w-full cursor-pointer accent-[#0b192c]"
            />
          </div>
          <p className="text-[11px] text-slate-400 leading-tight pt-1">
            Tiny explanation aids is to ensure the focus limit of in focus context.
          </p>
        </div>

        {/* 6. Execution Stages Progress (if active or run) */}
        {stages && stages.length > 0 && (
          <div className="pt-2 border-t border-slate-100 space-y-1">
            {stages.map((stage) => (
              <div
                key={stage.stage_id}
                className="flex items-center justify-between text-[11px] py-0.5"
              >
                <span className="text-slate-600 truncate max-w-[170px]" title={stage.detail}>
                  {stage.name}
                </span>
                <span
                  className={`text-[9px] px-1.5 py-0.2 rounded font-medium ${
                    stage.status === 'completed'
                      ? 'bg-emerald-50 text-emerald-700'
                      : stage.status === 'running'
                      ? 'bg-blue-50 text-blue-700 animate-pulse'
                      : 'bg-slate-100 text-slate-400'
                  }`}
                >
                  {stage.status}
                </span>
              </div>
            ))}
          </div>
        )}

        {/* 7. Action Button & Footer Info */}
        <div className="pt-3 mt-auto space-y-2">
          <button
            type="submit"
            disabled={isLoading || !bugSummary.trim()}
            className="w-full bg-[#0b192c] hover:bg-[#1e293b] text-white font-semibold py-2.5 px-4 rounded-xl text-xs transition-colors shadow-xs flex items-center justify-center gap-2 cursor-pointer disabled:opacity-60"
          >
            {isLoading ? (
              <>
                <div className="w-3.5 h-3.5 border-2 border-white border-t-transparent rounded-full animate-spin" />
                <span>Investigating...</span>
              </>
            ) : (
              <>
                <Play className="w-3.5 h-3.5 fill-white" />
                <span>Investigate Bug</span>
              </>
            )}
          </button>

          <div className="flex items-center justify-between text-[11px] text-slate-400 px-1">
            <span>Last run: {lastRunTime || 'Ready'}</span>
            <button
              type="button"
              onClick={() => {
                setBugSummary('')
                setSelectedCaseId('')
                onReset()
              }}
              className="text-slate-400 hover:text-slate-600 flex items-center gap-1 cursor-pointer"
              title="Reset"
            >
              <RotateCcw className="w-3 h-3" /> Reset
            </button>
          </div>
        </div>
      </form>

      {/* Connect Local Repository Modal */}
      {showConnectModal && (
        <div className="fixed inset-0 bg-slate-900/40 backdrop-blur-xs flex items-center justify-center p-4 z-50">
          <div className="bg-white rounded-2xl shadow-xl border border-slate-200 max-w-md w-full p-5 space-y-4">
            <div className="flex items-center justify-between pb-2 border-b border-slate-100">
              <h3 className="text-sm font-semibold text-slate-800">Connect Local Repository</h3>
              <button
                type="button"
                onClick={() => setShowConnectModal(false)}
                className="text-slate-400 hover:text-slate-600"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <form onSubmit={handleConnectSubmit} className="space-y-3">
              <div>
                <label htmlFor="repo-path" className="text-xs font-semibold text-slate-700 block mb-1">
                  Local Directory Path
                </label>
                <input
                  id="repo-path"
                  type="text"
                  placeholder="/Users/.../repo or ./data/repos/requests"
                  value={connectPath}
                  onChange={(e) => setConnectPath(e.target.value)}
                  className="w-full border border-slate-200 rounded-xl px-3 py-2 text-xs font-mono text-slate-800 focus:outline-none focus:border-slate-400"
                  required
                />
              </div>

              <div>
                <label htmlFor="repo-name" className="text-xs font-semibold text-slate-700 block mb-1">
                  Display Name (Optional)
                </label>
                <input
                  id="repo-name"
                  type="text"
                  placeholder="Defaults to directory name"
                  value={connectName}
                  onChange={(e) => setConnectName(e.target.value)}
                  className="w-full border border-slate-200 rounded-xl px-3 py-2 text-xs text-slate-800 focus:outline-none focus:border-slate-400"
                />
              </div>

              {connectError && (
                <div className="p-2 bg-rose-50 text-rose-700 border border-rose-200 rounded-lg text-xs">
                  {connectError}
                </div>
              )}

              <div className="flex justify-end gap-2 pt-2">
                <button
                  type="button"
                  onClick={() => setShowConnectModal(false)}
                  className="px-3 py-1.5 text-xs text-slate-600 hover:bg-slate-100 rounded-lg"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={isConnecting || !connectPath.trim()}
                  className="px-4 py-1.5 text-xs font-semibold bg-[#0b192c] text-white rounded-lg hover:bg-slate-800"
                >
                  {isConnecting ? 'Validating...' : 'Connect'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  )
}
