/**
 * hooks/use-approval-actions.ts — React Query mutations for all approval actions.
 *
 * Provides approve (with optional edit), reject, and skip mutations.
 * All three invalidate dashboard/approvals/activity queries on success
 * so KPI counts and the activity feed refresh immediately (FR-HI-5).
 *
 * resolved_by sends the logged-in user's email so outbound emails
 * are signed by the person who approved them (#159).
 */

import { useMutation, useQueryClient } from "@tanstack/react-query"
import { api } from "@/lib/api"
import { useAuth } from "@/lib/auth"

/** Invalidate all dashboard-related queries after any approval action. */
function useInvalidateOnSuccess() {
  const queryClient = useQueryClient()
  return () => {
    queryClient.invalidateQueries({ queryKey: ["dashboard"] })
    queryClient.invalidateQueries({ queryKey: ["approvals"] })
    queryClient.invalidateQueries({ queryKey: ["activity"] })
    queryClient.invalidateQueries({ queryKey: ["approval", "detail"] })
  }
}

export function useApproveApproval() {
  const onSuccess = useInvalidateOnSuccess()
  const { user } = useAuth()
  return useMutation({
    mutationFn: (params: { id: number; resolved_body?: string }) =>
      api.post(`/api/approvals/${params.id}/approve`, {
        resolved_by: user?.email ?? "broker",
        resolved_body: params.resolved_body ?? null,
      }),
    onSuccess,
  })
}

export function useRejectApproval() {
  const onSuccess = useInvalidateOnSuccess()
  const { user } = useAuth()
  return useMutation({
    mutationFn: (id: number) =>
      api.post(`/api/approvals/${id}/reject`, { resolved_by: user?.email ?? "broker" }),
    onSuccess,
  })
}

export function useSkipApproval() {
  const onSuccess = useInvalidateOnSuccess()
  const { user } = useAuth()
  return useMutation({
    mutationFn: (id: number) =>
      api.post(`/api/approvals/${id}/skip`, { resolved_by: user?.email ?? "broker" }),
    onSuccess,
  })
}
