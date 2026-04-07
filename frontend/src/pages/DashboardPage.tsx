/**
 * pages/DashboardPage.tsx — Broker home dashboard (#17).
 *
 * The default landing page showing four zones:
 * 1. KPI strip — Needs Review, Active RFQs, Quotes Received, Time Saved
 * 2. Urgent Actions — Pending approvals with inline approve buttons
 * 3. Active RFQs table — 6-row preview with "View all" link
 * 4. Activity feed — Recent audit events with live indicator
 *
 * All data is fetched via React Query hooks with 10-second polling.
 * Approving an action invalidates all queries so KPIs refresh immediately.
 *
 * Cross-cutting constraints:
 *   C2 — Approve button gates outbound sends (calls POST /api/approvals/{id}/approve)
 *   C3 — All state labels are plain English (provided by backend)
 *   C5 — Time Saved uses defensible agent run durations
 */

import { useState } from "react"
import { KpiStrip } from "@/components/dashboard/KpiStrip"
import { UrgentActions } from "@/components/dashboard/UrgentActions"
import { ActiveRfqsTable } from "@/components/dashboard/ActiveRfqsTable"
import { ActivityFeed } from "@/components/dashboard/ActivityFeed"
import { useDashboardSummary } from "@/hooks/use-dashboard-summary"
import { useActiveRfqs } from "@/hooks/use-active-rfqs"
import { usePendingApprovals } from "@/hooks/use-pending-approvals"
import { useRecentActivity } from "@/hooks/use-recent-activity"
import { useApproveAction } from "@/hooks/use-approve-action"

export function DashboardPage() {
  const summary = useDashboardSummary()
  const rfqs = useActiveRfqs()
  const approvals = usePendingApprovals()
  const activity = useRecentActivity()
  const approve = useApproveAction()
  const [approvingId, setApprovingId] = useState<number | null>(null)

  const handleApprove = (id: number) => {
    setApprovingId(id)
    approve.mutate(id, {
      onSettled: () => setApprovingId(null),
    })
  }

  return (
    <div className="p-4 lg:p-6 space-y-6 max-w-7xl">
      {/* Welcome banner */}
      <div>
        <h2 className="text-xl font-semibold text-[#0E2841]">
          Good {getGreeting()}, Jillian
        </h2>
        <p className="text-sm text-muted-foreground mt-1">
          {summary.data
            ? `${summary.data.needs_review} items need your review, ${summary.data.active_rfqs} RFQs in progress`
            : "Loading your dashboard..."}
        </p>
      </div>

      {/* KPI strip — 4 cards */}
      <KpiStrip data={summary.data} isLoading={summary.isLoading} />

      {/* Urgent Actions */}
      <UrgentActions
        approvals={approvals.data?.approvals ?? []}
        total={approvals.data?.total ?? 0}
        isLoading={approvals.isLoading}
        onApprove={handleApprove}
        approvingId={approvingId}
      />

      {/* Bottom row: Active RFQs table + Activity feed */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <ActiveRfqsTable
          rfqs={rfqs.data?.rfqs ?? []}
          total={rfqs.data?.total ?? 0}
          isLoading={rfqs.isLoading}
        />
        <ActivityFeed
          events={activity.data?.events ?? []}
          isLoading={activity.isLoading}
        />
      </div>
    </div>
  )
}

/** Return a time-appropriate greeting based on the current hour. */
function getGreeting(): string {
  const hour = new Date().getHours()
  if (hour < 12) return "morning"
  if (hour < 17) return "afternoon"
  return "evening"
}
