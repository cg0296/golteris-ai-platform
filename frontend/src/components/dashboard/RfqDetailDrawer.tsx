/**
 * components/dashboard/RfqDetailDrawer.tsx — RFQ detail drawer (#27).
 *
 * A right-sliding sheet that opens when the broker clicks an RFQ row
 * anywhere in the app (Home, RFQs list, Inbox, History, Activity feed).
 *
 * Four sections per FR-UI-5:
 * 1. Summary — route, equipment, dates, contact (definition list)
 * 2. Current Status — state pill, allowed transitions, confidence
 * 3. Messages — inbound/outbound email thread
 * 4. Actions & History — audit event timeline
 *
 * Cross-cutting constraints:
 *   C3 — All labels use plain English (state_label from backend)
 *   C4 — Timeline shows every action; "View system reasoning" disclosure
 */

import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet"
import { Badge } from "@/components/ui/badge"
import { Separator } from "@/components/ui/separator"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { useRfqDetail } from "@/hooks/use-rfq-detail"
import { formatRelativeTime } from "@/lib/utils"
import type { RfqDetail, RfqMessage, ActivityEvent, CarrierBidItem } from "@/types/api"

/** Map RFQ state values to badge color classes. */
const stateColors: Record<string, string> = {
  needs_clarification: "bg-amber-100 text-amber-800",
  ready_to_quote: "bg-blue-100 text-blue-800",
  waiting_on_carriers: "bg-purple-100 text-purple-800",
  quotes_received: "bg-green-100 text-green-800",
  waiting_on_broker: "bg-red-100 text-red-800",
  quote_sent: "bg-teal-100 text-teal-800",
  won: "bg-green-200 text-green-900",
  lost: "bg-gray-100 text-gray-600",
  cancelled: "bg-gray-100 text-gray-600",
}

interface RfqDetailDrawerProps {
  /** RFQ ID to display, or null if drawer is closed. */
  rfqId: number | null
  /** Called when the drawer should close. */
  onClose: () => void
}

export function RfqDetailDrawer({ rfqId, onClose }: RfqDetailDrawerProps) {
  const { data, isLoading } = useRfqDetail(rfqId)
  const isOpen = rfqId !== null

  return (
    <Sheet open={isOpen} onOpenChange={(open) => !open && onClose()}>
      <SheetContent className="w-full sm:max-w-2xl overflow-y-auto p-6">
        {isLoading || !data ? (
          <div className="space-y-4 pt-8">
            <div className="h-8 w-48 bg-muted/50 rounded animate-pulse" />
            <div className="h-4 w-32 bg-muted/50 rounded animate-pulse" />
            <div className="h-64 bg-muted/50 rounded animate-pulse" />
          </div>
        ) : (
          <>
            <SheetHeader className="pb-4">
              <div className="flex items-center gap-2 mb-1">
                <span className="text-xs font-mono text-muted-foreground">
                  #{data.id}
                </span>
                <Badge
                  variant="secondary"
                  className={`text-xs ${stateColors[data.state] ?? ""}`}
                >
                  {data.state_label}
                </Badge>
              </div>
              <SheetTitle className="text-lg">
                {data.customer_name ?? "Unknown Customer"}
                {data.customer_company && (
                  <span className="text-sm font-normal text-muted-foreground ml-2">
                    {data.customer_company}
                  </span>
                )}
              </SheetTitle>
              {data.origin && data.destination && (
                <p className="text-sm text-muted-foreground">
                  {data.origin} → {data.destination}
                </p>
              )}
            </SheetHeader>

            <Tabs defaultValue="summary" className="mt-2">
              <TabsList className="grid w-full grid-cols-4">
                <TabsTrigger value="summary" className="text-xs">Summary</TabsTrigger>
                <TabsTrigger value="status" className="text-xs">Status</TabsTrigger>
                <TabsTrigger value="messages" className="text-xs">
                  Messages
                  {data.messages.length > 0 && (
                    <span className="ml-1 text-muted-foreground">
                      ({data.messages.length})
                    </span>
                  )}
                </TabsTrigger>
                <TabsTrigger value="timeline" className="text-xs">Timeline</TabsTrigger>
              </TabsList>

              {/* --- Summary tab --- */}
              <TabsContent value="summary" className="mt-4">
                <SummarySection data={data} />
              </TabsContent>

              {/* --- Current Status tab --- */}
              <TabsContent value="status" className="mt-4">
                <StatusSection data={data} />
              </TabsContent>

              {/* --- Messages tab --- */}
              <TabsContent value="messages" className="mt-4">
                <MessagesSection messages={data.messages} />
              </TabsContent>

              {/* --- Timeline tab --- */}
              <TabsContent value="timeline" className="mt-4">
                <TimelineSection events={data.timeline} />
              </TabsContent>
            </Tabs>

            {/* Carrier bids (shown if any exist) */}
            {data.carrier_bids.length > 0 && (
              <div className="mt-6">
                <Separator className="mb-4" />
                <BidsSection bids={data.carrier_bids} />
              </div>
            )}
          </>
        )}
      </SheetContent>
    </Sheet>
  )
}


// ---------------------------------------------------------------------------
// Section components
// ---------------------------------------------------------------------------


/** Summary tab — definition list of all extracted RFQ fields. */
function SummarySection({ data }: { data: RfqDetail }) {
  const fields = [
    ["Customer", data.customer_name],
    ["Company", data.customer_company],
    ["Email", data.customer_email],
    ["Origin", data.origin],
    ["Destination", data.destination],
    ["Equipment", data.equipment_type],
    ["Truck Count", data.truck_count?.toString()],
    ["Commodity", data.commodity],
    ["Weight", data.weight_lbs ? `${data.weight_lbs.toLocaleString()} lbs` : null],
    ["Pickup Date", data.pickup_date ? new Date(data.pickup_date).toLocaleDateString() : null],
    ["Delivery Date", data.delivery_date ? new Date(data.delivery_date).toLocaleDateString() : null],
    ["Special Requirements", data.special_requirements],
    ["Created", formatRelativeTime(data.created_at)],
    ["Last Updated", formatRelativeTime(data.updated_at)],
  ].filter(([, val]) => val != null)

  return (
    <div className="grid grid-cols-2 gap-x-6 gap-y-4">
      {fields.map(([label, value]) => (
        <div key={label as string}>
          <p className="text-xs text-muted-foreground uppercase tracking-wider mb-0.5">
            {label}
          </p>
          <p className="text-sm font-medium break-words">{value}</p>
        </div>
      ))}
    </div>
  )
}


/** Status tab — current state, allowed transitions, confidence scores. */
function StatusSection({ data }: { data: RfqDetail }) {
  return (
    <div className="space-y-4">
      {/* Current state */}
      <div>
        <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2">
          Current State
        </p>
        <Badge
          variant="secondary"
          className={`text-sm ${stateColors[data.state] ?? ""}`}
        >
          {data.state_label}
        </Badge>
      </div>

      {/* Allowed next steps */}
      {data.allowed_transitions.length > 0 && (
        <div>
          <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2">
            Next Steps
          </p>
          <div className="flex flex-wrap gap-2">
            {data.allowed_transitions.map((t) => (
              <Badge key={t.state} variant="outline" className="text-xs">
                {t.label}
              </Badge>
            ))}
          </div>
        </div>
      )}

      {/* Confidence scores (if available) */}
      {data.confidence_scores && Object.keys(data.confidence_scores).length > 0 && (
        <div>
          <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2">
            Extraction Confidence
          </p>
          <div className="space-y-1.5">
            {Object.entries(data.confidence_scores).map(([field, score]) => (
              <div key={field} className="flex items-center gap-2">
                <span className="text-xs text-muted-foreground w-24 capitalize">
                  {field.replace("_", " ")}
                </span>
                <div className="flex-1 h-2 bg-muted rounded-full overflow-hidden">
                  <div
                    className={`h-full rounded-full ${
                      score >= 0.9 ? "bg-green-500" : score >= 0.7 ? "bg-amber-500" : "bg-red-500"
                    }`}
                    style={{ width: `${Math.round(score * 100)}%` }}
                  />
                </div>
                <span className="text-xs font-mono w-10 text-right">
                  {Math.round(score * 100)}%
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Outcome (for closed RFQs) */}
      {data.outcome && (
        <div>
          <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2">
            Outcome
          </p>
          <p className="text-sm capitalize">{data.outcome}</p>
          {data.quoted_amount && (
            <p className="text-sm text-muted-foreground">
              Quoted: ${data.quoted_amount.toLocaleString()}
            </p>
          )}
        </div>
      )}
    </div>
  )
}


/** Messages tab — chronological email thread with direction tags. */
function MessagesSection({ messages }: { messages: RfqMessage[] }) {
  if (messages.length === 0) {
    return (
      <p className="text-sm text-muted-foreground py-4 text-center">
        No messages yet
      </p>
    )
  }

  return (
    <div className="space-y-4">
      {messages.map((msg) => (
        <div key={msg.id} className="border rounded-lg p-3">
          <div className="flex items-center gap-2 mb-2">
            <Badge
              variant="secondary"
              className={`text-[10px] ${
                msg.direction === "inbound"
                  ? "bg-blue-100 text-blue-700"
                  : "bg-green-100 text-green-700"
              }`}
            >
              {msg.direction === "inbound" ? "IN" : "OUT"}
            </Badge>
            <span className="text-xs font-medium">{msg.sender}</span>
            {msg.received_at && (
              <span className="text-xs text-muted-foreground ml-auto">
                {formatRelativeTime(msg.received_at)}
              </span>
            )}
          </div>
          {msg.subject && (
            <p className="text-xs text-muted-foreground mb-1">
              Subject: {msg.subject}
            </p>
          )}
          <p className="text-sm whitespace-pre-wrap">{msg.body}</p>
        </div>
      ))}
    </div>
  )
}


/** Timeline tab — audit events in reverse chronological order. */
function TimelineSection({ events }: { events: ActivityEvent[] }) {
  if (events.length === 0) {
    return (
      <p className="text-sm text-muted-foreground py-4 text-center">
        No events recorded
      </p>
    )
  }

  return (
    <div className="space-y-3">
      {events.map((event) => (
        <div key={event.id} className="flex gap-3">
          <div className="flex flex-col items-center">
            <div className="h-2 w-2 rounded-full bg-[#0F9ED5] mt-1.5 shrink-0" />
            {/* Vertical line connecting timeline dots */}
            <div className="w-px flex-1 bg-border" />
          </div>
          <div className="pb-3 min-w-0">
            <p className="text-sm">{event.description}</p>
            <div className="flex items-center gap-2 mt-0.5">
              <span className="text-xs text-muted-foreground">
                {event.created_at ? formatRelativeTime(event.created_at) : ""}
              </span>
              {event.actor !== "system" && (
                <span className="text-xs text-muted-foreground">
                  by {event.actor}
                </span>
              )}
            </div>
          </div>
        </div>
      ))}
    </div>
  )
}


/** Carrier bids section — shown below tabs when bids exist. */
function BidsSection({ bids }: { bids: CarrierBidItem[] }) {
  return (
    <div>
      <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-3">
        Carrier Bids ({bids.length})
      </p>
      <div className="space-y-2">
        {bids.map((bid) => (
          <div
            key={bid.id}
            className="flex items-center justify-between border rounded-lg p-3"
          >
            <div>
              <p className="text-sm font-medium">{bid.carrier_name}</p>
              {bid.terms && (
                <p className="text-xs text-muted-foreground">{bid.terms}</p>
              )}
            </div>
            <div className="text-right">
              {bid.rate && (
                <p className="text-sm font-bold text-[#0E2841]">
                  ${bid.rate.toLocaleString()}
                </p>
              )}
              {bid.received_at && (
                <p className="text-xs text-muted-foreground">
                  {formatRelativeTime(bid.received_at)}
                </p>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
