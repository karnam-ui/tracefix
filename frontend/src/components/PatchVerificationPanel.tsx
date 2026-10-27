import React from 'react'
import {
  AlertCircle,
  CheckCircle2,
  Clock,
  FileCode,
  ShieldAlert,
  ShieldCheck,
  XCircle,
} from 'lucide-react'
import type { VerificationSummary } from '../types'

interface PatchVerificationPanelProps {
  proposedPatch?: string | null
  patchSafety?: {
    is_valid?: boolean
    errors?: string[]
    prohibited_files?: string[]
    warnings?: string[]
  }
  verification?: VerificationSummary | null
}

export const PatchVerificationPanel: React.FC<PatchVerificationPanelProps> = ({
  proposedPatch,
  patchSafety,
  verification,
}) => {
  if (!proposedPatch && !verification) {
    return (
      <div className="panel-card" style={{ marginBottom: 16 }}>
        <div className="panel-header">
          <span className="panel-title">Patch Proposal &amp; Sandbox Verification</span>
        </div>
        <div className="panel-body empty-placeholder">
          No repair executed. Select Mode D (&quot;Trace &amp; Fix&quot;) to generate a candidate diff and execute isolated tests.
        </div>
      </div>
    )
  }

  // Format diff lines into syntax elements
  const renderDiffLines = (rawDiff: string) => {
    return rawDiff.split('\n').map((line, idx) => {
      let className = 'diff-line'
      if (line.startsWith('+') && !line.startsWith('+++')) {
        className += ' diff-add'
      } else if (line.startsWith('-') && !line.startsWith('---')) {
        className += ' diff-del'
      } else if (line.startsWith('@@')) {
        className += ' diff-hunk'
      } else if (line.startsWith('---') || line.startsWith('+++')) {
        className += ' diff-header'
      }
      return (
        <div key={idx} className={className}>
          {line || ' '}
        </div>
      )
    })
  }

  const status = verification?.status || 'UNKNOWN'
  const isVerified = status === 'VERIFIED'
  const isUnavailable = status === 'UNAVAILABLE'
  const isFailed = status === 'TEST_FAILED' || status === 'FAILED'
  const isTimeout = status === 'TIMEOUT'

  return (
    <div className="panel-card" style={{ marginBottom: 16 }}>
      <div className="panel-header">
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <FileCode size={14} color="var(--accent-primary)" />
          <span className="panel-title">Repair Proposal &amp; Verification</span>
          {patchSafety && patchSafety.is_valid !== undefined && (
            <span
              className={`badge ${patchSafety.is_valid ? 'badge-green' : 'badge-red'}`}
              style={{ display: 'inline-flex', gap: 3, alignItems: 'center', fontSize: 10 }}
            >
              {patchSafety.is_valid ? <ShieldCheck size={10} /> : <ShieldAlert size={10} />}
              {patchSafety.is_valid ? 'AST SAFETY: PASS' : 'AST SAFETY: VIOLATION'}
            </span>
          )}
        </div>

        {verification && (
          <span
            className={`badge ${
              isVerified ? 'badge-green' : isUnavailable ? 'badge-yellow' : 'badge-red'
            } mono`}
            style={{ fontSize: 11 }}
          >
            {status} {verification.exit_code !== 0 && `(exit ${verification.exit_code})`}
          </span>
        )}
      </div>

      <div className="panel-body">
        {/* Verification Status Banner */}
        {verification && (
          <div
            style={{
              padding: '8px 12px',
              borderRadius: 'var(--radius-sm)',
              marginBottom: 12,
              backgroundColor: isVerified
                ? 'var(--status-success-bg)'
                : isUnavailable
                ? 'var(--status-warning-bg)'
                : 'var(--status-danger-bg)',
              border: `1px solid ${
                isVerified
                  ? 'rgba(46, 160, 67, 0.4)'
                  : isUnavailable
                  ? 'rgba(210, 153, 34, 0.4)'
                  : 'rgba(248, 81, 73, 0.4)'
              }`,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              fontSize: 12,
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              {isVerified && <CheckCircle2 size={16} color="var(--status-success-text)" />}
              {isUnavailable && <AlertCircle size={16} color="var(--status-warning-text)" />}
              {isFailed && <XCircle size={16} color="var(--status-danger-text)" />}
              {isTimeout && <Clock size={16} color="var(--status-warning-text)" />}
              <div>
                <strong>
                  {isVerified
                    ? 'Patch Verified in Isolated Sandbox'
                    : isUnavailable
                    ? 'Repair Generation Unavailable'
                    : isTimeout
                    ? 'Test Execution Timed Out'
                    : 'Sandbox Tests Failed'}
                </strong>
                {verification.details && (
                  <div style={{ fontSize: 11, color: 'var(--text-secondary)', marginTop: 2 }}>
                    {verification.details}
                  </div>
                )}
              </div>
            </div>

            {verification.duration_seconds > 0 && (
              <span className="mono" style={{ fontSize: 11, color: 'var(--text-secondary)' }}>
                {verification.duration_seconds.toFixed(2)}s runtime
              </span>
            )}
          </div>
        )}

        {/* Safety Check Violations */}
        {patchSafety && patchSafety.errors && patchSafety.errors.length > 0 && (
          <div
            style={{
              marginBottom: 12,
              padding: '8px 10px',
              backgroundColor: 'var(--status-danger-bg)',
              borderRadius: 'var(--radius-sm)',
              color: 'var(--status-danger-text)',
              fontSize: 11,
            }}
          >
            <div style={{ fontWeight: 600, marginBottom: 4 }}>Safety Check Violations:</div>
            <ul style={{ margin: 0, paddingLeft: 16 }}>
              {patchSafety.errors.map((err, i) => (
                <li key={i}>{err}</li>
              ))}
            </ul>
          </div>
        )}

        {/* Unified Diff View */}
        {proposedPatch ? (
          <div>
            <div style={{ fontSize: 11, color: 'var(--text-secondary)', marginBottom: 6, fontWeight: 600 }}>
              Proposed Unified Diff (Review Before Applying to Working Tree):
            </div>
            <div className="diff-view">{renderDiffLines(proposedPatch)}</div>
          </div>
        ) : isUnavailable ? (
          <div style={{ fontSize: 12, color: 'var(--text-secondary)', padding: 12, backgroundColor: 'var(--bg-secondary)', borderRadius: 'var(--radius-sm)' }}>
            To generate repairs with LLM models, configure an API key in your local environment:
            <pre className="mono" style={{ margin: '8px 0 0 0', padding: 8, backgroundColor: 'var(--bg-primary)', borderRadius: 4, fontSize: 11 }}>
              export ANTHROPIC_API_KEY=&quot;your-key&quot; # or OPENROUTER_API_KEY
            </pre>
          </div>
        ) : null}
      </div>
    </div>
  )
}
