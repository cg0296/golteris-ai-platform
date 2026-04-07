/**
 * components/agent/DecisionsTab.tsx — Agent decisions audit view (#37).
 *
 * Shows every LLM call with prompt, response, tokens, cost, and duration.
 * The broker can drill into any agent decision and see exactly what was
 * asked and what was returned (C4 — visible reasoning).
 */

import { useState } from "react"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent } from "@/components/ui/card"
import { useAgentRuns, useAgentRunDetail } from "@/hooks/use-agent-runs"
import { formatRelativeTime } from "@/lib/utils"
import type { AgentCallItem } from "@/hooks/use-agent-runs"

export function DecisionsTab() {
  const runs = useAgentRuns({ limit: 20 })
  const [selectedRunId, setSelectedRunId] = useState<number | null>(null)
  const detail = useAgentRunDetail(selectedRunId)
  const [expandedCallId, setExpandedCallId] = useState<number | null>(null)

  return (
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
      {/* Run list (left) */}
      <div className="space-y-2">
        <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
          Recent Runs
        </p>
        {runs.isLoading ? (
          <div className="space-y-2">
            {[...Array(5)].map((_, i) => (
              <div key={i} className="h-12 bg-white rounded animate-pulse shadow-sm" />
            ))}
          </div>
        ) : (
          runs.data?.runs.map((run) => (
            <button
              key={run.id}
              onClick={() => { setSelectedRunId(run.id); setExpandedCallId(null) }}
              className={`w-full text-left p-3 rounded-lg border transition-colors ${
                selectedRunId === run.id
                  ? "border-[#0F9ED5] bg-[#E8F4FC]"
                  : "bg-white hover:bg-muted/30"
              }`}
            >
              <p className="text-sm font-medium">{run.workflow_name}</p>
              <p className="text-xs text-muted-foreground">
                {run.started_at ? formatRelativeTime(run.started_at) : "—"} · ${run.total_cost_usd.toFixed(4)}
              </p>
            </button>
          ))
        )}
      </div>

      {/* Call detail (right) */}
      <div className="lg:col-span-2 space-y-2">
        <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
          Agent Calls
        </p>
        {!selectedRunId ? (
          <Card className="shadow-sm">
            <CardContent className="py-8 text-center">
              <p className="text-muted-foreground text-sm">Select a run to see its decisions</p>
            </CardContent>
          </Card>
        ) : detail.isLoading ? (
          <div className="space-y-2">
            {[...Array(3)].map((_, i) => (
              <div key={i} className="h-16 bg-white rounded animate-pulse shadow-sm" />
            ))}
          </div>
        ) : (
          detail.data?.calls.map((call) => (
            <div key={call.id} className="bg-white rounded-lg shadow-sm border overflow-hidden">
              <button
                onClick={() => setExpandedCallId(expandedCallId === call.id ? null : call.id)}
                className="w-full text-left p-3 hover:bg-muted/30"
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium">{call.agent_name}</span>
                    <Badge variant="outline" className="text-[10px]">{call.model}</Badge>
                  </div>
                  <div className="flex items-center gap-3 text-xs text-muted-foreground">
                    <span>{call.input_tokens + call.output_tokens} tokens</span>
                    <span>${call.cost_usd.toFixed(4)}</span>
                    <span>{call.duration_ms ? `${(call.duration_ms / 1000).toFixed(1)}s` : "—"}</span>
                  </div>
                </div>
              </button>

              {expandedCallId === call.id && (
                <div className="border-t p-3 space-y-3 bg-muted/10">
                  {call.system_prompt && (
                    <div>
                      <p className="text-[10px] font-semibold text-muted-foreground uppercase mb-1">System Prompt</p>
                      <pre className="text-xs bg-muted/30 p-2 rounded overflow-x-auto max-h-32 whitespace-pre-wrap">{call.system_prompt}</pre>
                    </div>
                  )}
                  <div>
                    <p className="text-[10px] font-semibold text-muted-foreground uppercase mb-1">User Prompt</p>
                    <pre className="text-xs bg-muted/30 p-2 rounded overflow-x-auto max-h-48 whitespace-pre-wrap">{call.user_prompt}</pre>
                  </div>
                  {call.response && (
                    <div>
                      <p className="text-[10px] font-semibold text-muted-foreground uppercase mb-1">Response</p>
                      <pre className="text-xs bg-blue-50 p-2 rounded overflow-x-auto max-h-48 whitespace-pre-wrap">{call.response}</pre>
                    </div>
                  )}
                  {call.error_message && (
                    <div>
                      <p className="text-[10px] font-semibold text-muted-foreground uppercase mb-1">Error</p>
                      <pre className="text-xs bg-red-50 p-2 rounded overflow-x-auto">{call.error_message}</pre>
                    </div>
                  )}
                </div>
              )}
            </div>
          ))
        )}
      </div>
    </div>
  )
}
