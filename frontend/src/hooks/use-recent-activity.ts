/**
 * hooks/use-recent-activity.ts — React Query hook for the activity feed.
 *
 * Polls GET /api/activity/recent every 10 seconds.
 * Events arrive in reverse chronological order with plain-English descriptions.
 */

import { useQuery } from "@tanstack/react-query"
import { api } from "@/lib/api"
import type { ActivityResponse } from "@/types/api"

export function useRecentActivity() {
  return useQuery({
    queryKey: ["activity", "recent"],
    queryFn: () => api.get<ActivityResponse>("/api/activity/recent"),
  })
}
