import React, { useState } from 'react'
import {
  AlertCircle,
  CheckCircle2,
  FolderGit2,
  Plus,
  RefreshCw,
  Trash2,
  X,
} from 'lucide-react'
import type { ConnectRepositoryRequest, RepositorySummary } from '../types'

interface RepositorySectionProps {
  repositories: RepositorySummary[]
  activeRepository: RepositorySummary | null
  isLoading: boolean
  onSelectRepo: (repoId: string) => void
  onConnectRepo: (req: ConnectRepositoryRequest) => Promise<void>
  onIngestRepo: (repoId: string) => Promise<void>
  onDisconnectRepo: (repoId: string) => Promise<void>
}

export const RepositorySection: React.FC<RepositorySectionProps> = ({
  repositories,
  activeRepository,
  isLoading,
  onSelectRepo,
  onConnectRepo,
  onIngestRepo,
  onDisconnectRepo,
}) => {
  const [showConnectModal, setShowConnectModal] = useState(false)
  const [connectPath, setConnectPath] = useState('')
  const [connectName, setConnectName] = useState('')
  const [connectError, setConnectError] = useState<string | null>(null)
  const [isConnecting, setIsConnecting] = useState(false)
  const [isIngesting, setIsIngesting] = useState(false)

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

  const handleIngestClick = async () => {
    if (!activeRepository) return
    setIsIngesting(true)
    try {
      await onIngestRepo(activeRepository.repo_id)
    } finally {
      setIsIngesting(false)
    }
  }

  const handleDeleteClick = async () => {
    if (!activeRepository) return
    if (confirm(`Disconnect repository '${activeRepository.name}' from TraceFix?`)) {
      await onDisconnectRepo(activeRepository.repo_id)
    }
  }

  const getStatusBadge = (status: string, isStale: boolean) => {
    if (isStale) {
      return (
        <span className="badge badge-yellow" title="Working tree commit differs from indexed graph">
          INDEX STALE
        </span>
      )
    }
    switch (status.toLowerCase()) {
      case 'ready':
        return (
          <span className="badge badge-green" style={{ display: 'inline-flex', gap: 3, alignItems: 'center' }}>
            <CheckCircle2 size={10} /> INDEX READY
          </span>
        )
      case 'indexing':
        return <span className="badge badge-blue">INDEXING...</span>
      case 'not_indexed':
        return <span className="badge badge-yellow">NOT INDEXED</span>
      case 'failed':
        return <span className="badge badge-red">INDEX FAILED</span>
      default:
        return <span className="badge badge-neutral">{status.toUpperCase()}</span>
    }
  }

  return (
    <div className="panel-card" style={{ marginBottom: 16 }}>
      <div className="panel-header" style={{ padding: '10px 14px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <FolderGit2 size={16} color="var(--accent-primary)" />
          <span className="panel-title" style={{ fontSize: 13 }}>Connected Repository</span>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          {repositories.length > 0 && activeRepository && (
            <select
              className="form-select mono"
              style={{ width: 'auto', padding: '4px 10px', fontSize: 12, fontWeight: 600 }}
              value={activeRepository.repo_id}
              onChange={(e) => onSelectRepo(e.target.value)}
              disabled={isLoading || isIngesting}
            >
              {repositories.map((r) => (
                <option key={r.repo_id} value={r.repo_id}>
                  {r.name} ({r.short_sha})
                </option>
              ))}
            </select>
          )}

          <button
            type="button"
            className="btn btn-sm btn-primary"
            onClick={() => setShowConnectModal(true)}
            disabled={isLoading || isIngesting}
          >
            <Plus size={12} /> Connect Local Repo
          </button>
        </div>
      </div>

      <div className="panel-body" style={{ padding: '12px 14px' }}>
        {activeRepository ? (
          <div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: 10 }}>
              <div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                  <span style={{ fontSize: 14, fontWeight: 600, color: 'var(--text-primary)' }}>
                    {activeRepository.name}
                  </span>
                  {getStatusBadge(activeRepository.status, activeRepository.is_stale)}
                  <span className="badge badge-neutral mono" style={{ fontSize: 11 }}>
                    branch: {activeRepository.default_branch}
                  </span>
                  <span className="badge badge-blue mono" style={{ fontSize: 11 }} title="Working HEAD revision">
                    HEAD: {activeRepository.short_sha}
                  </span>
                </div>
                <div className="mono" style={{ fontSize: 11, color: 'var(--text-secondary)', marginBottom: 6 }}>
                  {activeRepository.local_path}
                </div>
                <div style={{ fontSize: 11, color: 'var(--text-muted)', display: 'flex', gap: 14 }}>
                  <span>Files: <strong>{activeRepository.python_file_count} Python</strong></span>
                  <span>
                    Graph: <strong>{activeRepository.graph_available ? `${activeRepository.node_count.toLocaleString()} nodes, ${activeRepository.edge_count.toLocaleString()} edges` : 'No graph built'}</strong>
                  </span>
                  {activeRepository.last_ingested_at && (
                    <span>Last Ingested: {new Date(activeRepository.last_ingested_at).toLocaleTimeString()}</span>
                  )}
                </div>
              </div>

              <div style={{ display: 'flex', gap: 8 }}>
                <button
                  type="button"
                  className={`btn btn-sm ${activeRepository.graph_available && !activeRepository.is_stale ? 'btn-secondary' : 'btn-primary'}`}
                  onClick={handleIngestClick}
                  disabled={isIngesting || isLoading}
                  title="Parse AST and build or refresh FalkorDB property graph"
                >
                  <RefreshCw size={12} className={isIngesting ? 'spin' : ''} />
                  {isIngesting ? 'Ingesting AST...' : activeRepository.graph_available ? 'Reindex Graph' : 'Ingest & Build Graph'}
                </button>
                <button
                  type="button"
                  className="btn btn-sm btn-secondary"
                  onClick={handleDeleteClick}
                  disabled={isIngesting || isLoading}
                  title="Disconnect repository"
                >
                  <Trash2 size={12} />
                </button>
              </div>
            </div>

            {activeRepository.last_error && (
              <div style={{ marginTop: 8, padding: '6px 10px', backgroundColor: 'var(--status-danger-bg)', borderRadius: 'var(--radius-sm)', color: 'var(--status-danger-text)', fontSize: 11, display: 'flex', gap: 6, alignItems: 'center' }}>
                <AlertCircle size={12} />
                <span>Last Ingestion Error: {activeRepository.last_error}</span>
              </div>
            )}
          </div>
        ) : (
          <div className="empty-placeholder" style={{ padding: '16px 8px' }}>
            <p style={{ margin: '0 0 8px 0', fontSize: 13 }}>No repository connected to TraceFix.</p>
            <p style={{ margin: 0, fontSize: 11, color: 'var(--text-secondary)' }}>
              Click <strong>&quot;Connect Local Repo&quot;</strong> above to select an existing Git repository directory on your machine.
            </p>
          </div>
        )}
      </div>

      {/* Connect Repository Modal */}
      {showConnectModal && (
        <div
          style={{
            position: 'fixed',
            inset: 0,
            backgroundColor: 'rgba(0,0,0,0.65)',
            zIndex: 1000,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            padding: 16,
          }}
        >
          <div
            className="panel-card"
            style={{ width: '100%', maxWidth: 500, boxShadow: 'var(--shadow-md)' }}
          >
            <div className="panel-header">
              <span className="panel-title">Connect Local Git Repository</span>
              <button
                type="button"
                className="btn btn-sm btn-secondary"
                onClick={() => setShowConnectModal(false)}
              >
                <X size={14} />
              </button>
            </div>

            <form onSubmit={handleConnectSubmit} className="panel-body">
              <p style={{ fontSize: 12, color: 'var(--text-secondary)', marginBottom: 12 }}>
                Provide the absolute path to an existing Git repository on your local machine. TraceFix will validate the directory, inspect its HEAD commit, and prepare it for graph ingestion.
              </p>

              <div className="form-group">
                <label className="form-label" htmlFor="repo-path">
                  Local Repository Directory Path <span style={{ color: 'var(--status-danger-text)' }}>*</span>
                </label>
                <input
                  id="repo-path"
                  type="text"
                  className="form-input mono"
                  placeholder="/Users/.../my-repo or ./data/repos/requests"
                  value={connectPath}
                  onChange={(e) => setConnectPath(e.target.value)}
                  required
                  autoFocus
                />
              </div>

              <div className="form-group">
                <label className="form-label" htmlFor="repo-name">
                  Repository Display Name (Optional)
                </label>
                <input
                  id="repo-name"
                  type="text"
                  className="form-input"
                  placeholder="Defaults to directory name (e.g. requests)"
                  value={connectName}
                  onChange={(e) => setConnectName(e.target.value)}
                />
              </div>

              {connectError && (
                <div style={{ marginBottom: 12, padding: '8px 10px', backgroundColor: 'var(--status-danger-bg)', borderRadius: 'var(--radius-sm)', color: 'var(--status-danger-text)', fontSize: 12 }}>
                  {connectError}
                </div>
              )}

              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 16 }}>
                <button
                  type="button"
                  className="btn btn-secondary"
                  onClick={() => setShowConnectModal(false)}
                  disabled={isConnecting}
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="btn btn-primary"
                  disabled={isConnecting || !connectPath.trim()}
                >
                  {isConnecting ? 'Validating Git Repo...' : 'Validate & Connect'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  )
}

