/**
 * hooks/use-dashboard-summary.ts — React Query hook for dashboard KPI data.
 *
 * Polls GET /api/dashboard/summary every 10 seconds (inherited from the
 * QueryClient default). Powers the four KPI cards on the home dashboard.
 */

import { useQuery } from "@tanstack/react-query"
import { api } from "@/lib/api"
import type { DashboardSummary } from "@/types/api"

export function useDashboardSummary() {
  return useQuery({
    queryKey: ["dashboard", "summary"],
    queryFn: () => api.get<DashboardSummary>("/api/dashboard/summary"),
  })
}
