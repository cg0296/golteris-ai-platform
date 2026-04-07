/**
 * hooks/use-active-rfqs.ts — React Query hook for the active RFQs table.
 *
 * Polls GET /api/rfqs every 10 seconds. Default limit=6 for the dashboard
 * preview table; the full RFQs page can pass a higher limit.
 */

import { useQuery } from "@tanstack/react-query"
import { api } from "@/lib/api"
import type { RfqListResponse } from "@/types/api"

export function useActiveRfqs(limit = 6) {
  return useQuery({
    queryKey: ["rfqs", "active", limit],
    queryFn: () => api.get<RfqListResponse>(`/api/rfqs?limit=${limit}`),
  })
}
