/**
 * hooks/use-rfq-detail.ts — React Query hook for full RFQ detail.
 *
 * Fetches GET /api/rfqs/{id} when the RFQ detail drawer opens.
 * Returns all four sections: summary, messages, timeline, bids.
 * Polling is disabled for detail views — data is fetched once on open.
 */

import { useQuery } from "@tanstack/react-query"
import { api } from "@/lib/api"
import type { RfqDetail } from "@/types/api"

export function useRfqDetail(rfqId: number | null) {
  return useQuery({
    queryKey: ["rfq", "detail", rfqId],
    queryFn: () => api.get<RfqDetail>(`/api/rfqs/${rfqId}`),
    enabled: rfqId !== null,
    refetchInterval: false,
  })
}
