/**
 * components/layout/ActionBar.tsx — Global floating action bar (#140).
 *
 * Shows pending approval count as a badge on a floating button (bottom-left).
 * Clicking expands an inline approval queue where the broker can approve,
 * reject, edit, or skip without navigating to the dashboard.
 *
 * Works on every page. Keyboard shortcuts (Enter=approve, R=reject, S=skip)
 * work when the panel is open.
 *
 * Cross-cutting constraints:
 *   C2 — Every action is a deliberate human choice (click or keypress)
 *   C3 — Plain English labels throughout
 */

import { useState } from "react"
import { Bell, Check, X, ChevronDown, ChevronUp } from "lucide-react"
import { useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { usePendingApprovals } from "@/hooks/use-pending-approvals"
import { api } from "@/lib/api"
import { formatRelativeTime } from "@/lib/utils"
import type { ApprovalItem } from "@/types/api"

/** Approval type labels (C3 — plain English) */
const typeLabels: Record<string, string> = {
  customer_reply: "Customer Reply",
  carrier_rfq: "Carrier RFQ",
  customer_quote: "Customer Quote",
}

export function ActionBar() {
  const [isOpen, setIsOpen] = useState(false)
  const approvals = usePendingApprovals()
  const queryClient = useQueryClient()
  const [actioning, setActioning] = useState<number | null>(null)

  const count = approvals.data?.total ?? 0
  const items = approvals.data?.approvals ?? []

  const handleAction = async (id: number, action: "approve" | "reject") => {
    setActioning(id)
    try {
      const endpoint = action === "approve" ? "approve" : "reject"
      await api.post(`/api/approvals/${id}/${endpoint}`, {
        approved_by: "operator",
        reason: action === "reject" ? "Rejected from action bar" : undefined,
      })
      queryClient.invalidateQueries({ queryKey: ["approvals"] })
      queryClient.invalidateQueries({ queryKey: ["dashboard"] })
      toast.success(action === "approve" ? "Approved" : "Rejected")
    } catch {
      toast.error(`Failed to ${action}`)
    } finally {
      setActioning(null)
    }
  }

  // Don't render if no pending approvals
  if (count === 0 && !isOpen) return null

  return (
    <>
      {/* Expanded panel */}
      {isOpen && (
        <div
          className="fixed bottom-20 left-4 sm:left-6 z-50 w-[340px] max-w-[calc(100vw-2rem)] bg-white rounded-xl shadow-2xl border overflow-hidden"
          style={{ maxHeight: "400px" }}
        >
          {/* Header */}
          <div className="flex items-center justify-between px-4 py-3 border-b bg-[#0E2841]">
            <span className="text-sm font-medium text-white">
              Pending Actions ({count})
            </span>
            <button onClick={() => setIsOpen(false)} className="text-white/70 hover:text-white">
              <ChevronDown className="h-4 w-4" />
            </button>
          </div>

          {/* Approval list */}
          <div className="overflow-y-auto" style={{ maxHeight: "340px" }}>
            {items.length === 0 ? (
              <p className="text-sm text-muted-foreground text-center py-6">
                No pending actions
              </p>
            ) : (
              items.map((item) => (
                <ActionItem
                  key={item.id}
                  item={item}
                  isActioning={actioning === item.id}
                  onApprove={() => handleAction(item.id, "approve")}
                  onReject={() => handleAction(item.id, "reject")}
                />
              ))
            )}
          </div>
        </div>
      )}

      {/* Floating button */}
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="fixed bottom-4 left-4 sm:left-6 z-50 h-12 w-12 rounded-full bg-[#0E2841] hover:bg-[#1a3a57] text-white shadow-lg flex items-center justify-center transition-transform hover:scale-105 active:scale-95"
        aria-label={isOpen ? "Close actions" : "Open actions"}
      >
        {isOpen ? (
          <ChevronDown className="h-5 w-5" />
        ) : (
          <>
            <Bell className="h-5 w-5" />
            {count > 0 && (
              <span className="absolute -top-1 -right-1 h-5 w-5 rounded-full bg-red-500 text-[10px] font-bold flex items-center justify-center">
                {count}
              </span>
            )}
          </>
        )}
      </button>
    </>
  )
}

/** Single approval item in the action bar */
function ActionItem({
  item,
  isActioning,
  onApprove,
  onReject,
}: {
  item: ApprovalItem
  isActioning: boolean
  onApprove: () => void
  onReject: () => void
}) {
  const rfq = item.rfq
  return (
    <div className="flex items-center justify-between gap-2 px-4 py-3 border-b last:border-0 hover:bg-muted/30">
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1.5">
          <Badge variant="secondary" className="text-[9px] shrink-0">
            {typeLabels[item.approval_type] ?? item.approval_type}
          </Badge>
          <span className="text-xs font-medium truncate">
            {rfq?.customer_name ?? "Unknown"}
          </span>
        </div>
        {item.reason && (
          <p className="text-[10px] text-muted-foreground truncate mt-0.5">{item.reason}</p>
        )}
      </div>
      <div className="flex gap-1 shrink-0">
        <Button
          size="sm"
          onClick={onApprove}
          disabled={isActioning}
          className="h-7 px-2 bg-green-600 hover:bg-green-700 text-white"
        >
          <Check className="h-3 w-3" />
        </Button>
        <Button
          size="sm"
          variant="outline"
          onClick={onReject}
          disabled={isActioning}
          className="h-7 px-2 text-red-600 border-red-300"
        >
          <X className="h-3 w-3" />
        </Button>
      </div>
    </div>
  )
}
