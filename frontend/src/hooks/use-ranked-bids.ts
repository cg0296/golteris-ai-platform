/**
 * hooks/use-ranked-bids.ts — React Query hook for ranked carrier bids (#34).
 */

import { useQuery } from "@tanstack/react-query"
import { api } from "@/lib/api"

export interface RankedBid {
  id: number
  rank: number
  carrier_name: string
  carrier_email: string | null
  rate: number | null
  normalized_rate: number
  currency: string | null
  rate_type: string | null
  terms: string | null
  availability: string | null
  notes: string | null
  tag: string
  reason: string
  received_at: string | null
}

interface RankedBidsResponse {
  rfq_id: number
  bids: RankedBid[]
  total: number
}

export function useRankedBids(rfqId: number | null) {
  return useQuery({
    queryKey: ["rfq", "bids", rfqId],
    queryFn: () => api.get<RankedBidsResponse>(`/api/rfqs/${rfqId}/bids`),
    enabled: rfqId !== null,
  })
}
