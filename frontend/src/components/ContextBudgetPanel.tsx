import React, { useState } from 'react'
import {
  ArrowDownRight,
  ArrowUpRight,
  BarChart2,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Info,
  Sliders,
  XCircle,
} from 'lucide-react'
import type { BaselineComparisonResponse, ContextItem } from '../types'

interface ContextBudgetPanelProps {
  budget?: {
    budget_limit: number
    tokens_used: number
    utilization: number
    included_count: number
    excluded_count: number
    counting_method?: string
  }
  items?: ContextItem[]
  baselineComparison?: BaselineComparisonResponse | null
}

export const ContextBudgetPanel: React.FC<ContextBudgetPanelProps> = ({
  budget,
  items = [],
  baselineComparison,
}) => {
  const [isCollapsed, setIsCollapsed] = useState(false)

  if (!budget || !items || items.length === 0) {
    return (
      <div className="panel-card" style={{ marginBottom: 16 }}>
        <div className="panel-header">
          <span className="panel-title">Context Budget Accounting</span>
        </div>
        <div className="panel-body empty-placeholder">
          Context selection details will appear here following retrieval.
        </div>
      </div>
    )
  }

  const pct = Math.min(100, budget.utilization * 100)
  const barClass = pct > 95 ? 'danger' : pct > 80 ? 'warning' : ''
  const isHeuristic = budget.counting_method?.includes('heuristic') ?? true

  return (
    <div className="panel-card" style={{ marginBottom: 16 }}>
      <div
        className="panel-header"
        style={{ cursor: 'pointer', userSelect: 'none' }}
        onClick={() => setIsCollapsed(!isCollapsed)}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          {isCollapsed ? <ChevronRight size={14} /> : <ChevronDown size={14} />}
          <Sliders size={14} color="var(--accent-primary)" />
          <span className="panel-title">Context Selection &amp; Token Budget Accounting</span>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span className="badge badge-neutral mono" style={{ fontSize: 11 }}>
            {budget.tokens_used.toLocaleString()} / {budget.budget_limit.toLocaleString()} tokens
          </span>
          <span className="badge badge-blue mono" style={{ fontSize: 10 }}>
            {isHeuristic ? 'Estimate (Char÷4)' : 'Exact TikToken'}
          </span>
        </div>
      </div>

      {!isCollapsed && (
        <div className="panel-body">
          {/* Progress Bar & Summary */}
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, marginBottom: 4 }}>
            <span style={{ color: 'var(--text-secondary)' }}>
              Utilization: <strong>{pct.toFixed(1)}%</strong> ({budget.tokens_used} of {budget.budget_limit} tokens)
            </span>
            <span style={{ color: 'var(--text-secondary)' }}>
              <strong>{budget.included_count}</strong> selected, <strong>{budget.excluded_count}</strong> excluded
            </span>
          </div>

          <div className="budget-bar-bg" style={{ marginBottom: 14 }}>
            <div className={`budget-bar-fill ${barClass}`} style={{ width: `${pct}%` }} />
          </div>

          {/* Optional Live Baseline Comparison (Graph vs Lexical) */}
          {baselineComparison && (
            <div
              style={{
                marginBottom: 14,
                padding: '10px 12px',
                backgroundColor: 'var(--bg-secondary)',
                borderRadius: 'var(--radius-sm)',
                border: '1px solid var(--border-default)',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
                <span style={{ fontSize: 12, fontWeight: 600, display: 'flex', alignItems: 'center', gap: 6 }}>
                  <BarChart2 size={13} color="var(--accent-primary)" />
                  Live Retrieval Token Diagnostics (Same Query &amp; Corpus)
                </span>
                {baselineComparison.reduction_pct !== null && baselineComparison.reduction_pct !== undefined && (
                  <span
                    className={`badge ${baselineComparison.token_delta >= 0 ? 'badge-green' : 'badge-yellow'} mono`}
                    style={{ display: 'inline-flex', alignItems: 'center', gap: 3 }}
                  >
                    {baselineComparison.token_delta >= 0 ? <ArrowDownRight size={11} /> : <ArrowUpRight size={11} />}
                    {baselineComparison.token_delta >= 0
                      ? `${baselineComparison.reduction_pct}% Context Token Reduction`
                      : `${Math.abs(baselineComparison.reduction_pct)}% More Context Tokens`}
                  </span>
                )}
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 10, fontSize: 11 }}>
                <div>
                  <span style={{ color: 'var(--text-muted)' }}>Lexical Baseline:</span>
                  <div className="mono" style={{ fontWeight: 600 }}>
                    {baselineComparison.baseline_tokens.toLocaleString()} tokens ({baselineComparison.baseline_items_count} items)
                  </div>
                </div>
                <div>
                  <span style={{ color: 'var(--text-muted)' }}>Graph-Guided:</span>
                  <div className="mono" style={{ fontWeight: 600 }}>
                    {baselineComparison.evaluated_tokens.toLocaleString()} tokens ({baselineComparison.evaluated_items_count} items)
                  </div>
                </div>
                <div>
                  <span style={{ color: 'var(--text-muted)' }}>Token Delta:</span>
                  <div className="mono" style={{ fontWeight: 600 }}>
                    {baselineComparison.token_delta >= 0 ? `-${baselineComparison.token_delta}` : `+${Math.abs(baselineComparison.token_delta)}`} tokens
                  </div>
                </div>
              </div>

              <div style={{ marginTop: 8, fontSize: 10, color: 'var(--text-muted)', display: 'flex', alignItems: 'center', gap: 4 }}>
                <Info size={11} />
                <span>
                  Measurements reflect selected prompt context tokens on identical inputs. Actual model inference tokens depend on completions and runtime retries.
                </span>
              </div>
            </div>
          )}

          {/* Selected / Excluded breakdown table */}
          <div className="table-wrapper">
            <table className="data-table">
              <thead>
                <tr>
                  <th style={{ width: 70 }}>Decision</th>
                  <th>Target Symbol</th>
                  <th>File Path</th>
                  <th style={{ width: 65 }}>Tokens</th>
                  <th>Reason / Strat</th>
                </tr>
              </thead>
              <tbody>
                {items.slice(0, 15).map((it) => (
                  <tr key={it.candidate_id}>
                    <td>
                      {it.included ? (
                        <span
                          className="badge badge-green mono"
                          style={{ display: 'inline-flex', gap: 3, alignItems: 'center', fontSize: 10 }}
                        >
                          <CheckCircle2 size={10} /> IN
                        </span>
                      ) : (
                        <span
                          className="badge badge-red mono"
                          style={{ display: 'inline-flex', gap: 3, alignItems: 'center', fontSize: 10 }}
                        >
                          <XCircle size={10} /> OUT
                        </span>
                      )}
                    </td>
                    <td className="mono" style={{ fontWeight: 600, fontSize: 11 }}>
                      {it.symbol || '<file root>'}
                    </td>
                    <td className="mono" style={{ color: 'var(--text-secondary)', fontSize: 11 }}>
                      {it.file_path}
                    </td>
                    <td className="mono" style={{ fontSize: 11 }}>{it.token_cost}</td>
                    <td
                      style={{
                        color: it.included ? 'var(--text-secondary)' : 'var(--status-danger-text)',
                        fontSize: 11,
                      }}
                    >
                      {it.included ? `strategy: ${it.strategy}` : (it.exclusion_reason || 'Excluded by budget')}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}
