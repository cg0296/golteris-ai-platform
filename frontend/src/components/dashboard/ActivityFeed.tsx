/**
 * components/dashboard/ActivityFeed.tsx — Recent activity feed for the dashboard.
 *
 * Shows the most recent audit events in reverse chronological order.
 * Each event has a colored icon (based on event_type), a human-readable
 * description (C3), and a relative timestamp. The feed auto-refreshes
 * every 10 seconds via React Query polling.
 *
 * Filter pills let the operator narrow the feed by category (C3 — plain
 * language labels, not internal event_type strings).
 */

import { useState } from "react"
import { Activity } from "lucide-react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { ActivityRow } from "./ActivityRow"
import type { ActivityEvent } from "@/types/api"

/** Activity filter categories with the event_types that belong to each. */
const FILTERS = [
  { label: "All", key: "all", types: null },
  { label: "RFQs", key: "rfqs", types: ["rfq_created", "state_changed", "extraction_completed", "quote_response_classified"] },
  { label: "Approvals", key: "approvals", types: ["approval_approved", "approval_created", "escalated_for_review"] },
  { label: "Emails", key: "emails", types: ["email_sent", "email_received", "clarification_sent"] },
  { label: "Agent", key: "agent", types: ["agent_call", "validation_completed", "quote_sheet_generated", "carrier_bid_parsed", "additional_question"] },
] as const

type FilterKey = typeof FILTERS[number]["key"]

function matchesFilter(event: ActivityEvent, filterKey: FilterKey): boolean {
  if (filterKey === "all") return true
  const filter = FILTERS.find((f) => f.key === filterKey)
  if (!filter || !filter.types) return true
  return (filter.types as readonly string[]).includes(event.event_type)
}

interface ActivityFeedProps {
  events: ActivityEvent[]
  isLoading: boolean
  /** Called when an event is clicked — opens the RFQ detail drawer (#27). */
  onEventClick?: (rfqId: number | null) => void
}

export function ActivityFeed({ events, isLoading, onEventClick }: ActivityFeedProps) {
  const [activeFilter, setActiveFilter] = useState<FilterKey>("all")
  const filtered = activeFilter === "all" ? events : events.filter((e) => matchesFilter(e, activeFilter))

  return (
    <Card className="shadow-sm">
      <CardHeader className="pb-2">
        <CardTitle className="text-base font-semibold flex items-center gap-2">
          <Activity className="h-4 w-4 text-[#0F9ED5]" />
          Recent Activity
          <span className="relative flex h-2 w-2 ml-1">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-green-400 opacity-75" />
            <span className="relative inline-flex h-2 w-2 rounded-full bg-green-500" />
          </span>
        </CardTitle>
        {/* Filter pills */}
        <div className="flex gap-1.5 mt-2 flex-wrap">
          {FILTERS.map((f) => (
            <button
              key={f.key}
              onClick={() => setActiveFilter(f.key)}
              className={`px-2.5 py-0.5 rounded-full text-xs font-medium transition-colors ${
                activeFilter === f.key
                  ? "bg-[#0F9ED5] text-white"
                  : "bg-muted text-muted-foreground hover:bg-muted/80"
              }`}
            >
              {f.label}
            </button>
          ))}
        </div>
      </CardHeader>
      <CardContent className="pt-0">
        {isLoading ? (
          <div className="space-y-3">
            {[...Array(5)].map((_, i) => (
              <div key={i} className="h-12 bg-muted/50 rounded animate-pulse" />
            ))}
          </div>
        ) : filtered.length === 0 ? (
          <p className="text-sm text-muted-foreground py-4 text-center">
            {activeFilter === "all" ? "No recent activity" : "No matching activity"}
          </p>
        ) : (
          <div className="max-h-[400px] overflow-y-auto">
            {filtered.map((event) => (
              <ActivityRow
                key={event.id}
                event={event}
                onClick={() => onEventClick?.(event.rfq_id)}
              />
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  )
}
