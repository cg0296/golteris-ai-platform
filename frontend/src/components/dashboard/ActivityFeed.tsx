/**
 * components/dashboard/ActivityFeed.tsx — Recent activity feed for the dashboard.
 *
 * Shows the most recent audit events in reverse chronological order.
 * Each event has a colored icon (based on event_type), a human-readable
 * description (C3), and a relative timestamp. The feed auto-refreshes
 * every 10 seconds via React Query polling.
 */

import { Activity } from "lucide-react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { ActivityRow } from "./ActivityRow"
import type { ActivityEvent } from "@/types/api"

interface ActivityFeedProps {
  events: ActivityEvent[]
  isLoading: boolean
}

export function ActivityFeed({ events, isLoading }: ActivityFeedProps) {
  return (
    <Card className="shadow-sm">
      <CardHeader className="pb-3">
        <CardTitle className="text-base font-semibold flex items-center gap-2">
          <Activity className="h-4 w-4 text-[#0F9ED5]" />
          Recent Activity
          <span className="relative flex h-2 w-2 ml-1">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-green-400 opacity-75" />
            <span className="relative inline-flex h-2 w-2 rounded-full bg-green-500" />
          </span>
        </CardTitle>
      </CardHeader>
      <CardContent className="pt-0">
        {isLoading ? (
          <div className="space-y-3">
            {[...Array(5)].map((_, i) => (
              <div key={i} className="h-12 bg-muted/50 rounded animate-pulse" />
            ))}
          </div>
        ) : events.length === 0 ? (
          <p className="text-sm text-muted-foreground py-4 text-center">
            No recent activity
          </p>
        ) : (
          <div className="max-h-[400px] overflow-y-auto">
            {events.map((event) => (
              <ActivityRow key={event.id} event={event} />
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  )
}
