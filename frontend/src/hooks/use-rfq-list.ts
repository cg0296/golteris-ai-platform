/**
 * hooks/use-rfq-list.ts — React Query hooks for the full RFQs list page (#29).
 *
 * Provides:
 * - useRfqList: paginated RFQ list with state filter and search
 * - useRfqCounts: state counts for filter pill badges
 */

import { useQuery } from "@tanstack/react-query"
import { api } from "@/lib/api"
import type { RfqListResponse } from "@/types/api"

interface RfqListParams {
  limit?: number
  offset?: number
  state?: string | null
  search?: string
  includeTerminal?: boolean
}

export function useRfqList({
  limit = 50,
  offset = 0,
  state = null,
  search = "",
  includeTerminal = true,
}: RfqListParams) {
  const params = new URLSearchParams()
  params.set("limit", limit.toString())
  params.set("offset", offset.toString())
  if (state) params.set("state", state)
  if (search) params.set("search", search)
  if (includeTerminal) params.set("include_terminal", "true")

  return useQuery({
    queryKey: ["rfqs", "list", { limit, offset, state, search, includeTerminal }],
    queryFn: () => api.get<RfqListResponse>(`/api/rfqs?${params.toString()}`),
  })
}

export function useRfqCounts() {
  return useQuery({
    queryKey: ["rfqs", "counts"],
    queryFn: () => api.get<{ counts: Record<string, number> }>("/api/rfqs/counts"),
  })
}
