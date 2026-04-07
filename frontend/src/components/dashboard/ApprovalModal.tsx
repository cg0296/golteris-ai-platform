/**
 * components/dashboard/ApprovalModal.tsx — Full approval modal (#26).
 *
 * Displays when the broker clicks an urgent action. Shows:
 * - "SHIPPER WROTE" — the original inbound message
 * - "AGENT DRAFTED" — the draft email body (editable in edit mode)
 * - Reason flag — why this was flagged for review
 * - Four action buttons: Send As-Is, Edit, Reject, Skip
 * - Keyboard shortcuts: Enter=approve, E=edit, R=reject, S=skip, Esc=close
 *
 * FR-HI-2: Modal shows original message, drafted reply, reason flag, 4 actions.
 * FR-HI-3: Keyboard shortcuts for mouse-free queue clearing.
 * FR-HI-4: Any item clearable in under 10 seconds.
 * FR-HI-5: State updates propagate without page reload (React Query invalidation).
 *
 * C2 — Every action here is a deliberate human choice (click or keypress).
 * C3 — All labels use plain English (no agent jargon).
 */

import { useCallback, useEffect, useRef, useState } from "react"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Textarea } from "@/components/ui/textarea"
import { useApprovalDetail } from "@/hooks/use-approval-detail"
import {
  useApproveApproval,
  useRejectApproval,
  useSkipApproval,
} from "@/hooks/use-approval-actions"
import { formatRelativeTime } from "@/lib/utils"
import type { ApprovalItem } from "@/types/api"

/** Map approval_type values to plain-English labels (C3). */
const typeLabels: Record<string, string> = {
  customer_reply: "Customer Reply",
  carrier_rfq: "Carrier RFQ",
  customer_quote: "Customer Quote",
}

interface ApprovalModalProps {
  /** The approval to display, or null if modal is closed. */
  approval: ApprovalItem | null
  /** Called when the modal should close. */
  onClose: () => void
  /** Called after any action to advance to the next item in the queue. */
  onActionComplete: (action: "approve" | "reject" | "skip") => void
  /** Navigate to the next pending approval in the queue (J key). */
  onNext: () => void
  /** Navigate to the previous pending approval in the queue (K key). */
  onPrev: () => void
}

export function ApprovalModal({
  approval,
  onClose,
  onActionComplete,
  onNext,
  onPrev,
}: ApprovalModalProps) {
  const [editMode, setEditMode] = useState(false)
  const [editedBody, setEditedBody] = useState("")
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  // Fetch full detail (draft body, original message) when modal opens
  const detail = useApprovalDetail(approval?.id ?? null)
  const approveMutation = useApproveApproval()
  const rejectMutation = useRejectApproval()
  const skipMutation = useSkipApproval()

  const isOpen = approval !== null
  const isLoading = detail.isLoading
  const data = detail.data
  const isBusy =
    approveMutation.isPending ||
    rejectMutation.isPending ||
    skipMutation.isPending

  // Reset edit mode when a new approval is opened
  useEffect(() => {
    setEditMode(false)
    setEditedBody("")
  }, [approval?.id])

  // When entering edit mode, populate textarea with current draft
  useEffect(() => {
    if (editMode && data?.draft_body) {
      setEditedBody(data.draft_body)
      // Focus the textarea after a brief delay for the DOM to update
      setTimeout(() => textareaRef.current?.focus(), 50)
    }
  }, [editMode, data?.draft_body])

  // Handle the four approval actions
  const handleApprove = useCallback(() => {
    if (!approval || isBusy) return
    const body = editMode ? editedBody : undefined
    approveMutation.mutate(
      { id: approval.id, resolved_body: body },
      { onSuccess: () => onActionComplete("approve") }
    )
  }, [approval, isBusy, editMode, editedBody, approveMutation, onActionComplete])

  const handleReject = useCallback(() => {
    if (!approval || isBusy) return
    rejectMutation.mutate(approval.id, {
      onSuccess: () => onActionComplete("reject"),
    })
  }, [approval, isBusy, rejectMutation, onActionComplete])

  const handleSkip = useCallback(() => {
    if (!approval || isBusy) return
    skipMutation.mutate(approval.id, {
      onSuccess: () => onActionComplete("skip"),
    })
  }, [approval, isBusy, skipMutation, onActionComplete])

  const handleEdit = useCallback(() => {
    setEditMode(true)
  }, [])

  // Keyboard shortcuts (FR-HI-3)
  useEffect(() => {
    if (!isOpen) return

    const handler = (e: KeyboardEvent) => {
      // Don't intercept when typing in the edit textarea
      const target = e.target as HTMLElement
      if (target.tagName === "TEXTAREA" || target.tagName === "INPUT") {
        // Only allow Escape and Ctrl+Enter in edit mode
        if (e.key === "Escape") {
          e.preventDefault()
          if (editMode) {
            setEditMode(false)
          } else {
            onClose()
          }
        } else if (e.key === "Enter" && (e.ctrlKey || e.metaKey) && editMode) {
          e.preventDefault()
          handleApprove()
        }
        return
      }

      switch (e.key) {
        case "Enter":
          e.preventDefault()
          handleApprove()
          break
        case "e":
        case "E":
          e.preventDefault()
          handleEdit()
          break
        case "r":
        case "R":
          e.preventDefault()
          handleReject()
          break
        case "s":
        case "S":
          e.preventDefault()
          handleSkip()
          break
        case "j":
        case "J":
          e.preventDefault()
          onNext()
          break
        case "k":
        case "K":
          e.preventDefault()
          onPrev()
          break
        case "Escape":
          e.preventDefault()
          if (editMode) {
            setEditMode(false)
          } else {
            onClose()
          }
          break
      }
    }

    window.addEventListener("keydown", handler)
    return () => window.removeEventListener("keydown", handler)
  }, [
    isOpen, editMode, handleApprove, handleReject, handleSkip, handleEdit,
    onClose, onNext, onPrev,
  ])

  if (!approval) return null

  return (
    <Dialog open={isOpen} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <div className="flex items-center gap-2 mb-1">
            <Badge variant="secondary" className="text-xs">
              {typeLabels[approval.approval_type] ?? approval.approval_type}
            </Badge>
            <span className="text-xs text-muted-foreground">
              {formatRelativeTime(approval.created_at)}
            </span>
          </div>
          <DialogTitle className="text-lg">
            {approval.rfq?.customer_name ?? "Unknown Customer"}
            {approval.rfq?.origin && approval.rfq?.destination && (
              <span className="text-sm font-normal text-muted-foreground ml-2">
                {approval.rfq.origin} → {approval.rfq.destination}
              </span>
            )}
          </DialogTitle>
        </DialogHeader>

        {isLoading ? (
          <div className="space-y-4 py-4">
            <div className="h-24 bg-muted/50 rounded animate-pulse" />
            <div className="h-32 bg-muted/50 rounded animate-pulse" />
          </div>
        ) : (
          <div className="space-y-4 py-2">
            {/* SHIPPER WROTE section */}
            {data?.original_message && (
              <div>
                <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2">
                  Shipper Wrote
                </p>
                <div className="bg-muted/30 border rounded-lg p-3">
                  <p className="text-xs text-muted-foreground mb-1">
                    From: {data.original_message.sender}
                  </p>
                  {data.original_message.subject && (
                    <p className="text-xs text-muted-foreground mb-2">
                      Subject: {data.original_message.subject}
                    </p>
                  )}
                  <p className="text-sm whitespace-pre-wrap">
                    {data.original_message.body}
                  </p>
                </div>
              </div>
            )}

            {/* AGENT DRAFTED section */}
            <div>
              <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2">
                Agent Drafted
              </p>
              {editMode ? (
                <Textarea
                  ref={textareaRef}
                  value={editedBody}
                  onChange={(e) => setEditedBody(e.target.value)}
                  className="min-h-[160px] text-sm"
                  placeholder="Edit the draft..."
                />
              ) : (
                <div className="bg-blue-50 border border-blue-200 rounded-lg p-3">
                  {data?.draft_subject && (
                    <p className="text-xs text-muted-foreground mb-1">
                      To: {data.draft_recipient}
                    </p>
                  )}
                  {data?.draft_subject && (
                    <p className="text-xs text-muted-foreground mb-2">
                      Subject: {data.draft_subject}
                    </p>
                  )}
                  <p className="text-sm whitespace-pre-wrap">
                    {data?.draft_body ?? "Loading..."}
                  </p>
                </div>
              )}
            </div>

            {/* Reason flag */}
            {(data?.reason || approval.reason) && (
              <div className="bg-amber-50 border border-amber-200 rounded-lg px-3 py-2 flex items-start gap-2">
                <span className="text-amber-600 text-sm mt-0.5">⚠</span>
                <p className="text-sm text-amber-800">
                  {data?.reason ?? approval.reason}
                </p>
              </div>
            )}

            {/* Action buttons */}
            <div className="flex flex-wrap gap-2 pt-2">
              <Button
                onClick={handleApprove}
                disabled={isBusy}
                className="bg-[#0F9ED5] hover:bg-[#0B7FAD] text-white"
              >
                {editMode ? "Send Edited" : "Send As-Is"}
              </Button>
              {!editMode && (
                <Button variant="outline" onClick={handleEdit} disabled={isBusy}>
                  Edit
                </Button>
              )}
              {editMode && (
                <Button
                  variant="outline"
                  onClick={() => setEditMode(false)}
                  disabled={isBusy}
                >
                  Cancel Edit
                </Button>
              )}
              <Button
                variant="outline"
                onClick={handleReject}
                disabled={isBusy}
                className="text-red-600 hover:text-red-700 hover:bg-red-50"
              >
                Reject
              </Button>
              <Button variant="outline" onClick={handleSkip} disabled={isBusy}>
                Skip
              </Button>
            </div>

            {/* Keyboard shortcuts hint */}
            <div className="text-xs text-muted-foreground pt-1 flex flex-wrap gap-x-3 gap-y-1">
              <span>
                <kbd className="px-1.5 py-0.5 bg-muted rounded text-[10px] font-mono">
                  {editMode ? "Ctrl+Enter" : "Enter"}
                </kbd>{" "}
                Approve
              </span>
              {!editMode && (
                <span>
                  <kbd className="px-1.5 py-0.5 bg-muted rounded text-[10px] font-mono">E</kbd>{" "}
                  Edit
                </span>
              )}
              <span>
                <kbd className="px-1.5 py-0.5 bg-muted rounded text-[10px] font-mono">R</kbd>{" "}
                Reject
              </span>
              <span>
                <kbd className="px-1.5 py-0.5 bg-muted rounded text-[10px] font-mono">S</kbd>{" "}
                Skip
              </span>
              <span>
                <kbd className="px-1.5 py-0.5 bg-muted rounded text-[10px] font-mono">J</kbd>/
                <kbd className="px-1.5 py-0.5 bg-muted rounded text-[10px] font-mono">K</kbd>{" "}
                Next/Prev
              </span>
              <span>
                <kbd className="px-1.5 py-0.5 bg-muted rounded text-[10px] font-mono">Esc</kbd>{" "}
                Close
              </span>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}
