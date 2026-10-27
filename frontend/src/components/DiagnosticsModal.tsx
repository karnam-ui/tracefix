import React, { useState } from 'react'
import { Award, Database, Activity, X } from 'lucide-react'
import { EvaluationBenchmarksView } from './EvaluationBenchmarksView'
import { IncidentMemoryView } from './IncidentMemoryView'
import type { HealthResponse } from '../types'

interface DiagnosticsModalProps {
  isOpen: boolean
  onClose: () => void
  health?: HealthResponse | null
}

export const DiagnosticsModal: React.FC<DiagnosticsModalProps> = ({ isOpen, onClose, health }) => {
  const [activeTab, setActiveTab] = useState<'benchmarks' | 'memory' | 'system'>('benchmarks')

  if (!isOpen) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 backdrop-blur-xs p-4">
      <div className="bg-white rounded-2xl shadow-xl border border-slate-200 w-full max-w-4xl h-[85vh] flex flex-col overflow-hidden animate-in fade-in zoom-in-95 duration-150">
        {/* Header */}
        <div className="px-6 py-4 border-b border-slate-100 flex items-center justify-between bg-slate-50/50">
          <div className="flex items-center gap-2.5">
            <div className="p-1.5 rounded-lg bg-indigo-50 text-indigo-600">
              <Activity className="w-5 h-5" />
            </div>
            <div>
              <h3 className="text-base font-semibold text-slate-900">Engineering Diagnostics & Benchmarks</h3>
              <p className="text-xs text-slate-500">Historical experiment reports, incident memory records, and system health</p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="text-slate-400 hover:text-slate-600 p-1 rounded-lg hover:bg-slate-100 transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Tab Navigation */}
        <div className="px-6 pt-2 border-b border-slate-200 flex gap-6 text-xs font-medium">
          <button
            type="button"
            onClick={() => setActiveTab('benchmarks')}
            className={`pb-2.5 flex items-center gap-1.5 transition-colors relative ${
              activeTab === 'benchmarks'
                ? 'text-blue-600 border-b-2 border-blue-600 font-semibold'
                : 'text-slate-500 hover:text-slate-700'
            }`}
          >
            <Award className="w-4 h-4 text-amber-500" />
            Evaluation Benchmarks
          </button>

          <button
            type="button"
            onClick={() => setActiveTab('memory')}
            className={`pb-2.5 flex items-center gap-1.5 transition-colors relative ${
              activeTab === 'memory'
                ? 'text-blue-600 border-b-2 border-blue-600 font-semibold'
                : 'text-slate-500 hover:text-slate-700'
            }`}
          >
            <Database className="w-4 h-4 text-purple-500" />
            Incident Memory Store
          </button>

          <button
            type="button"
            onClick={() => setActiveTab('system')}
            className={`pb-2.5 flex items-center gap-1.5 transition-colors relative ${
              activeTab === 'system'
                ? 'text-blue-600 border-b-2 border-blue-600 font-semibold'
                : 'text-slate-500 hover:text-slate-700'
            }`}
          >
            <Activity className="w-4 h-4 text-emerald-500" />
            System Health
          </button>
        </div>

        {/* Modal Body */}
        <div className="flex-1 overflow-y-auto p-6 bg-slate-50/30">
          {activeTab === 'benchmarks' && <EvaluationBenchmarksView />}

          {activeTab === 'memory' && <IncidentMemoryView />}

          {activeTab === 'system' && (
            <div className="space-y-4 max-w-xl mx-auto py-4">
              <div className="p-4 bg-white border border-slate-200 rounded-xl space-y-3 shadow-xs">
                <h4 className="text-sm font-semibold text-slate-800 border-b border-slate-100 pb-2">
                  TraceFix Engine Health
                </h4>
                <div className="grid grid-cols-2 gap-3 text-xs">
                  <div>
                    <span className="text-slate-400 block">Overall Status</span>
                    <span className="font-semibold text-slate-800">{health?.status || 'Unknown'}</span>
                  </div>
                  <div>
                    <span className="text-slate-400 block">Backend Version</span>
                    <span className="font-mono text-slate-800">{health?.version || '0.0.1'}</span>
                  </div>
                  <div>
                    <span className="text-slate-400 block">FalkorDB Connection</span>
                    <span
                      className={`font-semibold ${
                        health?.falkordb_connected ? 'text-emerald-600' : 'text-amber-600'
                      }`}
                    >
                      {health?.falkordb_connected ? 'Connected (localhost:6379)' : 'Offline (Using Disk AST Snapshots)'}
                    </span>
                  </div>
                  <div>
                    <span className="text-slate-400 block">Connected Repositories</span>
                    <span className="font-semibold text-slate-800">{health?.connected_repos_count ?? 1}</span>
                  </div>
                  <div>
                    <span className="text-slate-400 block">SWE-bench Test Cases</span>
                    <span className="font-semibold text-slate-800">{health?.active_cases_count ?? 0}</span>
                  </div>
                  <div>
                    <span className="text-slate-400 block">Persisted Graph Snapshots</span>
                    <span className="font-semibold text-slate-800">{health?.persisted_graphs_count ?? 0}</span>
                  </div>
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="px-6 py-3 bg-slate-50 border-t border-slate-100 flex items-center justify-end">
          <button
            type="button"
            onClick={onClose}
            className="px-4 py-1.5 bg-slate-800 hover:bg-slate-900 text-white text-xs font-medium rounded-lg transition-colors"
          >
            Close
          </button>
        </div>
      </div>
    </div>
  )
}

