import React, { useState } from 'react'
import { Terminal, Copy, Check, X, Shield } from 'lucide-react'

interface McpGuideModalProps {
  isOpen: boolean
  onClose: () => void
}

export const McpGuideModal: React.FC<McpGuideModalProps> = ({ isOpen, onClose }) => {
  const [copiedTab, setCopiedTab] = useState<string | null>(null)
  const [activeClient, setActiveClient] = useState<'claude' | 'cursor' | 'cli'>('claude')

  if (!isOpen) return null

  const claudeConfig = JSON.stringify(
    {
      mcpServers: {
        tracefix: {
          command: 'uv',
          args: ['run', 'python', '-m', 'tracefix.mcp.server'],
          cwd: '${workspaceFolder}',
        },
      },
    },
    null,
    2
  )

  const cursorConfig = JSON.stringify(
    {
      mcpServers: {
        tracefix: {
          command: 'tracefix-mcp',
        },
      },
    },
    null,
    2
  )

  const copyToClipboard = (text: string, tab: string) => {
    navigator.clipboard.writeText(text)
    setCopiedTab(tab)
    setTimeout(() => setCopiedTab(null), 2000)
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 backdrop-blur-xs p-4">
      <div className="bg-white rounded-2xl shadow-xl border border-slate-200 w-full max-w-2xl overflow-hidden animate-in fade-in zoom-in-95 duration-150">
        {/* Header */}
        <div className="px-6 py-4 border-b border-slate-100 flex items-center justify-between bg-slate-50/50">
          <div className="flex items-center gap-2.5">
            <div className="p-1.5 rounded-lg bg-blue-50 text-blue-600">
              <Terminal className="w-5 h-5" />
            </div>
            <div>
              <h3 className="text-base font-semibold text-slate-900">Model Context Protocol (MCP) Setup</h3>
              <p className="text-xs text-slate-500">Connect compatible coding agents directly to TraceFix via STDIO</p>
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

        {/* Body */}
        <div className="p-6 space-y-5 max-h-[80vh] overflow-y-auto">
          {/* Security & Boundary Notice */}
          <div className="p-3.5 bg-blue-50/60 border border-blue-200/80 rounded-xl text-xs text-blue-900 flex items-start gap-3">
            <Shield className="w-4 h-4 text-blue-600 shrink-0 mt-0.5" />
            <div>
              <span className="font-semibold">Local STDIO Architecture: </span>
              TraceFix runs as a read-only local subprocess. It never opens network ports or exposes your code to external servers. Coding agents access repository intelligence through verified tools.
            </div>
          </div>

          {/* Client Selector Tabs */}
          <div className="flex border-b border-slate-200 gap-4 text-xs font-medium">
            <button
              type="button"
              onClick={() => setActiveClient('claude')}
              className={`pb-2 transition-colors relative ${
                activeClient === 'claude'
                  ? 'text-blue-600 border-b-2 border-blue-600 font-semibold'
                  : 'text-slate-500 hover:text-slate-700'
              }`}
            >
              Claude Desktop
            </button>
            <button
              type="button"
              onClick={() => setActiveClient('cursor')}
              className={`pb-2 transition-colors relative ${
                activeClient === 'cursor'
                  ? 'text-blue-600 border-b-2 border-blue-600 font-semibold'
                  : 'text-slate-500 hover:text-slate-700'
              }`}
            >
              Cursor IDE
            </button>
            <button
              type="button"
              onClick={() => setActiveClient('cli')}
              className={`pb-2 transition-colors relative ${
                activeClient === 'cli'
                  ? 'text-blue-600 border-b-2 border-blue-600 font-semibold'
                  : 'text-slate-500 hover:text-slate-700'
              }`}
            >
              Command Line
            </button>
          </div>

          {/* Code Configuration Box */}
          <div className="relative">
            <div className="flex items-center justify-between px-3 py-1.5 bg-slate-800 text-slate-300 text-xs font-mono rounded-t-lg">
              <span>
                {activeClient === 'claude'
                  ? 'claude_desktop_config.json'
                  : activeClient === 'cursor'
                  ? 'mcp.json'
                  : 'Terminal STDIO Invocation'}
              </span>
              <button
                type="button"
                onClick={() =>
                  copyToClipboard(
                    activeClient === 'claude'
                      ? claudeConfig
                      : activeClient === 'cursor'
                      ? cursorConfig
                      : 'uv run tracefix-mcp',
                    activeClient
                  )
                }
                className="flex items-center gap-1 text-[11px] hover:text-white transition-colors"
              >
                {copiedTab === activeClient ? (
                  <>
                    <Check className="w-3.5 h-3.5 text-emerald-400" /> Copied
                  </>
                ) : (
                  <>
                    <Copy className="w-3.5 h-3.5" /> Copy Config
                  </>
                )}
              </button>
            </div>
            <pre className="p-4 bg-slate-900 text-slate-100 font-mono text-xs rounded-b-lg overflow-x-auto leading-relaxed">
              {activeClient === 'claude'
                ? claudeConfig
                : activeClient === 'cursor'
                ? cursorConfig
                : '# Start TraceFix MCP Server over standard input/output:\nuv run tracefix-mcp\n\n# Or directly via Python module:\nuv run python -m tracefix.mcp.server'}
            </pre>
          </div>

          {/* Available MCP Tools Reference */}
          <div className="space-y-2">
            <h4 className="text-xs font-semibold text-slate-800 uppercase tracking-wide">
              Exposed Read-Only Tools
            </h4>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-2 text-xs">
              <div className="p-3 bg-slate-50 rounded-lg border border-slate-200/80">
                <span className="font-mono font-semibold text-blue-700">find_relevant_code</span>
                <p className="text-slate-600 text-[11px] mt-1">
                  Locates functions, classes, and code symbols relevant to a query with line ranges and scores.
                </p>
              </div>
              <div className="p-3 bg-slate-50 rounded-lg border border-slate-200/80">
                <span className="font-mono font-semibold text-blue-700">trace_dependencies</span>
                <p className="text-slate-600 text-[11px] mt-1">
                  Traverses caller, callee, import, and test relationships around a symbol or path.
                </p>
              </div>
              <div className="p-3 bg-slate-50 rounded-lg border border-slate-200/80">
                <span className="font-mono font-semibold text-blue-700">build_investigation_context</span>
                <p className="text-slate-600 text-[11px] mt-1">
                  Packs ranked evidence into an optimal context budget without blowing agent memory.
                </p>
              </div>
              <div className="p-3 bg-slate-50 rounded-lg border border-slate-200/80">
                <span className="font-mono font-semibold text-blue-700">list_repositories</span>
                <p className="text-slate-600 text-[11px] mt-1">
                  Lists connected repositories, active branches, revisions, and graph readiness.
                </p>
              </div>
            </div>
          </div>
        </div>

        {/* Footer */}
        <div className="px-6 py-3 bg-slate-50 border-t border-slate-100 flex items-center justify-between text-xs">
          <span className="text-slate-500">TraceFix MCP Protocol v2.3</span>
          <button
            type="button"
            onClick={onClose}
            className="px-4 py-1.5 bg-blue-600 hover:bg-blue-700 text-white font-medium rounded-lg transition-colors"
          >
            Close Guide
          </button>
        </div>
      </div>
    </div>
  )
}
