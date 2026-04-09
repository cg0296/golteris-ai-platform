/**
 * hooks/use-carriers.ts — React Query hooks for carrier management (#32).
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { api } from "@/lib/api"

export interface CarrierItem {
  id: number
  name: string
  email: string
  contact_name: string | null
  phone: string | null
  equipment_types: string[]
  lanes: { origin: string; destination: string }[]
  preferred: boolean
}

interface CarrierListResponse {
  carriers: CarrierItem[]
  total: number
}

export function useMatchingCarriers(rfqId: number | null) {
  return useQuery({
    queryKey: ["carriers", "match", rfqId],
    queryFn: () => api.get<CarrierListResponse>(`/api/carriers/match/${rfqId}`),
    enabled: rfqId !== null,
  })
}

/** Fetch all active carriers (#168) */
export function useAllCarriers() {
  return useQuery({
    queryKey: ["carriers", "all"],
    queryFn: () => api.get<CarrierListResponse>("/api/carriers"),
  })
}

export function useDistributeRfq() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (params: { rfqId: number; carrierIds: number[]; attachQuoteSheet?: boolean }) =>
      api.post(`/api/rfqs/${params.rfqId}/distribute`, {
        carrier_ids: params.carrierIds,
        attach_quote_sheet: params.attachQuoteSheet ?? false,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["approvals"] })
      queryClient.invalidateQueries({ queryKey: ["dashboard"] })
      queryClient.invalidateQueries({ queryKey: ["activity"] })
      queryClient.invalidateQueries({ queryKey: ["rfq", "detail"] })
    },
  })
}
