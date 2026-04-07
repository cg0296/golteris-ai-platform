/**
 * hooks/use-history.ts — React Query hook for the History view (#30).
 *
 * Fetches GET /api/history with stats and closed RFQs.
 */

import { useQuery } from "@tanstack/react-query"
import { api } from "@/lib/api"

export interface HistoryRfq {
  id: number
  customer_name: string | null
  customer_company: string | null
  origin: string | null
  destination: string | null
  equipment_type: string | null
  state: string
  state_label: string
  outcome: string | null
  quoted_amount: number | null
  cycle_hours: number | null
  closed_at: string | null
  created_at: string
}

export interface HistoryStats {
  completed_today: number
  avg_time_to_quote_hours: number
  approvals_this_week: number
  time_saved_hours: number
}

interface HistoryResponse {
  stats: HistoryStats
  rfqs: HistoryRfq[]
  total: number
  limit: number
  offset: number
}

interface HistoryParams {
  limit?: number
  offset?: number
  outcome?: string | null
  period?: string | null
}

export function useHistory({
  limit = 50,
  offset = 0,
  outcome = null,
  period = null,
}: HistoryParams) {
  const params = new URLSearchParams()
  params.set("limit", limit.toString())
  params.set("offset", offset.toString())
  if (outcome) params.set("outcome", outcome)
  if (period) params.set("period", period)

  return useQuery({
    queryKey: ["history", { limit, offset, outcome, period }],
    queryFn: () => api.get<HistoryResponse>(`/api/history?${params.toString()}`),
  })
}
