import React, { useState } from 'react'
import {
  AlertTriangle,
  Check,
  Filter,
  GitBranch,
  Layers,
} from 'lucide-react'
import type { RetrievalItem } from '../types'

interface EvidenceExplorerProps {
  items: RetrievalItem[]
  strategyUsed?: string
  fallbackOccurred?: boolean
  fallbackReason?: string
  onInspectNode?: (symbol: string) => void
}

export const EvidenceExplorer: React.FC<EvidenceExplorerProps> = ({
  items,
  strategyUsed,
  fallbackOccurred,
  fallbackReason,
  onInspectNode,
}) => {
  const [filterText, setFilterText] = useState('')
  const [showOnlyHits, setShowOnlyHits] = useState(false)

  if (!items || items.length === 0) {
    return (
      <div className="panel-card" style={{ marginBottom: 16 }}>
        <div className="panel-header">
          <span className="panel-title">Retrieved Evidence &amp; Localization</span>
        </div>
        <div className="panel-body empty-placeholder">
          No retrieval results yet. Run an investigation to view ranked evidence.
        </div>
      </div>
    )
  }

  const filteredItems = items.filter((it) => {
    if (showOnlyHits && !it.is_ground_truth_function && !it.is_ground_truth_file) {
      return false
    }
    if (!filterText) return true
    const q = filterText.toLowerCase()
    return (
      it.file.toLowerCase().includes(q) ||
      it.symbol.toLowerCase().includes(q) ||
      it.strategy.toLowerCase().includes(q)
    )
  })

  const functionHits = items.filter((it) => it.is_ground_truth_function).length
  const fileHits = items.filter((it) => it.is_ground_truth_file).length

  return (
    <div className="panel-card" style={{ marginBottom: 16 }}>
      <div className="panel-header">
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <span className="panel-title" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <Layers size={14} color="var(--accent-primary)" />
            Retrieved Evidence ({items.length} Candidates)
          </span>
          {strategyUsed && (
            <span className="badge badge-neutral mono" style={{ fontSize: 11 }}>
              strategy: {strategyUsed}
            </span>
          )}
        </div>

        {(functionHits > 0 || fileHits > 0) && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span
              className={`badge ${functionHits > 0 ? 'badge-green' : 'badge-neutral'}`}
              title="Function-level matches"
            >
              Fn Hits: {functionHits} / {items.length}
            </span>
            <span
              className={`badge ${fileHits > 0 ? 'badge-blue' : 'badge-neutral'}`}
              title="File-level matches"
            >
              File Hits: {fileHits} / {items.length}
            </span>
          </div>
        )}
      </div>

      {fallbackOccurred && (
        <div
          style={{
            padding: '8px 12px',
            backgroundColor: 'var(--status-warning-bg)',
            borderBottom: '1px solid rgba(210, 153, 34, 0.4)',
            color: 'var(--status-warning-text)',
            fontSize: 11,
            display: 'flex',
            alignItems: 'center',
            gap: 6,
          }}
        >
          <AlertTriangle size={13} style={{ flexShrink: 0 }} />
          <span>
            <strong>Fallback Notice:</strong> {fallbackReason || 'Graph retrieval was unavailable; system fell back to lexical BM25.'}
          </span>
        </div>
      )}

      {/* Filter Bar */}
      <div
        style={{
          padding: '8px 14px',
          borderBottom: '1px solid var(--border-default)',
          display: 'flex',
          gap: 10,
        }}
      >
        <div style={{ position: 'relative', flex: 1 }}>
          <input
            type="text"
            className="form-input"
            style={{ paddingLeft: 26, fontSize: 11 }}
            placeholder="Filter by file, symbol, or provenance..."
            value={filterText}
            onChange={(e) => setFilterText(e.target.value)}
          />
          <Filter
            size={12}
            color="var(--text-muted)"
            style={{ position: 'absolute', left: 8, top: 9 }}
          />
        </div>
        {(functionHits > 0 || fileHits > 0) && (
          <button
            type="button"
            className={`btn btn-sm ${showOnlyHits ? 'btn-primary' : 'btn-secondary'}`}
            onClick={() => setShowOnlyHits(!showOnlyHits)}
          >
            {showOnlyHits && <Check size={12} />} Only GT Hits
          </button>
        )}
      </div>

      {/* Candidates Table */}
      <div className="table-wrapper">
        <table className="data-table">
          <thead>
            <tr>
              <th style={{ width: 45 }}>Rank</th>
              <th style={{ width: 55 }}>Score</th>
              <th>Target Symbol &amp; File</th>
              <th style={{ width: 85 }}>Line Range</th>
              <th style={{ width: 110 }}>Provenance</th>
              <th style={{ width: 70 }}>Inspect</th>
            </tr>
          </thead>
          <tbody>
            {filteredItems.map((it) => (
              <tr key={it.evidence_id}>
                <td className="mono" style={{ color: 'var(--text-muted)', fontSize: 11 }}>
                  #{it.rank}
                </td>
                <td className="mono" style={{ fontWeight: 600, fontSize: 11 }}>
                  {it.score.toFixed(3)}
                </td>
                <td>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
                    <span className="mono" style={{ fontWeight: 600, color: 'var(--text-primary)', fontSize: 12 }}>
                      {it.symbol || '<file root>'}
                    </span>
                    {it.is_ground_truth_function && (
                      <span className="badge badge-green" style={{ fontSize: 9 }}>MATCH</span>
                    )}
                  </div>
                  <div className="mono" style={{ color: 'var(--text-secondary)', fontSize: 11 }}>
                    {it.file}
                  </div>
                </td>
                <td className="mono" style={{ fontSize: 11, color: 'var(--text-secondary)' }}>
                  {it.lines ? `L${it.lines[0]}–L${it.lines[1]}` : '—'}
                </td>
                <td>
                  <span
                    className={`badge ${it.provenance === 'observed' ? 'badge-blue' : 'badge-neutral'} mono`}
                    style={{ fontSize: 10 }}
                  >
                    {it.provenance}
                  </span>
                </td>
                <td>
                  {onInspectNode && it.symbol && (
                    <button
                      type="button"
                      className="btn btn-sm btn-secondary"
                      style={{ padding: '2px 6px', fontSize: 10 }}
                      onClick={() => onInspectNode(it.symbol)}
                      title="Inspect graph neighborhood for this symbol"
                    >
                      <GitBranch size={10} /> View
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
