/**
 * hooks/use-settings.ts — React Query hooks for Settings page (#31).
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { api } from "@/lib/api"

export interface WorkflowItem {
  id: number
  name: string
  enabled: boolean
  updated_at: string | null
}

interface WorkflowListResponse {
  workflows: WorkflowItem[]
}

interface SystemStatus {
  cost_caps: { daily: number; monthly: number }
  mailbox: { provider: string; email: string; connected: boolean }
  workflows: { total: number; enabled: number }
}

export function useWorkflows() {
  return useQuery({
    queryKey: ["workflows"],
    queryFn: () => api.get<WorkflowListResponse>("/api/workflows"),
  })
}

export function useSystemStatus() {
  return useQuery({
    queryKey: ["settings", "status"],
    queryFn: () => api.get<SystemStatus>("/api/settings/status"),
  })
}

export function useToggleWorkflow() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (params: { id: number; enabled: boolean }) =>
      fetch(`${import.meta.env.DEV ? "http://localhost:8001" : ""}/api/workflows/${params.id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled: params.enabled }),
      }).then(r => r.json()),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["workflows"] })
      queryClient.invalidateQueries({ queryKey: ["settings"] })
    },
  })
}

export function useKillSwitch() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => api.post("/api/workflows/kill"),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["workflows"] })
      queryClient.invalidateQueries({ queryKey: ["settings"] })
    },
  })
}

// --- Agent Controls (#44) ---

export interface AgentConfig {
  name: string
  description: string
  enabled: boolean
  model: string
}

interface AgentControlsResponse {
  agents: Record<string, AgentConfig>
  models: { id: string; name: string; provider: string }[]
  cost_caps: { daily: number; monthly: number }
}

export function useAgentControls() {
  return useQuery({
    queryKey: ["settings", "agents"],
    queryFn: () => api.get<AgentControlsResponse>("/api/settings/agents"),
  })
}

export function useUpdateAgent() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (params: { agent_id: string; enabled?: boolean; model?: string }) =>
      fetch(`${import.meta.env.DEV ? "http://localhost:8001" : ""}/api/settings/agents`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(params),
      }).then(r => r.json()),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["settings", "agents"] })
    },
  })
}
