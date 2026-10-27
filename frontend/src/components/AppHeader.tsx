import React from 'react'
import { Terminal, Activity, GitBranch } from 'lucide-react'
import type { HealthResponse, RepositorySummary } from '../types'

interface AppHeaderProps {
  health: HealthResponse | null
  healthError: string | null
  activeRepo: RepositorySummary | null
  onOpenMcpGuide: () => void
  onOpenDiagnostics: () => void
}

export const AppHeader: React.FC<AppHeaderProps> = ({
  health,
  healthError,
  activeRepo,
  onOpenMcpGuide,
  onOpenDiagnostics,
}) => {
  return (
    <header className="h-14 px-5 bg-white/95 backdrop-blur-xs border-b border-slate-200/80 flex items-center justify-between sticky top-0 z-30">
      {/* Brand & Active Repository */}
      <div className="flex items-center gap-4">
        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-lg bg-blue-600 flex items-center justify-center text-white shadow-xs">
            <Terminal className="w-4 h-4" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <span className="font-bold text-slate-900 tracking-tight text-sm">TRACEFIX</span>
              <span className="text-[10px] font-mono font-medium px-1.5 py-0.2 rounded bg-blue-50 text-blue-700 border border-blue-200">
                v0.0.1
              </span>
            </div>
            <p className="text-[11px] text-slate-500 hidden sm:block">
              Graph-Native Code Investigation & Verified Repair
            </p>
          </div>
        </div>

        {activeRepo && (
          <div className="hidden md:flex items-center gap-2 pl-4 border-l border-slate-200 text-xs">
            <span className="flex items-center gap-1 font-medium text-slate-700">
              <GitBranch className="w-3.5 h-3.5 text-slate-400" />
              {activeRepo.name}
            </span>
            <span className="font-mono text-[11px] text-slate-500 bg-slate-100 px-1.5 py-0.5 rounded">
              {activeRepo.default_branch}:{activeRepo.short_sha}
            </span>
          </div>
        )}
      </div>

      {/* Actions & Health Badges */}
      <div className="flex items-center gap-2.5">
        {/* Backend / FalkorDB Status */}
        {health ? (
          <div
            className={`flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-medium border ${
              health.falkordb_connected
                ? 'bg-emerald-50 text-emerald-700 border-emerald-200'
                : 'bg-amber-50 text-amber-700 border-amber-200'
            }`}
            title={`Backend: ${health.status} | FalkorDB: ${
              health.falkordb_connected ? 'Connected' : 'Offline (using Disk Snapshots)'
            }`}
          >
            <span
              className={`w-1.5 h-1.5 rounded-full ${
                health.falkordb_connected ? 'bg-emerald-500' : 'bg-amber-500'
              }`}
            />
            <span className="hidden sm:inline">
              {health.falkordb_connected ? 'Live FalkorDB' : 'Disk AST Snapshot'}
            </span>
          </div>
        ) : healthError ? (
          <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-medium bg-rose-50 text-rose-700 border border-rose-200">
            <span className="w-1.5 h-1.5 rounded-full bg-rose-500" />
            <span>Backend Disconnected</span>
          </div>
        ) : null}

        {/* MCP Guide Button */}
        <button
          type="button"
          onClick={onOpenMcpGuide}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium text-slate-700 bg-slate-100 hover:bg-slate-200/80 transition-colors"
          title="Connect Claude Desktop, Cursor, or Antigravity via MCP"
        >
          <Terminal className="w-3.5 h-3.5 text-blue-600" />
          <span>MCP Setup</span>
        </button>

        {/* Diagnostics & Benchmarks Button */}
        <button
          type="button"
          onClick={onOpenDiagnostics}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium text-slate-700 bg-slate-100 hover:bg-slate-200/80 transition-colors"
          title="View Historical Benchmarks & Incident Memory"
        >
          <Activity className="w-3.5 h-3.5 text-purple-600" />
          <span className="hidden sm:inline">Diagnostics</span>
        </button>
      </div>
    </header>
  )
}
