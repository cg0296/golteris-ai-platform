/**
 * components/dashboard/UrgentActionCard.tsx — Single urgent action row (#107).
 *
 * Displays one pending approval with its type badge, RFQ context, reason,
 * and inline action buttons. The broker can:
 * - "Send" to approve directly from the dashboard without opening the modal
 * - "Reject" to reject inline
 * - "Review" to open the full approval modal for editing
 *
 * C2 enforcement: clicking "Send" calls POST /api/approvals/{id}/approve
 * which is the HITL gate for outbound email sends. The action is still a
 * deliberate human choice (click), just without requiring the full modal.
 */

import { useState } from "react"
import { Check, X } from "lucide-react"
import { toast } from "sonner"
import { useQueryClient } from "@tanstack/react-query"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { api } from "@/lib/api"
import { formatRelativeTime } from "@/lib/utils"
import type { ApprovalItem } from "@/types/api"

/** Map approval_type values to plain-English labels (C3). */
const typeLabels: Record<string, string> = {
  customer_reply: "Customer Reply",
  carrier_rfq: "Carrier RFQ",
  customer_quote: "Customer Quote",
}

interface UrgentActionCardProps {
  approval: ApprovalItem
  onApprove: (id: number) => void
  isApproving: boolean
}

export function UrgentActionCard({
  approval,
  onApprove,
  isApproving,
}: UrgentActionCardProps) {
  const rfq = approval.rfq
  const route =
    rfq?.origin && rfq?.destination
      ? `${rfq.origin} → ${rfq.destination}`
      : null

  const [isActioning, setIsActioning] = useState<string | null>(null)
  const queryClient = useQueryClient()

  /* Quick-approve inline — sends the draft as-is without opening the modal (#107).
     C2: This is still a deliberate human action (click), fully audited. */
  const handleQuickAction = async (action: "approve" | "reject") => {
    setIsActioning(action)
    try {
      const endpoint = action === "approve" ? "approve" : "reject"
      await api.post(`/api/approvals/${approval.id}/${endpoint}`, {
        approved_by: "jillian@beltmann.com",
        reason: action === "reject" ? "Rejected from dashboard" : undefined,
      })
      queryClient.invalidateQueries({ queryKey: ["approvals"] })
      queryClient.invalidateQueries({ queryKey: ["dashboard"] })
      toast.success(
        action === "approve" ? "Approved" : "Rejected",
        { description: action === "approve" ? "Queued for sending" : "Draft rejected" }
      )
    } catch {
      toast.error(`Failed to ${action}`)
    } finally {
      setIsActioning(null)
    }
  }

  return (
    <div className="flex items-center justify-between gap-4 py-3 border-b last:border-0">
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2 mb-1">
          <Badge variant="secondary" className="text-xs shrink-0">
            {typeLabels[approval.approval_type] ?? approval.approval_type}
          </Badge>
          {rfq?.customer_name && (
            <span className="text-sm font-medium text-[#0E2841] truncate">
              {rfq.customer_name}
            </span>
          )}
        </div>
        {route && (
          <p className="text-xs text-muted-foreground truncate">{route}</p>
        )}
        {approval.reason && (
          <p className="text-xs text-muted-foreground truncate mt-0.5">
            {approval.reason}
          </p>
        )}
        <p className="text-xs text-muted-foreground mt-0.5">
          {formatRelativeTime(approval.created_at)}
        </p>
      </div>

      {/* Inline action buttons (#107) — approve/reject without opening modal */}
      <div className="flex items-center gap-1.5 shrink-0">
        <Button
          size="sm"
          onClick={() => handleQuickAction("approve")}
          disabled={isActioning !== null}
          className="bg-green-600 hover:bg-green-700 text-white h-8 px-2.5"
          title="Approve and send"
        >
          {isActioning === "approve" ? "..." : <><Check className="h-3.5 w-3.5 mr-1" /> Send</>}
        </Button>
        <Button
          size="sm"
          variant="outline"
          onClick={() => handleQuickAction("reject")}
          disabled={isActioning !== null}
          className="text-red-600 border-red-300 hover:bg-red-50 h-8 px-2.5"
          title="Reject"
        >
          {isActioning === "reject" ? "..." : <X className="h-3.5 w-3.5" />}
        </Button>
        <Button
          size="sm"
          variant="outline"
          onClick={() => onApprove(approval.id)}
          disabled={isApproving || isActioning !== null}
          className="h-8 px-2.5"
          title="Open full review"
        >
          Review
        </Button>
      </div>
    </div>
  )
}
