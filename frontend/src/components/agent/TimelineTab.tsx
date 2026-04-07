/**
 * components/agent/TimelineTab.tsx — Agent run timeline (#38).
 *
 * Shows all agent runs with duration bars, status badges, cost, and
 * expandable detail panels with child agent_calls.
 *
 * C4: Every run is visible with its cost and duration.
 * C5: Cost per run is displayed prominently.
 */

import { useState } from "react"
import { ChevronDown, ChevronRight } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent } from "@/components/ui/card"
import { useAgentRuns, useAgentRunDetail } from "@/hooks/use-agent-runs"
import { useCostVisibility } from "@/lib/cost-visibility"
import { formatRelativeTime, cn } from "@/lib/utils"

const statusColors: Record<string, string> = {
  running: "bg-blue-100 text-blue-800",
  completed: "bg-green-100 text-green-800",
  failed: "bg-red-100 text-red-800",
  paused_for_hitl: "bg-amber-100 text-amber-800",
}

const statusLabels: Record<string, string> = {
  running: "Running",
  completed: "Completed",
  failed: "Failed",
  paused_for_hitl: "Paused (HITL)",
}

export function TimelineTab() {
  const [statusFilter, setStatusFilter] = useState<string | undefined>()
  const [expandedRunId, setExpandedRunId] = useState<number | null>(null)
  const runs = useAgentRuns({ status: statusFilter, limit: 50 })

  return (
    <div className="space-y-4">
      {/* Status filter */}
      <div className="flex flex-wrap gap-2">
        {[
          { value: undefined, label: "All" },
          { value: "running", label: "Running" },
          { value: "completed", label: "Completed" },
          { value: "failed", label: "Failed" },
          { value: "paused_for_hitl", label: "Paused" },
        ].map((f) => (
          <button
            key={f.value ?? "all"}
            onClick={() => setStatusFilter(f.value)}
            className={cn(
              "px-3 py-1 rounded-full text-xs font-medium border transition-colors",
              statusFilter === f.value
                ? "bg-[#0E2841] text-white border-[#0E2841]"
                : "bg-white text-muted-foreground border-border hover:bg-muted/50"
            )}
          >
            {f.label}
          </button>
        ))}
      </div>

      {/* Run list */}
      {runs.isLoading ? (
        <div className="space-y-2">
          {[...Array(6)].map((_, i) => (
            <div key={i} className="h-16 bg-white rounded-lg animate-pulse shadow-sm" />
          ))}
        </div>
      ) : (runs.data?.runs.length ?? 0) === 0 ? (
        <Card className="shadow-sm">
          <CardContent className="py-8 text-center">
            <p className="text-muted-foreground">No agent runs found</p>
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-2">
          {runs.data?.runs.map((run) => (
            <RunRow
              key={run.id}
              run={run}
              isExpanded={expandedRunId === run.id}
              onToggle={() => setExpandedRunId(expandedRunId === run.id ? null : run.id)}
            />
          ))}
        </div>
      )}
    </div>
  )
}

function RunRow({
  run,
  isExpanded,
  onToggle,
}: {
  run: { id: number; workflow_name: string; status: string; duration_ms: number | null; total_cost_usd: number; started_at: string | null; rfq_id: number | null }
  isExpanded: boolean
  onToggle: () => void
}) {
  const detail = useAgentRunDetail(isExpanded ? run.id : null)
  const durationSec = run.duration_ms ? (run.duration_ms / 1000).toFixed(1) : "—"
  const { showCost } = useCostVisibility()

  return (
    <div className="bg-white rounded-lg shadow-sm border overflow-hidden">
      <button
        onClick={onToggle}
        className="w-full flex items-center gap-3 p-3 hover:bg-muted/30 transition-colors text-left"
      >
        {isExpanded ? (
          <ChevronDown className="h-4 w-4 text-muted-foreground shrink-0" />
        ) : (
          <ChevronRight className="h-4 w-4 text-muted-foreground shrink-0" />
        )}

        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium">{run.workflow_name}</span>
            <Badge variant="secondary" className={`text-[10px] ${statusColors[run.status] ?? ""}`}>
              {statusLabels[run.status] ?? run.status}
            </Badge>
            {run.rfq_id && (
              <span className="text-xs text-muted-foreground">RFQ #{run.rfq_id}</span>
            )}
          </div>
          <p className="text-xs text-muted-foreground mt-0.5">
            {run.started_at ? formatRelativeTime(run.started_at) : "—"}
          </p>
        </div>

        {/* Duration bar */}
        <div className="hidden sm:flex items-center gap-3 shrink-0">
          <div className="text-right">
            <p className="text-xs font-mono">{durationSec}s</p>
            {showCost && <p className="text-[10px] text-muted-foreground">${run.total_cost_usd.toFixed(4)}</p>}
          </div>
          <div className="w-24 h-2 bg-muted rounded-full overflow-hidden">
            <div
              className={cn(
                "h-full rounded-full",
                run.status === "completed" ? "bg-green-500" :
                run.status === "failed" ? "bg-red-500" :
                run.status === "running" ? "bg-blue-500 animate-pulse" :
                "bg-amber-500"
              )}
              style={{ width: `${Math.min(100, (run.duration_ms ?? 0) / 600)}%` }}
            />
          </div>
        </div>
      </button>

      {/* Expanded detail — child calls */}
      {isExpanded && (
        <div className="border-t bg-muted/20 p-3">
          {detail.isLoading ? (
            <div className="space-y-2">
              {[...Array(3)].map((_, i) => (
                <div key={i} className="h-10 bg-muted/50 rounded animate-pulse" />
              ))}
            </div>
          ) : (detail.data?.calls.length ?? 0) === 0 ? (
            <p className="text-xs text-muted-foreground">No agent calls recorded</p>
          ) : (
            <div className="space-y-2">
              <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
                Agent Calls ({detail.data?.call_count})
              </p>
              {detail.data?.calls.map((call) => (
                <CallRow key={call.id} call={call} />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function CallRow({ call }: { call: { id: number; agent_name: string; model: string; provider: string; status: string; input_tokens: number; output_tokens: number; cost_usd: number; duration_ms: number | null } }) {
  const { showCost } = useCostVisibility()
  return (
    <div className="flex items-center justify-between bg-white rounded p-2 border text-xs">
      <div>
        <span className="font-medium">{call.agent_name}</span>
        <span className="text-muted-foreground ml-2">{call.model}</span>
      </div>
      <div className="flex items-center gap-3 text-muted-foreground">
        <span>{call.input_tokens + call.output_tokens} tokens</span>
        {showCost && <span>${call.cost_usd.toFixed(4)}</span>}
        <span>{call.duration_ms ? `${(call.duration_ms / 1000).toFixed(1)}s` : "—"}</span>
        <Badge variant="secondary" className={`text-[9px] ${statusColors[call.status] ?? ""}`}>
          {call.status}
        </Badge>
      </div>
    </div>
  )
}
