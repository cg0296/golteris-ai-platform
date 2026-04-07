/**
 * hooks/use-agent-runs.ts — React Query hooks for agent observability (#38).
 */

import { useQuery } from "@tanstack/react-query"
import { api } from "@/lib/api"

export interface AgentRunItem {
  id: number
  rfq_id: number | null
  workflow_id: number | null
  workflow_name: string
  trigger: string | null
  status: string
  started_at: string | null
  finished_at: string | null
  duration_ms: number | null
  total_cost_usd: number
  total_input_tokens: number
  total_output_tokens: number
}

export interface AgentCallItem {
  id: number
  agent_name: string
  provider: string
  model: string
  status: string
  input_tokens: number
  output_tokens: number
  cost_usd: number
  started_at: string | null
  finished_at: string | null
  duration_ms: number | null
  system_prompt: string | null
  user_prompt: string | null
  response: string | null
  error_message: string | null
}

interface RunListResponse {
  runs: AgentRunItem[]
  total: number
  limit: number
  offset: number
}

interface RunDetailResponse {
  run: AgentRunItem
  calls: AgentCallItem[]
  call_count: number
}

export function useAgentRuns(params?: { status?: string; limit?: number }) {
  const searchParams = new URLSearchParams()
  if (params?.status) searchParams.set("status", params.status)
  searchParams.set("limit", String(params?.limit ?? 50))

  return useQuery({
    queryKey: ["agent", "runs", params],
    queryFn: () => api.get<RunListResponse>(`/api/agent/runs?${searchParams.toString()}`),
  })
}

export function useAgentRunDetail(runId: number | null) {
  return useQuery({
    queryKey: ["agent", "run", runId],
    queryFn: () => api.get<RunDetailResponse>(`/api/agent/runs/${runId}`),
    enabled: runId !== null,
  })
}
