/**
 * components/agent/ActivityTab.tsx — Unified agent activity view (#165).
 *
 * Single chronological list of all agent runs and jobs. Each item shows
 * workflow name, status, duration, cost, RFQ link, and job queue info.
 * Expanding an item reveals the LLM call decisions with full prompt/response
 * drill-down (previously in the Decisions tab).
 *
 * Replaces the separate Timeline, Decisions, and Tasks tabs.
 *
 * C4: Every agent decision is traceable to its prompt, model, tokens, and cost.
 * C5: Cost tracking visible per run and per call.
 */

import { useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { ChevronDown, ChevronRight, Bot, Cog, AlertCircle } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent } from "@/components/ui/card"
import { useAgentRuns, useAgentRunDetail } from "@/hooks/use-agent-runs"
import { useCostVisibility } from "@/lib/cost-visibility"
import { formatRelativeTime, cn } from "@/lib/utils"
import { api } from "@/lib/api"
import type { AgentCallItem } from "@/hooks/use-agent-runs"

/** Status badge colors shared across runs, calls, and jobs */
const statusColors: Record<string, string> = {
  running: "bg-blue-100 text-blue-800",
  completed: "bg-green-100 text-green-800",
  failed: "bg-red-100 text-red-800",
  paused_for_hitl: "bg-amber-100 text-amber-800",
  pending: "bg-amber-100 text-amber-800",
  success: "bg-green-100 text-green-800",
  timeout: "bg-red-100 text-red-800",
  rate_limited: "bg-orange-100 text-orange-800",
}

const statusLabels: Record<string, string> = {
  running: "Running",
  completed: "Completed",
  failed: "Failed",
  paused_for_hitl: "Paused",
  pending: "Queued",
  success: "Success",
  timeout: "Timeout",
  rate_limited: "Rate Limited",
}

/** Status filter options */
const STATUS_FILTERS = [
  { value: undefined, label: "All" },
  { value: "running", label: "Running" },
  { value: "completed", label: "Completed" },
  { value: "failed", label: "Failed" },
  { value: "paused_for_hitl", label: "Paused" },
]

interface JobItem {
  id: number
  job_type: string
  status: string
  rfq_id: number | null
  retry_count: number
  created_at: string
  started_at: string | null
  finished_at: string | null
  error_message: string | null
}

export function ActivityTab() {
  const [statusFilter, setStatusFilter] = useState<string | undefined>()
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const runs = useAgentRuns({ status: statusFilter, limit: 50 })
  const jobs = useQuery({
    queryKey: ["agent", "jobs"],
    queryFn: () => api.get<{ jobs: JobItem[]; total: number }>("/api/agent/jobs"),
  })

  // Merge runs and pending/running jobs into one chronological list
  type ActivityItem =
    | { type: "run"; data: typeof runs.data extends { runs: (infer R)[] } ? R : never; sortTime: string }
    | { type: "job"; data: JobItem; sortTime: string }

  const items: ActivityItem[] = []

  // Add agent runs
  if (runs.data?.runs) {
    for (const run of runs.data.runs) {
      items.push({
        type: "run",
        data: run,
        sortTime: run.started_at ?? "",
      })
    }
  }

  // Add pending/running jobs that don't have a corresponding agent run yet
  if (jobs.data?.jobs) {
    for (const job of jobs.data.jobs) {
      if (job.status === "pending" || job.status === "running") {
        items.push({
          type: "job",
          data: job,
          sortTime: job.created_at,
        })
      }
    }
  }

  // Sort newest first
  items.sort((a, b) => (b.sortTime > a.sortTime ? 1 : -1))

  const isLoading = runs.isLoading || jobs.isLoading

  return (
    <div className="space-y-4">
      {/* Status filter */}
      <div className="flex flex-wrap gap-2">
        {STATUS_FILTERS.map((f) => (
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

      {/* Activity list */}
      {isLoading ? (
        <div className="space-y-2">
          {[...Array(6)].map((_, i) => (
            <div key={i} className="h-16 bg-white rounded-lg animate-pulse shadow-sm" />
          ))}
        </div>
      ) : items.length === 0 ? (
        <Card className="shadow-sm">
          <CardContent className="py-8 text-center">
            <p className="text-muted-foreground">No agent activity</p>
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-2">
          {items.map((item) => {
            const key = `${item.type}-${item.type === "run" ? item.data.id : item.data.id}`
            if (item.type === "run") {
              return (
                <RunItem
                  key={key}
                  run={item.data}
                  isExpanded={expandedId === key}
                  onToggle={() => setExpandedId(expandedId === key ? null : key)}
                />
              )
            } else {
              return <JobItem key={key} job={item.data} />
            }
          })}
        </div>
      )}
    </div>
  )
}

/** Agent run row — expandable to show LLM call decisions */
function RunItem({
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

        <Bot className="h-4 w-4 text-[#0F9ED5] shrink-0" />

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

        {/* Duration + cost */}
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

      {/* Expanded: LLM call decisions */}
      {isExpanded && (
        <div className="border-t bg-muted/10 p-3">
          {detail.isLoading ? (
            <div className="space-y-2">
              {[...Array(2)].map((_, i) => (
                <div key={i} className="h-10 bg-muted/50 rounded animate-pulse" />
              ))}
            </div>
          ) : (detail.data?.calls.length ?? 0) === 0 ? (
            <p className="text-xs text-muted-foreground">No LLM calls recorded</p>
          ) : (
            <div className="space-y-2">
              <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
                LLM Calls ({detail.data?.call_count})
              </p>
              {detail.data?.calls.map((call) => (
                <CallDetail key={call.id} call={call} />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

/** LLM call detail — expandable prompt/response viewer */
function CallDetail({ call }: { call: AgentCallItem }) {
  const [expanded, setExpanded] = useState(false)
  const { showCost } = useCostVisibility()

  return (
    <div className="bg-white rounded border overflow-hidden">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full text-left p-2 hover:bg-muted/30 flex items-center justify-between"
      >
        <div className="flex items-center gap-2">
          {expanded ? <ChevronDown className="h-3 w-3 text-muted-foreground" /> : <ChevronRight className="h-3 w-3 text-muted-foreground" />}
          <span className="text-xs font-medium">{call.agent_name}</span>
          <Badge variant="outline" className="text-[9px]">{call.model}</Badge>
          <Badge variant="secondary" className={`text-[9px] ${statusColors[call.status] ?? ""}`}>
            {statusLabels[call.status] ?? call.status}
          </Badge>
        </div>
        <div className="flex items-center gap-3 text-[10px] text-muted-foreground">
          <span>{(call.input_tokens + call.output_tokens).toLocaleString()} tokens</span>
          {showCost && <span>${call.cost_usd.toFixed(4)}</span>}
          <span>{call.duration_ms ? `${(call.duration_ms / 1000).toFixed(1)}s` : "—"}</span>
        </div>
      </button>

      {expanded && (
        <div className="border-t p-3 space-y-3 bg-muted/5">
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
  )
}

/** Pending/running job row — not expandable, just shows queue status */
function JobItem({ job }: { job: { id: number; job_type: string; status: string; rfq_id: number | null; retry_count: number; created_at: string; error_message: string | null } }) {
  return (
    <div className="flex items-center gap-3 bg-white rounded-lg shadow-sm border p-3">
      <Cog className={cn("h-4 w-4 shrink-0", job.status === "running" ? "text-blue-500 animate-spin" : "text-muted-foreground")} />
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium">{job.job_type}</span>
          <Badge variant="secondary" className={`text-[10px] ${statusColors[job.status] ?? ""}`}>
            {statusLabels[job.status] ?? job.status}
          </Badge>
          {job.rfq_id && <span className="text-xs text-muted-foreground">RFQ #{job.rfq_id}</span>}
        </div>
        <p className="text-xs text-muted-foreground mt-0.5">
          {formatRelativeTime(job.created_at)}
          {job.retry_count > 0 && ` · Retry ${job.retry_count}`}
        </p>
      </div>
      {job.error_message && (
        <div className="flex items-center gap-1 text-xs text-red-600 max-w-[200px] truncate">
          <AlertCircle className="h-3 w-3 shrink-0" />
          {job.error_message}
        </div>
      )}
    </div>
  )
}
