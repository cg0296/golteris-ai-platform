/**
 * components/dashboard/UrgentActionCard.tsx — Single urgent action row.
 *
 * Displays one pending approval with its type badge, RFQ context, reason,
 * and an inline "Approve" button. The broker can approve directly from the
 * dashboard without opening a full modal.
 *
 * C2 enforcement: clicking "Approve" calls POST /api/approvals/{id}/approve
 * which is the HITL gate for outbound email sends.
 */

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
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

      <Button
        size="sm"
        onClick={() => onApprove(approval.id)}
        disabled={isApproving}
        className="shrink-0 bg-[#0F9ED5] hover:bg-[#0B7FAD] text-white"
      >
        {isApproving ? "Approving..." : "Approve"}
      </Button>
    </div>
  )
}
