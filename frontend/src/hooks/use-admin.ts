/**
 * hooks/use-admin.ts — React Query hooks for admin panel (#131).
 */

import { useQuery, useMutation } from "@tanstack/react-query"
import { api } from "@/lib/api"

export interface ProcessInfo {
  name: string
  status: string
  pid: number | null
  last_activity?: string | null
  uptime?: string | null
}

export interface ProcessesResponse {
  processes: ProcessInfo[]
  jobs: { pending: number; running: number }
  checked_at: string
}

export interface PipelineStage {
  stage: string
  status: string
  timestamp: string | null
  duration_ms?: number | null
  cost_usd?: number | null
  details: string
}

export interface PipelineTrace {
  rfq: {
    id: number
    customer_name: string
    customer_company: string | null
    origin: string | null
    destination: string | null
    state: string
    created_at: string | null
  }
  pipeline: PipelineStage[]
  summary: {
    total_stages: number
    messages: number
    jobs: number
    agent_runs: number
    agent_calls: number
    approvals: number
    events: number
  }
}

export interface PipelineSearchResult {
  id: number
  customer_name: string
  customer_company: string | null
  origin: string | null
  destination: string | null
  state: string
  created_at: string | null
  pipeline_counts: { jobs: number; runs: number; approvals: number }
}

export function useProcesses() {
  return useQuery({
    queryKey: ["admin", "processes"],
    queryFn: () => api.get<ProcessesResponse>("/api/admin/processes"),
    refetchInterval: 5_000,
  })
}

export function useRestartWorker() {
  return useMutation({
    mutationFn: () => api.post<{ status: string; message: string; pid?: number }>("/api/admin/restart-worker"),
  })
}

export function usePipelineTrace(rfqId: number | null) {
  return useQuery({
    queryKey: ["admin", "pipeline", rfqId],
    queryFn: () => api.get<PipelineTrace>(`/api/admin/pipeline/${rfqId}`),
    enabled: rfqId !== null,
  })
}

export function usePipelineSearch(search: string, state?: string) {
  const params = new URLSearchParams()
  if (search) params.set("search", search)
  if (state) params.set("state", state)
  return useQuery({
    queryKey: ["admin", "pipeline", "search", search, state],
    queryFn: () => api.get<{ rfqs: PipelineSearchResult[]; total: number }>(`/api/admin/pipeline?${params}`),
  })
}
