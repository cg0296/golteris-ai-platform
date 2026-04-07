/**
 * hooks/use-approve-action.ts — React Query mutation for inline approval.
 *
 * POST /api/approvals/{id}/approve — flips a pending approval to approved.
 * On success, invalidates dashboard queries so KPI counts refresh immediately
 * (acceptance criterion: "KPI counts update when state changes downstream").
 */

import { useMutation, useQueryClient } from "@tanstack/react-query"
import { api } from "@/lib/api"

export function useApproveAction() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: number) =>
      api.post(`/api/approvals/${id}/approve`, { resolved_by: "broker" }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["dashboard"] })
      queryClient.invalidateQueries({ queryKey: ["approvals"] })
      queryClient.invalidateQueries({ queryKey: ["activity"] })
    },
  })
}
