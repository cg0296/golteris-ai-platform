/**
 * pages/DashboardPage.tsx — Broker home dashboard (#17, #26).
 *
 * The default landing page showing four zones:
 * 1. KPI strip — Needs Review, Active RFQs, Quotes Received, Time Saved
 * 2. Urgent Actions — Pending approvals with inline buttons that open the modal
 * 3. Active RFQs table — 6-row preview with "View all" link
 * 4. Activity feed — Recent audit events with live indicator
 *
 * The approval modal (#26) opens when clicking an urgent action. It supports
 * four actions (Send As-Is, Edit, Reject, Skip) with keyboard shortcuts
 * (Enter, E, R, S, J/K, Esc) for mouse-free queue clearing (FR-HI-3).
 *
 * Cross-cutting constraints:
 *   C2 — All approval actions are deliberate human choices (click or keypress)
 *   C3 — All state labels are plain English (provided by backend)
 *   C5 — Time Saved uses defensible agent run durations
 */

import { useCallback, useState } from "react"
import { toast } from "sonner"
import { KpiStrip } from "@/components/dashboard/KpiStrip"
import { UrgentActions } from "@/components/dashboard/UrgentActions"
import { ActiveRfqsTable } from "@/components/dashboard/ActiveRfqsTable"
import { ActivityFeed } from "@/components/dashboard/ActivityFeed"
import { ApprovalModal } from "@/components/dashboard/ApprovalModal"
import { RfqDetailDrawer } from "@/components/dashboard/RfqDetailDrawer"
import { useDashboardSummary } from "@/hooks/use-dashboard-summary"
import { useActiveRfqs } from "@/hooks/use-active-rfqs"
import { usePendingApprovals } from "@/hooks/use-pending-approvals"
import { useRecentActivity } from "@/hooks/use-recent-activity"
import type { ApprovalItem } from "@/types/api"

/** Toast messages for each approval action (C3 — plain English). */
const actionToasts: Record<string, { title: string; description: string }> = {
  approve: { title: "Approved", description: "Draft approved and queued for sending" },
  reject: { title: "Rejected", description: "Draft rejected — it will not be sent" },
  skip: { title: "Skipped", description: "Draft skipped — you can review it later" },
}

export function DashboardPage() {
  const summary = useDashboardSummary()
  const rfqs = useActiveRfqs()
  const approvals = usePendingApprovals()
  const activity = useRecentActivity()

  // Approval modal state — which approval is currently open
  const [selectedApproval, setSelectedApproval] = useState<ApprovalItem | null>(null)

  // RFQ detail drawer state — which RFQ ID is open (#27)
  const [selectedRfqId, setSelectedRfqId] = useState<number | null>(null)

  // Open the approval modal when clicking an urgent action
  const handleOpenApproval = useCallback(
    (id: number) => {
      const found = approvals.data?.approvals.find((a) => a.id === id)
      if (found) setSelectedApproval(found)
    },
    [approvals.data]
  )

  // After an action, show toast and close (or advance to next)
  const handleActionComplete = useCallback(
    (action: "approve" | "reject" | "skip") => {
      const msg = actionToasts[action]
      toast.success(msg.title, { description: msg.description })
      setSelectedApproval(null)
    },
    []
  )

  // J/K queue navigation — cycle through pending approvals
  const handleNext = useCallback(() => {
    const list = approvals.data?.approvals ?? []
    if (list.length === 0) return
    const currentIdx = list.findIndex((a) => a.id === selectedApproval?.id)
    const nextIdx = (currentIdx + 1) % list.length
    setSelectedApproval(list[nextIdx])
  }, [approvals.data, selectedApproval])

  const handlePrev = useCallback(() => {
    const list = approvals.data?.approvals ?? []
    if (list.length === 0) return
    const currentIdx = list.findIndex((a) => a.id === selectedApproval?.id)
    const prevIdx = currentIdx <= 0 ? list.length - 1 : currentIdx - 1
    setSelectedApproval(list[prevIdx])
  }, [approvals.data, selectedApproval])

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

      {/* Urgent Actions — clicking opens the approval modal */}
      <UrgentActions
        approvals={approvals.data?.approvals ?? []}
        total={approvals.data?.total ?? 0}
        isLoading={approvals.isLoading}
        onApprove={handleOpenApproval}
        approvingId={null}
      />

      {/* Bottom row: Active RFQs table + Activity feed */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <ActiveRfqsTable
          rfqs={rfqs.data?.rfqs ?? []}
          total={rfqs.data?.total ?? 0}
          isLoading={rfqs.isLoading}
          onRowClick={(id) => setSelectedRfqId(id)}
        />
        <ActivityFeed
          events={activity.data?.events ?? []}
          isLoading={activity.isLoading}
          onEventClick={(rfqId) => rfqId && setSelectedRfqId(rfqId)}
        />
      </div>

      {/* Approval modal (#26) */}
      <ApprovalModal
        approval={selectedApproval}
        onClose={() => setSelectedApproval(null)}
        onActionComplete={handleActionComplete}
        onNext={handleNext}
        onPrev={handlePrev}
      />

      {/* RFQ detail drawer (#27) */}
      <RfqDetailDrawer
        rfqId={selectedRfqId}
        onClose={() => setSelectedRfqId(null)}
      />
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
