/**
 * hooks/use-system-status.ts — Polls worker status for the top bar indicator (#157).
 */

import { useQuery } from "@tanstack/react-query"
import { api } from "@/lib/api"

interface ProcessesResponse {
  processes: Array<{ name: string; status: string; last_activity: string | null }>
  jobs: { pending: number; running: number }
  checked_at: string
}

export type SystemState = "processing" | "idle" | "stuck"

export interface SystemStatus {
  state: SystemState
  label: string
  detail: string
}

function deriveStatus(data: ProcessesResponse): SystemStatus {
  const { pending, running } = data.jobs
  const worker = data.processes.find((p) => p.name === "Background Worker")
  const workerStatus = worker?.status ?? "stopped"
  const lastActivity = worker?.last_activity ? new Date(worker.last_activity) : null
  const now = new Date()
  const staleSec = lastActivity ? (now.getTime() - lastActivity.getTime()) / 1000 : Infinity

  // Stuck: worker stopped, or running jobs with no recent progress
  if (workerStatus === "stopped" || (running > 0 && staleSec > 120)) {
    const ago = lastActivity
      ? `${Math.round(staleSec / 60)} min ago`
      : "no recent activity"
    return {
      state: "stuck",
      label: "Stuck",
      detail: running > 0
        ? `${running} job(s) stuck — last activity ${ago}`
        : `Worker may be down — ${ago}`,
    }
  }

  // Processing: jobs actively running or pending
  if (running > 0 || pending > 0) {
    const total = running + pending
    return {
      state: "processing",
      label: "Processing",
      detail: `${total} job(s) ${running > 0 ? "processing" : "queued"}`,
    }
  }

  // Idle: nothing to do
  return {
    state: "idle",
    label: "Idle",
    detail: "All caught up",
  }
}

export function useSystemStatus() {
  const query = useQuery({
    queryKey: ["system-status"],
    queryFn: () => api.get<ProcessesResponse>("/api/admin/processes"),
    refetchInterval: 10_000,
    retry: false,
  })

  const status: SystemStatus = query.data
    ? deriveStatus(query.data)
    : { state: "idle", label: "Connecting...", detail: "Checking system status" }

  return { ...status, isLoading: query.isLoading, isError: query.isError }
}
