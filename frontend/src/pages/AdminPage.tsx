/**
 * pages/AdminPage.tsx — Admin panel (#131).
 *
 * Two tabs:
 * 1. Process Manager — view running processes, restart worker, see job queue
 * 2. Pipeline Tracker — search for any RFQ and see its full pipeline trace
 *
 * Only accessible to users with admin role.
 */

import { useState } from "react"
import { Shield, RefreshCw, Search, ChevronRight, Circle } from "lucide-react"
import { toast } from "sonner"
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
import { formatRelativeTime } from "@/lib/utils"

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

      <Tabs defaultValue="processes">
        <TabsList className="grid w-full grid-cols-2 max-w-md">
          <TabsTrigger value="processes" className="text-xs">Process Manager</TabsTrigger>
          <TabsTrigger value="pipeline" className="text-xs">Pipeline Tracker</TabsTrigger>
        </TabsList>

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
