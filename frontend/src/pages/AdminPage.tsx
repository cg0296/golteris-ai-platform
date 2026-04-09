/**
 * pages/AdminPage.tsx — Admin panel (#131).
 *
 * Two tabs:
 * 1. Process Manager — view running processes, restart worker, see job queue
 * 2. Pipeline Tracker — search for any RFQ and see its full pipeline trace
 *
 * Only accessible to users with admin role.
 */

import { useState, useMemo } from "react"
import { Shield, RefreshCw, Search, ChevronRight, Circle, Activity } from "lucide-react"
import { toast } from "sonner"
import { useQuery } from "@tanstack/react-query"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  useProcesses,
  useRestartWorker,
  usePipelineSearch,
  usePipelineTrace,
  type PipelineStage,
} from "@/hooks/use-admin"
import { api } from "@/lib/api"
import { formatRelativeTime, cn } from "@/lib/utils"

/** Status color mapping for processes */
const statusColors: Record<string, string> = {
  running: "bg-green-500",
  stopped: "bg-red-500",
  error: "bg-red-500",
}

/** Pipeline stage status colors */
const stageStatusColors: Record<string, string> = {
  completed: "bg-green-100 text-green-800",
  running: "bg-blue-100 text-blue-800",
  pending: "bg-amber-100 text-amber-800",
  failed: "bg-red-100 text-red-800",
  pending_approval: "bg-amber-100 text-amber-800",
  approved: "bg-green-100 text-green-800",
  rejected: "bg-gray-100 text-gray-600",
}

export function AdminPage() {
  return (
    <div className="p-4 lg:p-6 max-w-7xl space-y-4">
      <h2 className="text-xl font-semibold text-[#0E2841] flex items-center gap-2">
        <Shield className="h-5 w-5" />
        Admin
      </h2>

      <Tabs defaultValue="activity-log">
        <TabsList className="grid w-full grid-cols-3 max-w-lg">
          <TabsTrigger value="activity-log" className="text-xs">Activity Log</TabsTrigger>
          <TabsTrigger value="processes" className="text-xs">Process Manager</TabsTrigger>
          <TabsTrigger value="pipeline" className="text-xs">Pipeline Tracker</TabsTrigger>
        </TabsList>

        <TabsContent value="activity-log" className="mt-4">
          <ActivityLogTab />
        </TabsContent>
        <TabsContent value="processes" className="mt-4">
          <ProcessManagerTab />
        </TabsContent>
        <TabsContent value="pipeline" className="mt-4">
          <PipelineTrackerTab />
        </TabsContent>
      </Tabs>
    </div>
  )
}


/** Process Manager — shows running services with restart controls. */
function ProcessManagerTab() {
  const processes = useProcesses()
  const restart = useRestartWorker()

  return (
    <div className="space-y-4">
      <Card className="shadow-sm">
        <CardHeader className="pb-3">
          <CardTitle className="text-base">Running Processes</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          {processes.isLoading ? (
            <div className="space-y-2">
              {[...Array(3)].map((_, i) => (
                <div key={i} className="h-12 bg-muted/50 rounded animate-pulse" />
              ))}
            </div>
          ) : (
            <>
              {processes.data?.processes.map((proc) => (
                <div key={proc.name} className="flex items-center justify-between py-2 border-b last:border-0">
                  <div className="flex items-center gap-3">
                    <Circle
                      className={`h-3 w-3 fill-current ${
                        proc.status === "running" ? "text-green-500" : "text-red-500"
                      }`}
                    />
                    <div>
                      <p className="text-sm font-medium">{proc.name}</p>
                      <p className="text-xs text-muted-foreground">
                        {proc.pid ? `PID ${proc.pid}` : ""}
                        {proc.last_activity ? ` · Last activity: ${formatRelativeTime(proc.last_activity)}` : ""}
                      </p>
                    </div>
                  </div>
                  <Badge
                    variant="secondary"
                    className={`text-xs ${
                      proc.status === "running" ? "bg-green-100 text-green-800" :
                      proc.status === "stopped" ? "bg-red-100 text-red-800" :
                      "bg-gray-100 text-gray-600"
                    }`}
                  >
                    {proc.status}
                  </Badge>
                </div>
              ))}

              {/* Job queue summary */}
              {processes.data?.jobs && (
                <div className="pt-2">
                  <p className="text-xs text-muted-foreground">
                    Job Queue: {processes.data.jobs.pending} pending, {processes.data.jobs.running} running
                  </p>
                </div>
              )}
            </>
          )}
        </CardContent>
      </Card>

      {/* Restart controls */}
      <Card className="shadow-sm">
        <CardHeader className="pb-3">
          <CardTitle className="text-base">Controls</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <Button
            variant="outline"
            onClick={() => {
              restart.mutate(undefined, {
                onSuccess: (data) => toast.success(data.message),
                onError: () => toast.error("Failed to restart worker"),
              })
            }}
            disabled={restart.isPending}
          >
            <RefreshCw className={`h-4 w-4 mr-2 ${restart.isPending ? "animate-spin" : ""}`} />
            {restart.isPending ? "Restarting..." : "Restart Worker"}
          </Button>
        </CardContent>
      </Card>
    </div>
  )
}


/** Pipeline Tracker — search and drill into any RFQ's pipeline. */
function PipelineTrackerTab() {
  const [search, setSearch] = useState("")
  const [selectedRfqId, setSelectedRfqId] = useState<number | null>(null)
  const results = usePipelineSearch(search)
  const trace = usePipelineTrace(selectedRfqId)

  return (
    <div className="space-y-4">
      {/* Search */}
      <div className="relative w-full max-w-md">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
        <input
          type="text"
          placeholder="Search by customer, route, RFQ ID..."
          value={search}
          onChange={(e) => { setSearch(e.target.value); setSelectedRfqId(null) }}
          className="w-full pl-9 pr-3 py-2 text-sm border rounded-md bg-white focus:outline-none focus:ring-2 focus:ring-[#0F9ED5]/30 focus:border-[#0F9ED5]"
        />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* RFQ list */}
        <Card className="shadow-sm">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">RFQs ({results.data?.total ?? 0})</CardTitle>
          </CardHeader>
          <CardContent className="space-y-1 max-h-[500px] overflow-y-auto">
            {results.isLoading ? (
              <div className="space-y-2">
                {[...Array(5)].map((_, i) => (
                  <div key={i} className="h-12 bg-muted/50 rounded animate-pulse" />
                ))}
              </div>
            ) : (results.data?.rfqs ?? []).length === 0 ? (
              <p className="text-sm text-muted-foreground py-4 text-center">No RFQs found</p>
            ) : (
              results.data?.rfqs.map((rfq) => (
                <button
                  key={rfq.id}
                  onClick={() => setSelectedRfqId(rfq.id)}
                  className={`w-full text-left p-3 rounded-lg border transition-colors ${
                    selectedRfqId === rfq.id
                      ? "border-[#0F9ED5] bg-[#E8F4FC]"
                      : "bg-white hover:bg-muted/30"
                  }`}
                >
                  <div className="flex items-center justify-between">
                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="text-xs font-mono text-muted-foreground">#{rfq.id}</span>
                        <span className="text-sm font-medium truncate">{rfq.customer_name}</span>
                      </div>
                      <p className="text-xs text-muted-foreground truncate">
                        {rfq.origin} → {rfq.destination}
                      </p>
                    </div>
                    <div className="flex items-center gap-2 shrink-0">
                      <Badge variant="secondary" className="text-[10px]">{rfq.state}</Badge>
                      <ChevronRight className="h-4 w-4 text-muted-foreground" />
                    </div>
                  </div>
                </button>
              ))
            )}
          </CardContent>
        </Card>

        {/* Pipeline trace */}
        <Card className="shadow-sm">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">
              {selectedRfqId ? `Pipeline — RFQ #${selectedRfqId}` : "Select an RFQ"}
            </CardTitle>
          </CardHeader>
          <CardContent>
            {!selectedRfqId ? (
              <p className="text-sm text-muted-foreground py-8 text-center">
                Click an RFQ to see its pipeline trace
              </p>
            ) : trace.isLoading ? (
              <div className="space-y-3">
                {[...Array(4)].map((_, i) => (
                  <div key={i} className="h-16 bg-muted/50 rounded animate-pulse" />
                ))}
              </div>
            ) : trace.data ? (
              <div className="space-y-1">
                {/* RFQ header */}
                <div className="mb-4 pb-3 border-b">
                  <p className="text-sm font-medium">{trace.data.rfq.customer_name}</p>
                  <p className="text-xs text-muted-foreground">
                    {trace.data.rfq.origin} → {trace.data.rfq.destination}
                  </p>
                  <p className="text-xs text-muted-foreground">
                    {trace.data.summary.jobs} jobs · {trace.data.summary.agent_runs} runs · {trace.data.summary.agent_calls} calls · {trace.data.summary.approvals} approvals
                  </p>
                </div>

                {/* Pipeline stages */}
                {trace.data.pipeline.map((stage, i) => (
                  <PipelineStageRow key={i} stage={stage} isLast={i === trace.data!.pipeline.length - 1} />
                ))}

                {trace.data.pipeline.length === 0 && (
                  <p className="text-sm text-muted-foreground py-4 text-center">
                    No pipeline activity yet
                  </p>
                )}
              </div>
            ) : null}
          </CardContent>
        </Card>
      </div>
    </div>
  )
}


/** Single pipeline stage row with timeline connector. */
function PipelineStageRow({ stage, isLast }: { stage: PipelineStage; isLast: boolean }) {
  return (
    <div className="flex gap-3">
      <div className="flex flex-col items-center">
        <div className={`h-3 w-3 rounded-full mt-1 shrink-0 ${
          stage.status === "completed" || stage.status === "approved" ? "bg-green-500" :
          stage.status === "running" ? "bg-blue-500 animate-pulse" :
          stage.status === "failed" ? "bg-red-500" :
          "bg-amber-400"
        }`} />
        {!isLast && <div className="w-px flex-1 bg-border min-h-[2rem]" />}
      </div>
      <div className="pb-3 min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium">{stage.stage}</span>
          <Badge variant="secondary" className={`text-[10px] ${stageStatusColors[stage.status] ?? ""}`}>
            {stage.status}
          </Badge>
          {stage.duration_ms != null && (
            <span className="text-[10px] text-muted-foreground">
              {(stage.duration_ms / 1000).toFixed(1)}s
            </span>
          )}
          {stage.cost_usd != null && (
            <span className="text-[10px] text-muted-foreground">
              ${stage.cost_usd.toFixed(4)}
            </span>
          )}
        </div>
        <p className="text-xs text-muted-foreground mt-0.5">{stage.details}</p>
        {stage.timestamp && (
          <p className="text-[10px] text-muted-foreground">{formatRelativeTime(stage.timestamp)}</p>
        )}
      </div>
    </div>
  )
}


// ---------------------------------------------------------------------------
// Activity Log tab (#166) — unified system event stream for troubleshooting
// ---------------------------------------------------------------------------

/** Event type → icon/color mapping for the activity log */
const eventTypeStyles: Record<string, { icon: string; color: string }> = {
  email_received: { icon: "📨", color: "bg-blue-100 text-blue-800" },
  email_sent: { icon: "📤", color: "bg-green-100 text-green-800" },
  rfq_created: { icon: "📋", color: "bg-green-100 text-green-800" },
  rfq_extracted: { icon: "🔍", color: "bg-blue-100 text-blue-800" },
  state_changed: { icon: "🔄", color: "bg-purple-100 text-purple-800" },
  followup_drafted: { icon: "✏️", color: "bg-amber-100 text-amber-800" },
  approval_approved: { icon: "✅", color: "bg-green-100 text-green-800" },
  approval_rejected: { icon: "❌", color: "bg-red-100 text-red-800" },
  auto_send: { icon: "⚡", color: "bg-teal-100 text-teal-800" },
  carrier_distribution_created: { icon: "🚛", color: "bg-purple-100 text-purple-800" },
  carrier_bid_received: { icon: "💰", color: "bg-green-100 text-green-800" },
  escalated_for_review: { icon: "⚠️", color: "bg-amber-100 text-amber-800" },
  quote_sheet_generated: { icon: "📊", color: "bg-blue-100 text-blue-800" },
  customer_quote_generated: { icon: "💵", color: "bg-teal-100 text-teal-800" },
  quote_response_classified: { icon: "🤖", color: "bg-purple-100 text-purple-800" },
  clarification_requested: { icon: "❓", color: "bg-amber-100 text-amber-800" },
  message_matched: { icon: "🔗", color: "bg-blue-100 text-blue-800" },
  workflow_enabled: { icon: "🟢", color: "bg-green-100 text-green-800" },
  workflow_disabled: { icon: "🔴", color: "bg-red-100 text-red-800" },
}

const TIME_FILTERS = [
  { value: null, label: "All Time" },
  { value: "hour", label: "Last Hour" },
  { value: "today", label: "Today" },
  { value: "week", label: "This Week" },
] as const

interface ActivityEvent {
  id: number
  rfq_id: number | null
  event_type: string
  actor: string
  description: string
  event_data: Record<string, unknown> | null
  created_at: string | null
}

interface ActivityLogResponse {
  events: ActivityEvent[]
  total: number
  event_types: Record<string, number>
}

const PAGE_SIZE = 50

function ActivityLogTab() {
  const [rfqFilter, setRfqFilter] = useState("")
  const [typeFilter, setTypeFilter] = useState<string | null>(null)
  const [timeFilter, setTimeFilter] = useState<string | null>(null)
  const [page, setPage] = useState(0)

  // Debounce RFQ filter
  const [debouncedRfq, setDebouncedRfq] = useState("")
  useMemo(() => {
    const timer = setTimeout(() => setDebouncedRfq(rfqFilter), 300)
    return () => clearTimeout(timer)
  }, [rfqFilter])

  const params = new URLSearchParams()
  params.set("limit", String(PAGE_SIZE))
  params.set("offset", String(page * PAGE_SIZE))
  if (debouncedRfq) params.set("rfq_id", debouncedRfq)
  if (typeFilter) params.set("event_type", typeFilter)
  if (timeFilter) params.set("since", timeFilter)

  const log = useQuery({
    queryKey: ["admin", "activity-log", { rfq: debouncedRfq, type: typeFilter, time: timeFilter, page }],
    queryFn: () => api.get<ActivityLogResponse>(`/api/admin/activity-log?${params.toString()}`),
    refetchInterval: 10_000,
  })

  const totalPages = Math.ceil((log.data?.total ?? 0) / PAGE_SIZE)
  const eventTypes = Object.entries(log.data?.event_types ?? {}).sort((a, b) => b[1] - a[1])

  return (
    <div className="space-y-4">
      {/* Filters */}
      <div className="flex flex-col sm:flex-row gap-3">
        {/* RFQ filter */}
        <div className="relative w-full sm:w-40">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
          <input
            type="text"
            placeholder="RFQ #..."
            value={rfqFilter}
            onChange={(e) => { setRfqFilter(e.target.value.replace(/\D/g, "")); setPage(0) }}
            className="w-full pl-9 pr-3 py-1.5 text-sm border rounded-md bg-white focus:outline-none focus:ring-2 focus:ring-[#0F9ED5]/30 focus:border-[#0F9ED5]"
          />
        </div>

        {/* Time range pills */}
        <div className="flex flex-wrap gap-1.5">
          {TIME_FILTERS.map((f) => (
            <button
              key={f.value ?? "all"}
              onClick={() => { setTimeFilter(f.value); setPage(0) }}
              className={cn(
                "px-2.5 py-1 rounded-full text-[11px] font-medium border transition-colors",
                timeFilter === f.value
                  ? "bg-[#0E2841] text-white border-[#0E2841]"
                  : "bg-white text-muted-foreground border-border hover:bg-muted/50"
              )}
            >
              {f.label}
            </button>
          ))}
        </div>
      </div>

      {/* Event type filter pills */}
      {eventTypes.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          <button
            onClick={() => { setTypeFilter(null); setPage(0) }}
            className={cn(
              "px-2.5 py-1 rounded-full text-[11px] font-medium border transition-colors",
              typeFilter === null
                ? "bg-[#0F9ED5] text-white border-[#0F9ED5]"
                : "bg-white text-muted-foreground border-border hover:bg-muted/50"
            )}
          >
            All ({log.data?.total ?? 0})
          </button>
          {eventTypes.map(([type, count]) => {
            const style = eventTypeStyles[type]
            return (
              <button
                key={type}
                onClick={() => { setTypeFilter(typeFilter === type ? null : type); setPage(0) }}
                className={cn(
                  "px-2.5 py-1 rounded-full text-[11px] font-medium border transition-colors",
                  typeFilter === type
                    ? "bg-[#0F9ED5] text-white border-[#0F9ED5]"
                    : "bg-white text-muted-foreground border-border hover:bg-muted/50"
                )}
              >
                {style?.icon ?? "•"} {type.replace(/_/g, " ")} ({count})
              </button>
            )
          })}
        </div>
      )}

      {/* Event list */}
      {log.isLoading ? (
        <div className="space-y-2">
          {[...Array(8)].map((_, i) => (
            <div key={i} className="h-12 bg-white rounded animate-pulse shadow-sm" />
          ))}
        </div>
      ) : (log.data?.events.length ?? 0) === 0 ? (
        <Card className="shadow-sm">
          <CardContent className="py-8 text-center">
            <p className="text-muted-foreground">No activity found</p>
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-1.5">
          {log.data?.events.map((event) => {
            const style = eventTypeStyles[event.event_type] ?? { icon: "•", color: "bg-gray-100 text-gray-600" }
            return (
              <div key={event.id} className="flex items-start gap-3 bg-white rounded-lg shadow-sm border p-3">
                <span className="text-sm shrink-0 mt-0.5">{style.icon}</span>
                <div className="flex-1 min-w-0">
                  <p className="text-sm">{event.description}</p>
                  <div className="flex items-center gap-2 mt-1">
                    <Badge variant="secondary" className={`text-[9px] ${style.color}`}>
                      {event.event_type.replace(/_/g, " ")}
                    </Badge>
                    {event.rfq_id && (
                      <span className="text-[10px] text-[#0F9ED5] font-medium">RFQ #{event.rfq_id}</span>
                    )}
                    <span className="text-[10px] text-muted-foreground">
                      {event.actor}
                    </span>
                  </div>
                </div>
                <span className="text-[10px] text-muted-foreground shrink-0 mt-0.5">
                  {event.created_at ? formatRelativeTime(event.created_at) : "—"}
                </span>
              </div>
            )
          })}
        </div>
      )}

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-between">
          <p className="text-xs text-muted-foreground">
            Showing {page * PAGE_SIZE + 1}–{Math.min((page + 1) * PAGE_SIZE, log.data?.total ?? 0)} of {log.data?.total}
          </p>
          <div className="flex gap-2">
            <button onClick={() => setPage((p) => Math.max(0, p - 1))} disabled={page === 0} className="px-3 py-1 text-xs border rounded-md disabled:opacity-40 hover:bg-muted/50">Previous</button>
            <button onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))} disabled={page >= totalPages - 1} className="px-3 py-1 text-xs border rounded-md disabled:opacity-40 hover:bg-muted/50">Next</button>
          </div>
        </div>
      )}
    </div>
  )
}
