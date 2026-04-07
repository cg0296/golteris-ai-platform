/**
 * components/dashboard/MessageThreadModal.tsx — Full email thread viewer (#111).
 *
 * Opens as a large centered modal (using the center Sheet variant from #110)
 * when the broker clicks a message in the Inbox. Displays the full email
 * thread in chronological order, styled like a typical email client.
 *
 * Features:
 * - Shows each message with sender, subject, timestamp, direction badge
 * - Full message body displayed (not truncated)
 * - RFQ context shown in header if the message is attached to an RFQ
 * - Routing badge visible for each message
 * - Link to open the RFQ detail modal
 *
 * Cross-cutting constraints:
 *   C3 — All labels use plain English (routing_label from backend)
 */

import { Mail, ArrowLeft, ExternalLink } from "lucide-react"
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Separator } from "@/components/ui/separator"
import { useMessageThread, type ThreadMessage } from "@/hooks/use-message-thread"
import { formatRelativeTime } from "@/lib/utils"

/** Badge colors for routing status */
const routingColors: Record<string, string> = {
  attached: "bg-blue-100 text-blue-700",
  new_rfq: "bg-green-100 text-green-700",
  needs_review: "bg-amber-100 text-amber-800",
  ignored: "bg-gray-100 text-gray-600",
}

/** Badge colors for message direction */
const directionColors: Record<string, string> = {
  inbound: "bg-blue-100 text-blue-700",
  outbound: "bg-green-100 text-green-700",
}

interface MessageThreadModalProps {
  /** Message ID to display thread for, or null if closed. */
  messageId: number | null
  /** Called when the modal should close. */
  onClose: () => void
  /** Optional callback to open the RFQ detail modal for the attached RFQ. */
  onOpenRfq?: (rfqId: number) => void
}

export function MessageThreadModal({ messageId, onClose, onOpenRfq }: MessageThreadModalProps) {
  const { data, isLoading } = useMessageThread(messageId)
  const isOpen = messageId !== null

  return (
    <Sheet open={isOpen} onOpenChange={(open) => !open && onClose()}>
      <SheetContent side="center" className="overflow-y-auto p-0">
        {isLoading || !data ? (
          <div className="p-6 space-y-4 pt-8">
            <div className="h-8 w-48 bg-muted/50 rounded animate-pulse" />
            <div className="h-4 w-64 bg-muted/50 rounded animate-pulse" />
            <div className="h-64 bg-muted/50 rounded animate-pulse" />
          </div>
        ) : (
          <>
            {/* Header — subject, RFQ context, routing badge */}
            <SheetHeader className="p-6 pb-4 border-b bg-muted/20">
              <div className="flex items-start gap-3">
                <div className="h-10 w-10 rounded-full bg-[#0F9ED5]/10 flex items-center justify-center shrink-0 mt-0.5">
                  <Mail className="h-5 w-5 text-[#0F9ED5]" />
                </div>
                <div className="min-w-0 flex-1">
                  <SheetTitle className="text-lg leading-tight">
                    {data.message.subject || "(No subject)"}
                  </SheetTitle>
                  <div className="flex flex-wrap items-center gap-2 mt-1.5">
                    {data.message.routing_status && (
                      <Badge
                        variant="secondary"
                        className={`text-[10px] ${routingColors[data.message.routing_status] ?? ""}`}
                      >
                        {data.message.routing_label}
                      </Badge>
                    )}
                    {data.rfq && (
                      <button
                        onClick={() => {
                          if (data.rfq && onOpenRfq) {
                            onClose()
                            onOpenRfq(data.rfq.id)
                          }
                        }}
                        className="text-xs text-[#0F9ED5] hover:underline flex items-center gap-1"
                      >
                        RFQ #{data.rfq.id} — {data.rfq.customer_name}
                        {data.rfq.origin && data.rfq.destination && (
                          <span className="text-muted-foreground">
                            ({data.rfq.origin} → {data.rfq.destination})
                          </span>
                        )}
                        <ExternalLink className="h-3 w-3" />
                      </button>
                    )}
                  </div>
                  <p className="text-xs text-muted-foreground mt-1">
                    {data.thread.length} message{data.thread.length !== 1 ? "s" : ""} in thread
                  </p>
                </div>
              </div>
            </SheetHeader>

            {/* Thread — all messages in chronological order */}
            <div className="p-6 space-y-1">
              {data.thread.map((msg, idx) => (
                <ThreadMessageCard
                  key={msg.id}
                  message={msg}
                  isHighlighted={msg.id === data.message.id}
                  isLast={idx === data.thread.length - 1}
                />
              ))}
            </div>
          </>
        )}
      </SheetContent>
    </Sheet>
  )
}


/**
 * Individual message card within the thread — shows sender, direction,
 * timestamp, subject, and full body. Styled like an email client message.
 */
function ThreadMessageCard({
  message,
  isHighlighted,
  isLast,
}: {
  message: ThreadMessage
  isHighlighted: boolean
  isLast: boolean
}) {
  return (
    <div
      className={`rounded-lg border p-4 ${
        isHighlighted
          ? "border-[#0F9ED5]/40 bg-[#0F9ED5]/5 ring-1 ring-[#0F9ED5]/20"
          : "border-border"
      } ${!isLast ? "mb-3" : ""}`}
    >
      {/* Message header — sender, direction badge, timestamp */}
      <div className="flex items-center gap-2 mb-2">
        <Badge
          variant="secondary"
          className={`text-[10px] ${directionColors[message.direction] ?? ""}`}
        >
          {message.direction === "inbound" ? "Received" : "Sent"}
        </Badge>
        <span className="text-sm font-medium truncate">{message.sender}</span>
        {message.received_at && (
          <span className="text-xs text-muted-foreground ml-auto shrink-0">
            {formatRelativeTime(message.received_at)}
          </span>
        )}
      </div>

      {/* Subject line (if different from thread subject or if it's useful) */}
      {message.subject && (
        <p className="text-xs text-muted-foreground mb-2">
          {message.subject}
        </p>
      )}

      {/* Full message body */}
      <div className="text-sm whitespace-pre-wrap leading-relaxed text-foreground/90">
        {message.body}
      </div>
    </div>
  )
}
