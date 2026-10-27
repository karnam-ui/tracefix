import React, { useState } from 'react'
import {
  Compass,
  Layers,
  Play,
  RotateCcw,
  Search,
  Sliders,
  Wrench,
} from 'lucide-react'
import type { CaseSummary, InvestigateRequest, InvestigationMode, RepositorySummary } from '../types'

interface BugInvestigationFormProps {
  activeRepository: RepositorySummary | null
  cases: CaseSummary[]
  isLoading: boolean
  onSubmit: (req: InvestigateRequest) => void
  onReset: () => void
}

export const BugInvestigationForm: React.FC<BugInvestigationFormProps> = ({
  activeRepository,
  cases,
  isLoading,
  onSubmit,
  onReset,
}) => {
  const [bugSummary, setBugSummary] = useState<string>('')
  const [mode, setMode] = useState<InvestigationMode>('trace')
  const [budget, setBudget] = useState<number>(4000)
  const [compareBaseline, setCompareBaseline] = useState<boolean>(false)
  const [showBenchmarkPresets, setShowBenchmarkPresets] = useState<boolean>(false)
  const [selectedCaseId, setSelectedCaseId] = useState<string>('')

  const handleSelectPreset = (caseId: string) => {
    setSelectedCaseId(caseId)
    if (!caseId) return
    const found = cases.find((c) => c.case_id === caseId)
    if (found) {
      setBugSummary(found.bug_report_preview)
    }
  }

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (isLoading || !bugSummary.trim() || !activeRepository) return

    const req: InvestigateRequest = {
      case_id: selectedCaseId || undefined,
      repo_id: activeRepository.repo_id,
      repo: activeRepository.name,
      revision: activeRepository.working_revision,
      bug_report: bugSummary.trim(),
      mode,
      strategy: mode === 'find' ? 'lexical' : 'graph',
      budget,
      mock: false,
      execute_repair: mode === 'repair',
      compare_baseline: compareBaseline,
    }
    onSubmit(req)
  }

  const getActionLabel = () => {
    switch (mode) {
      case 'trace':
        return 'Trace Code Relationships'
      case 'find':
        return 'Find Relevant Code & Symbols'
      case 'snippets':
        return 'Retrieve Bounded Snippets'
      case 'repair':
        return 'Trace & Propose Verified Fix'
    }
  }

  const getActionIcon = () => {
    switch (mode) {
      case 'trace':
        return <Compass size={14} />
      case 'find':
        return <Search size={14} />
      case 'snippets':
        return <Layers size={14} />
      case 'repair':
        return <Wrench size={14} />
    }
  }

  const isRepoReady = Boolean(activeRepository)

  return (
    <div className="panel-card" style={{ marginBottom: 16 }}>
      <div className="panel-header">
        <span className="panel-title" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <Search size={14} color="var(--accent-primary)" />
          Bug Investigation & Retrieval
        </span>
        <button
          type="button"
          className="btn btn-sm btn-secondary"
          onClick={() => setShowBenchmarkPresets(!showBenchmarkPresets)}
          title="Toggle frozen benchmark test cases (SWE-bench / A6c pilot)"
        >
          {showBenchmarkPresets ? 'Hide Benchmarks' : 'Load Benchmark Case...'}
        </button>
      </div>

      <form onSubmit={handleSubmit} className="panel-body">
        {/* Optional Benchmark Picker for research diagnostics */}
        {showBenchmarkPresets && (
          <div
            style={{
              padding: 10,
              backgroundColor: 'var(--bg-secondary)',
              borderRadius: 'var(--radius-sm)',
              border: '1px solid var(--border-default)',
              marginBottom: 14,
            }}
          >
            <label className="form-label" htmlFor="benchmark-select" style={{ fontSize: 11 }}>
              Select Frozen Evaluation Bug Case (Optional Diagnostic)
            </label>
            <select
              id="benchmark-select"
              className="form-select mono"
              style={{ fontSize: 11 }}
              value={selectedCaseId}
              onChange={(e) => handleSelectPreset(e.target.value)}
            >
              <option value="">-- Custom bug report (default) --</option>
              <optgroup label="Frozen Pilot Subset (A6c)">
                <option value="psf__requests-1142">psf__requests-1142 (Content-length on redirect)</option>
                <option value="psf__requests-1376">psf__requests-1376 (Multipart byte payload)</option>
                <option value="psf__requests-1537">psf__requests-1537 (Basename file handling)</option>
                <option value="psf__requests-1724">psf__requests-1724 (Unicode url handling)</option>
                <option value="psf__requests-1766">psf__requests-1766 (Session quota error)</option>
              </optgroup>
            </select>
          </div>
        )}

        {/* Bug Report Textarea */}
        <div className="form-group">
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
            <label className="form-label" htmlFor="bug-report-text">
              Bug Report / Issue Statement <span style={{ color: 'var(--status-danger-text)' }}>*</span>
            </label>
            {bugSummary && (
              <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                {bugSummary.length} chars
              </span>
            )}
          </div>
          <textarea
            id="bug-report-text"
            className="form-textarea mono"
            style={{ minHeight: 110, fontSize: 12, lineHeight: 1.5 }}
            placeholder="Describe the bug, paste stack trace, error messages, or reproduction steps..."
            value={bugSummary}
            onChange={(e) => setBugSummary(e.target.value)}
            required
            disabled={isLoading}
          />
        </div>

        {/* Investigation Modes Selection */}
        <div className="form-group">
          <label className="form-label" style={{ marginBottom: 6 }}>
            Investigation Mode
          </label>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
            <button
              type="button"
              className={`btn btn-sm ${mode === 'trace' ? 'btn-primary' : 'btn-secondary'}`}
              style={{ justifyContent: 'flex-start', padding: '8px 10px', height: 'auto', textAlign: 'left' }}
              onClick={() => setMode('trace')}
            >
              <Compass size={14} style={{ flexShrink: 0, marginTop: 2 }} />
              <div>
                <div style={{ fontWeight: 600 }}>Mode A: Trace</div>
                <div style={{ fontSize: 10, color: mode === 'trace' ? '#fff' : 'var(--text-muted)', fontWeight: 400 }}>
                  Graph-guided relationships &amp; call paths
                </div>
              </div>
            </button>

            <button
              type="button"
              className={`btn btn-sm ${mode === 'find' ? 'btn-primary' : 'btn-secondary'}`}
              style={{ justifyContent: 'flex-start', padding: '8px 10px', height: 'auto', textAlign: 'left' }}
              onClick={() => setMode('find')}
            >
              <Search size={14} style={{ flexShrink: 0, marginTop: 2 }} />
              <div>
                <div style={{ fontWeight: 600 }}>Mode B: Find</div>
                <div style={{ fontSize: 10, color: mode === 'find' ? '#fff' : 'var(--text-muted)', fontWeight: 400 }}>
                  Lexical search for symbols &amp; files
                </div>
              </div>
            </button>

            <button
              type="button"
              className={`btn btn-sm ${mode === 'snippets' ? 'btn-primary' : 'btn-secondary'}`}
              style={{ justifyContent: 'flex-start', padding: '8px 10px', height: 'auto', textAlign: 'left' }}
              onClick={() => setMode('snippets')}
            >
              <Layers size={14} style={{ flexShrink: 0, marginTop: 2 }} />
              <div>
                <div style={{ fontWeight: 600 }}>Mode C: Snippets</div>
                <div style={{ fontSize: 10, color: mode === 'snippets' ? '#fff' : 'var(--text-muted)', fontWeight: 400 }}>
                  Bounded code fragments &amp; lines
                </div>
              </div>
            </button>

            <button
              type="button"
              className={`btn btn-sm ${mode === 'repair' ? 'btn-primary' : 'btn-secondary'}`}
              style={{ justifyContent: 'flex-start', padding: '8px 10px', height: 'auto', textAlign: 'left' }}
              onClick={() => setMode('repair')}
            >
              <Wrench size={14} style={{ flexShrink: 0, marginTop: 2 }} />
              <div>
                <div style={{ fontWeight: 600 }}>Mode D: Trace &amp; Fix</div>
                <div style={{ fontSize: 10, color: mode === 'repair' ? '#fff' : 'var(--text-muted)', fontWeight: 400 }}>
                  Investigate + propose &amp; verify patch
                </div>
              </div>
            </button>
          </div>
        </div>

        {/* Context Budget & Baseline Diagnostic Controls */}
        <div style={{ display: 'flex', gap: 14, alignItems: 'center', marginBottom: 14, flexWrap: 'wrap' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <Sliders size={13} color="var(--text-muted)" />
            <span className="form-label" style={{ margin: 0, fontSize: 11 }}>
              Context Budget:
            </span>
            <select
              className="form-select mono"
              style={{ width: 'auto', padding: '3px 8px', fontSize: 11 }}
              value={budget}
              onChange={(e) => setBudget(Number(e.target.value))}
            >
              <option value={2000}>2,000 tokens</option>
              <option value={4000}>4,000 tokens (Standard)</option>
              <option value={8000}>8,000 tokens (Extended)</option>
            </select>
          </div>

          <label
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: 6,
              fontSize: 11,
              color: 'var(--text-secondary)',
              cursor: 'pointer',
              userSelect: 'none',
            }}
          >
            <input
              type="checkbox"
              checked={compareBaseline}
              onChange={(e) => setCompareBaseline(e.target.checked)}
            />
            Run Lexical Baseline Comparison
          </label>
        </div>

        {/* Action Buttons */}
        <div style={{ display: 'flex', gap: 10 }}>
          <button
            type="submit"
            className="btn btn-primary"
            style={{ flex: 1, padding: '9px 16px', fontWeight: 600, display: 'flex', justifyContent: 'center', gap: 6 }}
            disabled={isLoading || !isRepoReady || !bugSummary.trim()}
          >
            {isLoading ? <Play size={14} className="spin" /> : getActionIcon()}
            {isLoading ? 'Investigating...' : getActionLabel()}
          </button>

          <button
            type="button"
            className="btn btn-secondary"
            onClick={() => {
              setBugSummary('')
              setSelectedCaseId('')
              onReset()
            }}
            disabled={isLoading}
            title="Reset form and results"
          >
            <RotateCcw size={14} />
          </button>
        </div>

        {!isRepoReady && (
          <div style={{ marginTop: 8, fontSize: 11, color: 'var(--status-warning-text)' }}>
            ⚠️ Please connect or select a ready repository above to start an investigation.
          </div>
        )}
      </form>
    </div>
  )
}
