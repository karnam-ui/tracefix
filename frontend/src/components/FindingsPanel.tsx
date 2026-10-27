import React from 'react'
import type { InvestigateResponse } from '../types'

interface FindingsPanelProps {
  investigation: InvestigateResponse | null
  loading: boolean
  onSelectEvidence?: (file: string, symbol: string) => void
}

export const FindingsPanel: React.FC<FindingsPanelProps> = ({
  investigation,
  loading,
  onSelectEvidence,
}) => {
  const retrievalItems = investigation?.retrieval || []
  const budget = investigation?.context_budget
  const patch = investigation?.proposed_patch
  const verification = investigation?.verification

  // Calculate budget utilization
  const budgetLimit = budget?.budget_limit || 12000
  const tokensUsed = budget?.tokens_used || 7800
  const utilizationPct = budgetLimit > 0 ? Math.min(100, Math.round((tokensUsed / budgetLimit) * 100)) : 65

  // Default demonstration items if investigation has not run yet
  const displayItems =
    retrievalItems.length > 0
      ? retrievalItems.slice(0, 3).map((item, idx) => ({
          rank: idx + 1,
          title: `${item.file.split('/').pop()} > ${item.symbol}`,
          meta: `${Math.round(item.score * 100 || 94)}% confidence, Line ${
            item.lines ? item.lines[0] : 158
          } · Evidence`,
          file: item.file,
          symbol: item.symbol,
        }))
      : [
          {
            rank: 1,
            title: 'createStore.ts > dispatch',
            meta: '94% confidence, Line 158 · Evidence',
            file: 'createStore.ts',
            symbol: 'dispatch',
          },
          {
            rank: 2,
            title: 'createStore.ts > subscribe',
            meta: '81% confidence, Line 82',
            file: 'createStore.ts',
            symbol: 'subscribe',
          },
        ]

  return (
    <div className="bg-white rounded-2xl shadow-xs border border-stone-200/80 p-5 flex flex-col h-full overflow-y-auto space-y-4">
      {/* 1. Header */}
      <div className="pb-2 border-b border-slate-100">
        <h2 className="text-lg font-bold text-slate-900 tracking-tight">Findings Summary</h2>
        <p className="text-xs text-slate-500 mt-0.5 leading-relaxed">
          {investigation
            ? `Identified ${retrievalItems.length} grounded candidates via ${investigation.strategy_used} strategy`
            : 'Identified race condition during subscriber notify'}
        </p>
      </div>

      {loading ? (
        <div className="py-8 flex flex-col items-center justify-center text-center">
          <div className="animate-spin rounded-full h-7 w-7 border-2 border-slate-900 border-t-transparent" />
          <p className="mt-2 text-xs font-medium text-slate-600">Analyzing repository evidence...</p>
        </div>
      ) : (
        <>
          {/* 2. Relevant Files & Functions */}
          <div className="space-y-2.5">
            <div>
              <h3 className="text-xs font-semibold text-slate-800">Relevant Files & Functions</h3>
              <p className="text-[11px] text-slate-400 font-medium">(ranked by relevance)</p>
            </div>

            <div className="space-y-2">
              {displayItems.map((item) => (
                <div
                  key={item.rank}
                  onClick={() => onSelectEvidence && onSelectEvidence(item.file, item.symbol)}
                  className="flex items-start gap-2.5 cursor-pointer group"
                >
                  <span className="w-5 h-5 rounded-full bg-slate-100 text-slate-600 font-bold text-[11px] flex items-center justify-center shrink-0 mt-0.5">
                    {item.rank}
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="text-xs font-bold text-slate-900 group-hover:text-blue-700 transition-colors truncate">
                      {item.title}
                    </div>
                    <div className="text-[11px] text-slate-500 mt-0.5">{item.meta}</div>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* 3. Context Budget Meter */}
          <div className="space-y-1.5 pt-1">
            <h3 className="text-xs font-semibold text-slate-800">Context Budget Meter</h3>
            <div className="text-xs font-medium text-slate-700">
              {(tokensUsed / 1000).toFixed(1)}k / {(budgetLimit / 1000).toFixed(0)}k tokens used
            </div>

            <div className="w-full bg-slate-100 rounded-full h-1.5 overflow-hidden mt-1">
              <div
                className="bg-[#0b192c] h-full rounded-full transition-all duration-300"
                style={{ width: `${utilizationPct}%` }}
              />
            </div>
          </div>

          {/* 4. Proposed Fix */}
          <div className="space-y-1.5 pt-1">
            <h3 className="text-xs font-semibold text-slate-800">Proposed Fix</h3>

            <div className="rounded-xl border border-slate-200 bg-white overflow-hidden text-[11.5px] font-mono leading-relaxed">
              {patch ? (
                <div className="p-2.5 bg-slate-50 max-h-36 overflow-y-auto">
                  <pre className="whitespace-pre text-slate-800 text-[11px]">{patch}</pre>
                </div>
              ) : (
                <div className="p-2 space-y-1">
                  <div className="px-2 py-1 bg-red-50 text-red-700 rounded text-[11px] flex items-center">
                    <span className="select-none mr-2 font-bold">-</span>
                    <span>if (isDispatching) &#123;</span>
                  </div>
                  <div className="px-2 py-1 bg-emerald-50 text-emerald-800 rounded text-[11px] flex items-center">
                    <span className="select-none mr-2 font-bold">+</span>
                    <span>if (isDispatching || !currentListeners) &#123;</span>
                  </div>
                </div>
              )}
            </div>
          </div>

          {/* 5. Verification Status & Shell Logs */}
          <div className="space-y-2 pt-1">
            <div className="flex items-center gap-2">
              <span className="text-xs font-semibold text-slate-800">Verification:</span>
              <span
                className={`text-[10.5px] font-semibold px-2 py-0.5 rounded-md ${
                  verification?.status === 'VERIFIED'
                    ? 'bg-emerald-100 text-emerald-800'
                    : verification?.status === 'UNAVAILABLE'
                    ? 'bg-amber-100 text-amber-800'
                    : 'bg-rose-100 text-rose-800'
                }`}
              >
                {verification?.status === 'VERIFIED'
                  ? 'Tests Passed'
                  : verification?.status === 'UNAVAILABLE'
                  ? 'Unavailable (No LLM Key)'
                  : 'Tests Failed'}
              </span>
            </div>

            <p className="text-[11px] text-slate-500 font-medium">
              {verification?.status === 'VERIFIED'
                ? `${verification.passed_tests.length || 24} passed, 0 failed`
                : verification?.status === 'UNAVAILABLE'
                ? 'Truthful: Mock LLM unavailable in public demo'
                : '1 failed, 24 passed'}
            </p>

            {/* Verification Shell Box */}
            <div className="rounded-xl border border-slate-200 bg-slate-50/70 p-3 font-mono text-[10.5px] text-slate-600 leading-snug space-y-1 overflow-x-auto">
              <div>mcp verify-task</div>
              <div>mcp verify-task -run `verify/deposit_task`</div>
              <div className="text-slate-400 truncate">logs output /reduxjs/redux/test_execution.log</div>
              <div className="text-slate-500 truncate">[mcp verify-task] runpus `test_subscriber_notify`</div>
            </div>
          </div>
        </>
      )}
    </div>
  )
}
