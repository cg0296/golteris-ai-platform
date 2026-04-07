/**
 * hooks/use-quote-sheet.ts — React Query hook for quote sheet data.
 */

import { useQuery } from "@tanstack/react-query"
import { api } from "@/lib/api"

export interface QuoteSheetData {
  rfq_id: number
  customer_name: string | null
  customer_company: string | null
  quote_sheet: Record<string, unknown>
}

export function useQuoteSheet(rfqId: number | null) {
  return useQuery({
    queryKey: ["rfq", "quote-sheet", rfqId],
    queryFn: () => api.get<QuoteSheetData>(`/api/rfqs/${rfqId}/quote-sheet`),
    enabled: rfqId !== null,
    retry: false,
  })
}
