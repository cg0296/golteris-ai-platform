/**
 * hooks/use-approval-detail.ts — React Query hook for full approval detail.
 *
 * Fetches GET /api/approvals/{id} when the approval modal opens.
 * Returns the full draft body, reason, RFQ context, and original message
 * needed for the "SHIPPER WROTE" / "AGENT DRAFTED" modal sections.
 */

import { useQuery } from "@tanstack/react-query"
import { api } from "@/lib/api"
import type { ApprovalDetail } from "@/types/api"

export function useApprovalDetail(approvalId: number | null) {
  return useQuery({
    queryKey: ["approval", "detail", approvalId],
    queryFn: () => api.get<ApprovalDetail>(`/api/approvals/${approvalId}`),
    enabled: approvalId !== null,
  })
}
