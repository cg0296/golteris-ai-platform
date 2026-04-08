/**
 * components/dashboard/UrgentActionCard.tsx — Single urgent action row (#107).
 *
 * Expandable card: click to reveal the draft email body. Full action set:
 * Send As-Is, Edit (inline textarea), Reject, Skip. Same actions as the
 * RFQ detail approval card.
 *
 * C2: Every action is a deliberate human choice (click), fully audited.
 * C3: Plain English labels throughout.
 */

import { useState } from "react"
import { Check, X, ChevronDown, ChevronRight } from "lucide-react"
import { toast } from "sonner"
import { useQueryClient } from "@tanstack/react-query"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { api } from "@/lib/api"
import { formatRelativeTime } from "@/lib/utils"
import type { ApprovalItem } from "@/types/api"

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

  const [isExpanded, setIsExpanded] = useState(false)
  const [isEditing, setIsEditing] = useState(false)
  const [editBody, setEditBody] = useState("")
  const [isActioning, setIsActioning] = useState<string | null>(null)
  const queryClient = useQueryClient()

  const handleAction = async (action: "approve" | "reject" | "skip", body?: string) => {
    setIsActioning(action)
    try {
      const endpoint = action === "approve" ? "approve" : action === "reject" ? "reject" : "skip"
      await api.post(`/api/approvals/${approval.id}/${endpoint}`, {
        approved_by: "operator",
        edited_body: body || undefined,
        reason: action === "reject" ? "Rejected from dashboard" : action === "skip" ? "Skipped" : undefined,
      })
      queryClient.invalidateQueries({ queryKey: ["approvals"] })
      queryClient.invalidateQueries({ queryKey: ["dashboard"] })
      setIsEditing(false)
      const msgs: Record<string, string> = {
        approve: "Approved and queued for sending",
        reject: "Rejected — will not be sent",
        skip: "Skipped — review later",
      }
      toast.success(msgs[action])
    } catch {
      toast.error(`Failed to ${action}`)
    } finally {
      setIsActioning(null)
    }
  }

  return (
    <div className="py-3 border-b last:border-0">
      {/* Header row — clickable to expand */}
      <div
        className="flex items-center justify-between gap-4 cursor-pointer hover:bg-muted/30 -mx-2 px-2 py-1 rounded"
        onClick={() => setIsExpanded(!isExpanded)}
      >
        <div className="flex items-center gap-2 min-w-0 flex-1">
          {isExpanded ? (
            <ChevronDown className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
          ) : (
            <ChevronRight className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
          )}
          <Badge variant="secondary" className="text-xs shrink-0">
            {typeLabels[approval.approval_type] ?? approval.approval_type}
          </Badge>
          {rfq?.customer_name && (
            <span className="text-sm font-medium text-[#0E2841] truncate">
              {rfq.customer_name}
            </span>
          )}
          {route && (
            <span className="text-xs text-muted-foreground truncate hidden sm:inline">
              {route}
            </span>
          )}
          <span className="text-xs text-muted-foreground ml-auto shrink-0">
            {formatRelativeTime(approval.created_at)}
          </span>
        </div>

        {/* Quick send button (always visible, no expand needed) */}
        <div className="flex items-center gap-1.5 shrink-0" onClick={(e) => e.stopPropagation()}>
          <Button
            size="sm"
            onClick={() => handleAction("approve")}
            disabled={isActioning !== null}
            className="bg-green-600 hover:bg-green-700 text-white h-8 px-2.5"
          >
            {isActioning === "approve" ? "..." : <><Check className="h-3.5 w-3.5 mr-1" /> Send</>}
          </Button>
        </div>
      </div>

      {/* Expanded content — draft body + full actions */}
      {isExpanded && (
        <div className="mt-2 ml-6 space-y-2">
          {approval.reason && (
            <p className="text-xs text-muted-foreground">{approval.reason}</p>
          )}

          {approval.draft_subject && (
            <p className="text-xs text-muted-foreground">
              To: {approval.draft_recipient} · {approval.draft_subject}
            </p>
          )}

          {/* Draft body — editable or read-only */}
          {approval.draft_body && (
            isEditing ? (
              <textarea
                value={editBody}
                onChange={(e) => setEditBody(e.target.value)}
                className="w-full text-sm border rounded p-2 min-h-[120px] resize-y focus:outline-none focus:ring-2 focus:ring-[#0F9ED5]/30"
              />
            ) : (
              <div className="text-sm whitespace-pre-wrap bg-muted/30 border rounded p-3 max-h-40 overflow-y-auto">
                {approval.draft_body}
              </div>
            )
          )}

          {/* Full action buttons */}
          <div className="flex items-center gap-1.5 pt-1">
            {isEditing ? (
              <>
                <Button
                  size="sm"
                  onClick={() => handleAction("approve", editBody)}
                  disabled={isActioning !== null}
                  className="bg-green-600 hover:bg-green-700 text-white h-8 px-3"
                >
                  {isActioning === "approve" ? "..." : <><Check className="h-3.5 w-3.5 mr-1" /> Send Edited</>}
                </Button>
                <Button size="sm" variant="outline" onClick={() => setIsEditing(false)} className="h-8 px-2">
                  Cancel
                </Button>
              </>
            ) : (
              <>
                <Button
                  size="sm"
                  onClick={() => handleAction("approve")}
                  disabled={isActioning !== null}
                  className="bg-green-600 hover:bg-green-700 text-white h-8 px-3"
                >
                  {isActioning === "approve" ? "..." : <><Check className="h-3.5 w-3.5 mr-1" /> Send As-Is</>}
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => { setIsEditing(true); setEditBody(approval.draft_body ?? "") }}
                  disabled={isActioning !== null}
                  className="h-8 px-3"
                >
                  Edit
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => handleAction("reject")}
                  disabled={isActioning !== null}
                  className="text-red-600 border-red-300 hover:bg-red-50 h-8 px-2"
                >
                  Reject
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => handleAction("skip")}
                  disabled={isActioning !== null}
                  className="text-muted-foreground h-8 px-2"
                >
                  Skip
                </Button>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
