/**
 * hooks/use-pending-approvals.ts — React Query hook for the Urgent Actions panel.
 *
 * Polls GET /api/approvals?status=pending_approval every 10 seconds.
 * Each approval includes nested RFQ context for display.
 */

import { useQuery } from "@tanstack/react-query"
import { api } from "@/lib/api"
import type { ApprovalListResponse } from "@/types/api"

export function usePendingApprovals() {
  return useQuery({
    queryKey: ["approvals", "pending"],
    queryFn: () =>
      api.get<ApprovalListResponse>("/api/approvals?status=pending_approval"),
  })
}
