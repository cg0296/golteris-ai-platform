/**
 * components/dashboard/RfqDetailDrawer.tsx — RFQ detail modal (#27, #110).
 *
 * A large centered modal that opens when the broker clicks an RFQ row
 * anywhere in the app (Home, RFQs list, Inbox, History, Activity feed).
 * Replaced the narrow right-side drawer with a near-full-screen panel
 * to give more room for details, timelines, and actions (#110).
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

import { useState, useEffect, useCallback } from "react"
import { useQueryClient, useQuery } from "@tanstack/react-query"
import { toast } from "sonner"
import { Send, FileText, Mail, ChevronDown, ChevronRight, Check, X, AlertCircle, Download, RefreshCw, MessageSquare } from "lucide-react"
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Separator } from "@/components/ui/separator"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { CarrierSelectModal } from "./CarrierSelectModal"
import { PipelineProgress } from "./PipelineProgress"
import { useRfqDetail } from "@/hooks/use-rfq-detail"
import { api } from "@/lib/api"
import { useRankedBids, type RankedBid } from "@/hooks/use-ranked-bids"
import { useQuoteSheet } from "@/hooks/use-quote-sheet"
import { formatRelativeTime } from "@/lib/utils"
import type { RfqDetail, RfqMessage, ActivityEvent, CarrierBidItem } from "@/types/api"

/** Map RFQ state values to badge color classes. */
const stateColors: Record<string, string> = {
  inquiry: "bg-sky-100 text-sky-800",
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
  /** Ordered list of RFQ IDs for J/K navigation (#112). Optional — if omitted, J/K is disabled. */
  rfqIds?: number[]
  /** Called to navigate to a different RFQ (J/K keys). Falls back to onClose's parent setter. */
  onSelectRfq?: (id: number) => void
}

export function RfqDetailDrawer({ rfqId, onClose, rfqIds, onSelectRfq }: RfqDetailDrawerProps) {
  const { data, isLoading } = useRfqDetail(rfqId)
  const rankedBids = useRankedBids(rfqId)
  const quoteSheet = useQuoteSheet(rfqId)
  const isOpen = rfqId !== null
  const [carrierModalRfqId, setCarrierModalRfqId] = useState<number | null>(null)
  const [showQuoteSheet, setShowQuoteSheet] = useState(true)

  /* J/K keyboard navigation — move to prev/next RFQ in the list (#112).
     Only active when the modal is open and rfqIds are provided. */
  const handleKeyNav = useCallback(
    (e: KeyboardEvent) => {
      if (!rfqId || !rfqIds?.length || !onSelectRfq) return
      /* Don't intercept if user is typing in an input/textarea */
      const tag = (e.target as HTMLElement)?.tagName
      if (tag === "INPUT" || tag === "TEXTAREA") return

      const idx = rfqIds.indexOf(rfqId)
      if (idx === -1) return

      if (e.key === "j" || e.key === "J") {
        /* J = next RFQ (down the list) */
        const next = rfqIds[idx + 1]
        if (next != null) onSelectRfq(next)
      } else if (e.key === "k" || e.key === "K") {
        /* K = previous RFQ (up the list) */
        const prev = rfqIds[idx - 1]
        if (prev != null) onSelectRfq(prev)
      }
    },
    [rfqId, rfqIds, onSelectRfq]
  )

  useEffect(() => {
    if (!isOpen) return
    window.addEventListener("keydown", handleKeyNav)
    return () => window.removeEventListener("keydown", handleKeyNav)
  }, [isOpen, handleKeyNav])

  return (
    <Sheet open={isOpen} onOpenChange={(open) => !open && onClose()}>
      <SheetContent side="center" className="flex flex-col overflow-hidden p-0" showCloseButton={false}>
        {isLoading || !data ? (
          <div className="space-y-4 p-6 pt-8">
            <div className="h-8 w-48 bg-muted/50 rounded animate-pulse" />
            <div className="h-4 w-32 bg-muted/50 rounded animate-pulse" />
            <div className="h-64 bg-muted/50 rounded animate-pulse" />
          </div>
        ) : (
          <>
            {/* Sticky header — stays visible while content scrolls (#157) */}
            <SheetHeader className="sticky top-0 z-10 bg-white border-b pb-3 pr-10">
              <div className="flex items-center gap-2 mb-1">
                <span className="text-xs font-mono text-muted-foreground">
                  {data.ref_number ?? `#${data.id}`}
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
              {/* Close button — fixed in header */}
              <button
                onClick={onClose}
                className="absolute top-3 right-3 rounded-sm opacity-70 ring-offset-background transition-opacity hover:opacity-100"
              >
                <X className="h-4 w-4" />
                <span className="sr-only">Close</span>
              </button>
            </SheetHeader>

            {/* Scrollable body */}
            <div className="flex-1 overflow-y-auto px-6 pb-6">

            {/* Pipeline progress indicator (#139) — shows at a glance where this RFQ is */}
            <PipelineProgress state={data.state} createdAt={data.created_at} />

            {/* Pending actions for this RFQ — approve/reject inline */}
            <RfqPendingActions rfqId={data.id} />

            {/* Reply actions — available in all non-terminal states (#156) */}
            {!["won", "lost", "cancelled"].includes(data.state) && (
              <RfqReplyActions rfqId={data.id} customerEmail={data.customer_email} customerName={data.customer_name} />
            )}

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
                <SummarySection data={data} messages={data.messages} />
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

            {/* Ranked carrier bids (#34) — shown if any bids exist */}
            {(rankedBids.data?.total ?? 0) > 0 && (
              <div className="mt-6">
                <Separator className="mb-4" />
                <RankedBidsSection bids={rankedBids.data?.bids ?? []} rfqId={data.id} />
              </div>
            )}

            {/* Quote Sheet — shown if one was generated */}
            {quoteSheet.data && (
              <div className="mt-6">
                <Separator className="mb-4" />
                <div className="space-y-3">
                  <div className="flex items-center justify-between">
                    <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
                      Quote Sheet
                    </p>
                    <div className="flex gap-2">
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => {
                          fetch(`/api/rfqs/${rfqId}/quote-sheet/download`)
                            .then(res => res.blob())
                            .then(blob => {
                              const url = URL.createObjectURL(blob)
                              const a = document.createElement("a")
                              a.href = url
                              a.download = `RFQ-${rfqId}_quote_sheet.xlsx`
                              a.click()
                              URL.revokeObjectURL(url)
                            })
                        }}
                      >
                        <Download className="h-3.5 w-3.5 mr-1.5" />
                        Download Excel
                      </Button>
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => setShowQuoteSheet(!showQuoteSheet)}
                      >
                        <FileText className="h-3.5 w-3.5 mr-1.5" />
                        {showQuoteSheet ? "Hide" : "View Quote Sheet"}
                      </Button>
                    </div>
                  </div>
                  {showQuoteSheet && (
                    <div className="bg-muted/30 border rounded-lg p-4 text-sm space-y-2">
                      {(() => {
                        const qs = quoteSheet.data.quote_sheet as Record<string, unknown>
                        if (qs.raw) {
                          return <pre className="text-xs whitespace-pre-wrap">{String(qs.raw)}</pre>
                        }
                        return (
                          <>
                            {qs.reference_id && (
                              <p className="font-mono text-xs text-muted-foreground">Ref: {String(qs.reference_id)}</p>
                            )}
                            {qs.summary && (
                              <p className="font-medium">{String(qs.summary)}</p>
                            )}
                            {Array.isArray(qs.lanes) && qs.lanes.map((lane: Record<string, unknown>, i: number) => (
                              <div key={i} className="grid grid-cols-2 gap-x-4 gap-y-1 pt-2 border-t">
                                {lane.origin && <div><span className="text-xs text-muted-foreground">Origin:</span> <span>{String(lane.origin)}</span></div>}
                                {lane.destination && <div><span className="text-xs text-muted-foreground">Dest:</span> <span>{String(lane.destination)}</span></div>}
                                {lane.equipment && <div><span className="text-xs text-muted-foreground">Equipment:</span> <span>{String(lane.equipment)}</span></div>}
                                {lane.truck_count && <div><span className="text-xs text-muted-foreground">Trucks:</span> <span>{String(lane.truck_count)}</span></div>}
                                {lane.commodity && <div><span className="text-xs text-muted-foreground">Commodity:</span> <span>{String(lane.commodity)}</span></div>}
                                {lane.weight_lbs && <div><span className="text-xs text-muted-foreground">Weight:</span> <span>{Number(lane.weight_lbs).toLocaleString()} lbs</span></div>}
                                {lane.pickup_date && <div><span className="text-xs text-muted-foreground">Pickup:</span> <span>{String(lane.pickup_date)}</span></div>}
                              </div>
                            ))}
                            {qs.special_requirements && (
                              <div className="pt-2 border-t">
                                <span className="text-xs text-muted-foreground">Special:</span>
                                <p>{String(qs.special_requirements)}</p>
                              </div>
                            )}
                            {!qs.reference_id && !qs.summary && !Array.isArray(qs.lanes) && (
                              <pre className="text-xs whitespace-pre-wrap text-muted-foreground">{JSON.stringify(qs, null, 2)}</pre>
                            )}
                          </>
                        )
                      })()}
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* RFQ Actions (#156) — available in non-terminal states */}
            {!["won", "lost", "cancelled"].includes(data.state) && (
              <div className="mt-6">
                <Separator className="mb-4" />
                <div className="space-y-2">
                  {/* Send to Carriers — available from ready_to_quote onward */}
                  {["ready_to_quote", "waiting_on_carriers", "quotes_received", "waiting_on_broker", "quote_sent"].includes(data.state) && (
                    <Button
                      onClick={() => setCarrierModalRfqId(data.id)}
                      className="w-full bg-[#0F9ED5] hover:bg-[#0B7FAD] text-white"
                    >
                      <Send className="h-4 w-4 mr-2" />
                      Send to Carriers
                    </Button>
                  )}

                  {/* Regenerate Quote Sheet — available from ready_to_quote onward */}
                  {["ready_to_quote", "waiting_on_carriers", "quotes_received", "waiting_on_broker", "quote_sent"].includes(data.state) && (
                    <Button
                      variant="outline"
                      className="w-full"
                      onClick={async () => {
                        try {
                          await fetch(`/api/rfqs/${data.id}/regenerate-quote-sheet`, { method: "POST" })
                          toast.success("Quote sheet regenerated")
                        } catch { toast.error("Failed to regenerate quote sheet") }
                      }}
                    >
                      <RefreshCw className="h-4 w-4 mr-2" />
                      Regenerate Quote Sheet
                    </Button>
                  )}

                  {/* Ask for Clarification — available in any active state */}
                  <Button
                    variant="outline"
                    className="w-full"
                    onClick={async () => {
                      try {
                        await fetch(`/api/rfqs/${data.id}/request-clarification`, { method: "POST" })
                        toast.success("Clarification follow-up enqueued")
                      } catch { toast.error("Failed to request clarification") }
                    }}
                  >
                    <MessageSquare className="h-4 w-4 mr-2" />
                    Ask for Clarification
                  </Button>
                </div>
              </div>
            )}

            {/* Won / Lost / Cancel buttons (#100) — shown for non-terminal RFQs */}
            {!["won", "lost", "cancelled"].includes(data.state) && (
              <div className="mt-6">
                <Separator className="mb-4" />
                <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-3">
                  Close RFQ
                </p>
                <div className="flex gap-2">
                  <OutcomeButton rfqId={data.id} outcome="won" label="Won" className="bg-green-600 hover:bg-green-700 text-white" onSuccess={onClose} />
                  <OutcomeButton rfqId={data.id} outcome="lost" label="Lost" className="bg-gray-500 hover:bg-gray-600 text-white" onSuccess={onClose} />
                  <OutcomeButton rfqId={data.id} outcome="cancelled" label="Cancel" className="text-red-600 border-red-300 hover:bg-red-50" variant="outline" onSuccess={onClose} />
                </div>
              </div>
            )}
            </div>{/* end scrollable body */}
          </>
        )}
      </SheetContent>

      {/* Carrier selection modal (#32) */}
      <CarrierSelectModal
        rfqId={carrierModalRfqId}
        onClose={() => setCarrierModalRfqId(null)}
      />
    </Sheet>
  )
}


// ---------------------------------------------------------------------------
// Section components
// ---------------------------------------------------------------------------


/** Summary tab — original email (#109) + definition list of extracted RFQ fields. */
function SummarySection({ data, messages }: { data: RfqDetail; messages: RfqMessage[] }) {
  const [showOriginal, setShowOriginal] = useState(false)

  /* Find the first inbound message — this is the original email that was extracted from (#109) */
  const originalEmail = messages.find((m) => m.direction === "inbound")

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
    <div className="space-y-4">
      {/* Original email — collapsible section above extracted fields (#109) */}
      {originalEmail && (
        <div className="border rounded-lg overflow-hidden">
          <button
            onClick={() => setShowOriginal(!showOriginal)}
            className="w-full flex items-center gap-2 px-3 py-2 text-left hover:bg-muted/30 transition-colors"
          >
            {showOriginal ? (
              <ChevronDown className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
            ) : (
              <ChevronRight className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
            )}
            <Mail className="h-3.5 w-3.5 text-[#0F9ED5] shrink-0" />
            <span className="text-xs font-medium">Original Email</span>
            <span className="text-xs text-muted-foreground ml-auto">
              from {originalEmail.sender}
            </span>
          </button>
          {showOriginal && (
            <div className="px-3 pb-3 border-t bg-muted/10">
              {originalEmail.subject && (
                <p className="text-xs text-muted-foreground mt-2 mb-1">
                  Subject: {originalEmail.subject}
                </p>
              )}
              <p className="text-sm whitespace-pre-wrap leading-relaxed mt-1">
                {originalEmail.body}
              </p>
            </div>
          )}
        </div>
      )}

      {/* Extracted fields */}
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


/** Ranked carrier bids section (#34, #101) — shows bids with ranking tags and pricing action. */
function RankedBidsSection({ bids, rfqId }: { bids: RankedBid[]; rfqId: number }) {
  const [pricingResult, setPricingResult] = useState<Record<string, unknown> | null>(null)
  const [isPricing, setIsPricing] = useState(false)
  const [isGenerating, setIsGenerating] = useState(false)
  // Editable markup state (#162)
  const [markupPct, setMarkupPct] = useState(12)
  const [markupDollar, setMarkupDollar] = useState(0)
  const [customerRate, setCustomerRate] = useState(0)
  const [carrierRate, setCarrierRate] = useState(0)
  // Counter-offer state
  const [counterBidId, setCounterBidId] = useState<number | null>(null)
  const [counterRate, setCounterRate] = useState("")
  const [counterMessage, setCounterMessage] = useState("")
  const [isSendingCounter, setIsSendingCounter] = useState(false)
  // Re-bid state
  const [showRebid, setShowRebid] = useState(false)
  const [rebidGuidance, setRebidGuidance] = useState("")
  const [isSendingRebid, setIsSendingRebid] = useState(false)

  const queryClient = useQueryClient()

  const handleSelectBid = async (bidId: number) => {
    setIsPricing(true)
    try {
      const res = await fetch(
        `${import.meta.env.DEV ? "http://localhost:8001" : ""}/api/rfqs/${rfqId}/price`,
        { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ carrier_bid_id: bidId }) }
      )
      const data = await res.json()
      setPricingResult(data)
      // Initialize editable markup from the result
      setCarrierRate(Number(data.carrier_rate))
      setMarkupPct(Number(data.markup_percent))
      setMarkupDollar(Number(data.markup_amount))
      setCustomerRate(Number(data.customer_rate))
      queryClient.invalidateQueries({ queryKey: ["rfq", "detail"] })
      toast.success("Pricing applied")
    } catch { toast.error("Pricing failed") }
    finally { setIsPricing(false) }
  }

  // Sync markup slider/input (#162)
  const handleMarkupPctChange = (pct: number) => {
    setMarkupPct(pct)
    const markup = carrierRate * pct / 100
    setMarkupDollar(Math.round(markup))
    setCustomerRate(Math.round(carrierRate + markup))
  }

  const handleMarkupDollarChange = (dollar: number) => {
    setMarkupDollar(dollar)
    setMarkupPct(carrierRate > 0 ? Math.round(dollar / carrierRate * 100) : 0)
    setCustomerRate(Math.round(carrierRate + dollar))
  }

  const handleSaveMarkup = async () => {
    try {
      const res = await fetch(
        `${import.meta.env.DEV ? "http://localhost:8001" : ""}/api/rfqs/${rfqId}/price`,
        { method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ carrier_bid_id: pricingResult?.carrier_bid_id, manual_rate: customerRate }) }
      )
      const data = await res.json()
      setPricingResult(data)
      setCarrierRate(Number(data.carrier_rate))
      setMarkupPct(Number(data.markup_percent))
      setMarkupDollar(Number(data.markup_amount))
      setCustomerRate(Number(data.customer_rate))
      queryClient.invalidateQueries({ queryKey: ["rfq", "detail"] })
      toast.success("Markup updated", { description: `Customer rate: $${Number(data.customer_rate).toLocaleString()}` })
    } catch { toast.error("Failed to update markup") }
  }

  const handleGenerateQuote = async () => {
    setIsGenerating(true)
    try {
      await fetch(
        `${import.meta.env.DEV ? "http://localhost:8001" : ""}/api/rfqs/${rfqId}/generate-quote`,
        { method: "POST", headers: { "Content-Type": "application/json" } }
      )
      queryClient.invalidateQueries()
      toast.success("Customer quote generated", { description: "Review it in Urgent Actions" })
    } catch { toast.error("Quote generation failed") }
    finally { setIsGenerating(false) }
  }

  // Counter-offer (#162)
  const handleSendCounter = async () => {
    if (!counterBidId || !counterRate) return
    setIsSendingCounter(true)
    try {
      await fetch(
        `${import.meta.env.DEV ? "http://localhost:8001" : ""}/api/rfqs/${rfqId}/counter-offer`,
        { method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ carrier_bid_id: counterBidId, proposed_rate: parseFloat(counterRate), message: counterMessage || undefined }) }
      )
      toast.success("Counter-offer sent")
      setCounterBidId(null)
      setCounterRate("")
      setCounterMessage("")
      queryClient.invalidateQueries()
    } catch { toast.error("Counter-offer failed") }
    finally { setIsSendingCounter(false) }
  }

  // Re-bid request (#162)
  const handleSendRebid = async () => {
    if (!rebidGuidance.trim()) return
    setIsSendingRebid(true)
    try {
      const carrierIds = bids.map((b) => b.id) // Use bid IDs — backend needs carrier IDs
      // Get unique carrier emails from bids to find carrier IDs
      await fetch(
        `${import.meta.env.DEV ? "http://localhost:8001" : ""}/api/rfqs/${rfqId}/rebid-request`,
        { method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ carrier_ids: carrierIds, guidance: rebidGuidance }) }
      )
      toast.success("Re-bid request sent")
      setShowRebid(false)
      setRebidGuidance("")
      queryClient.invalidateQueries()
    } catch { toast.error("Re-bid request failed") }
    finally { setIsSendingRebid(false) }
  }

  const tagStyles: Record<string, string> = {
    best_value: "bg-green-100 text-green-800",
    runner_up: "bg-blue-100 text-blue-800",
    outlier_high: "bg-red-100 text-red-800",
    outlier_low: "bg-amber-100 text-amber-800",
  }
  const tagLabels: Record<string, string> = {
    best_value: "Best Value",
    runner_up: "Runner Up",
    outlier_high: "Outlier (High)",
    outlier_low: "Outlier (Low)",
  }

  return (
    <div>
      <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-3">
        Carrier Bids — Ranked ({bids.length})
      </p>
      <div className="space-y-2">
        {bids.map((bid) => (
          <div key={bid.id}>
            <div
              className={`flex items-center justify-between border rounded-lg p-3 ${
                bid.tag === "best_value" ? "border-green-300 bg-green-50/50" : ""
              }`}
            >
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <span className="text-xs font-mono text-muted-foreground">#{bid.rank}</span>
                  <p className="text-sm font-medium">{bid.carrier_name}</p>
                  {bid.tag && (
                    <Badge variant="secondary" className={`text-[10px] ${tagStyles[bid.tag] ?? ""}`}>
                      {tagLabels[bid.tag] ?? bid.tag}
                    </Badge>
                  )}
                </div>
                {bid.reason && <p className="text-xs text-muted-foreground mt-0.5">{bid.reason}</p>}
                {bid.availability && <p className="text-xs text-muted-foreground">{bid.availability}</p>}
              </div>
              <div className="text-right shrink-0 ml-4 space-y-1">
                {bid.rate != null && (
                  <p className="text-sm font-bold text-[#0E2841]">${bid.rate.toLocaleString()}</p>
                )}
                <div className="flex gap-1">
                  <Button size="sm" variant="outline" onClick={() => handleSelectBid(bid.id)} disabled={isPricing} className="text-xs">
                    {isPricing ? "..." : "Select & Price"}
                  </Button>
                  <Button size="sm" variant="outline" onClick={() => setCounterBidId(counterBidId === bid.id ? null : bid.id)} className="text-xs">
                    Counter
                  </Button>
                </div>
              </div>
            </div>

            {/* Inline counter-offer form (#162) */}
            {counterBidId === bid.id && (
              <div className="border border-t-0 rounded-b-lg p-3 bg-muted/20 space-y-2">
                <p className="text-xs font-semibold text-muted-foreground uppercase">Counter-offer to {bid.carrier_name}</p>
                <div className="flex gap-2">
                  <div className="flex-1">
                    <label className="text-[10px] text-muted-foreground">Proposed Rate ($)</label>
                    <input type="number" value={counterRate} onChange={(e) => setCounterRate(e.target.value)}
                      placeholder={bid.rate ? String(Math.round(bid.rate * 0.9)) : ""}
                      className="w-full text-sm border rounded px-2.5 py-1.5 focus:outline-none focus:ring-1 focus:ring-[#0F9ED5]" />
                  </div>
                </div>
                <textarea value={counterMessage} onChange={(e) => setCounterMessage(e.target.value)}
                  placeholder="Optional message to the carrier..."
                  className="w-full text-sm border rounded px-2.5 py-1.5 resize-none focus:outline-none focus:ring-1 focus:ring-[#0F9ED5]" rows={2} />
                <div className="flex gap-2">
                  <Button size="sm" onClick={handleSendCounter} disabled={!counterRate || isSendingCounter} className="bg-[#0F9ED5] hover:bg-[#0B7FAD] text-white">
                    {isSendingCounter ? "Sending..." : "Send Counter"}
                  </Button>
                  <Button size="sm" variant="ghost" onClick={() => setCounterBidId(null)}>Cancel</Button>
                </div>
              </div>
            )}
          </div>
        ))}
      </div>

      {/* Re-bid request (#162) */}
      <div className="mt-3">
        {showRebid ? (
          <div className="border rounded-lg p-3 bg-muted/20 space-y-2">
            <p className="text-xs font-semibold text-muted-foreground uppercase">Request Re-bid from All Carriers</p>
            <textarea value={rebidGuidance} onChange={(e) => setRebidGuidance(e.target.value)}
              placeholder="e.g., We need this under $4,500. Can you sharpen your rate?"
              className="w-full text-sm border rounded px-2.5 py-1.5 resize-none focus:outline-none focus:ring-1 focus:ring-[#0F9ED5]" rows={2} />
            <div className="flex gap-2">
              <Button size="sm" onClick={handleSendRebid} disabled={!rebidGuidance.trim() || isSendingRebid} className="bg-[#0F9ED5] hover:bg-[#0B7FAD] text-white">
                {isSendingRebid ? "Sending..." : `Request Re-bid (${bids.length} carriers)`}
              </Button>
              <Button size="sm" variant="ghost" onClick={() => setShowRebid(false)}>Cancel</Button>
            </div>
          </div>
        ) : (
          <Button size="sm" variant="outline" onClick={() => setShowRebid(true)} className="w-full text-xs">
            Request Re-bid
          </Button>
        )}
      </div>

      {/* Pricing section with editable markup (#162) */}
      {pricingResult && (
        <div className="mt-4 bg-blue-50 border border-blue-200 rounded-lg p-4 space-y-3">
          <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Pricing</p>
          <div className="grid grid-cols-3 gap-3 text-sm">
            <div>
              <p className="text-xs text-muted-foreground">Carrier Rate</p>
              <p className="font-medium">${carrierRate.toLocaleString()}</p>
            </div>
            <div>
              <p className="text-xs text-muted-foreground">Markup</p>
              <p className="font-medium">${markupDollar.toLocaleString()}</p>
            </div>
            <div>
              <p className="text-xs text-muted-foreground">Customer Rate</p>
              <p className="font-bold text-[#0E2841]">${customerRate.toLocaleString()}</p>
            </div>
          </div>

          {/* Markup slider + input (#162) */}
          <div className="space-y-2">
            <div className="flex items-center gap-3">
              <label className="text-xs text-muted-foreground w-16">Markup %</label>
              <input type="range" min={0} max={50} step={1} value={markupPct}
                onChange={(e) => handleMarkupPctChange(Number(e.target.value))}
                className="flex-1 h-2 accent-[#0F9ED5]" />
              <span className="text-xs font-mono w-10 text-right">{markupPct}%</span>
            </div>
            <div className="flex items-center gap-3">
              <label className="text-xs text-muted-foreground w-16">Markup $</label>
              <input type="number" value={markupDollar}
                onChange={(e) => handleMarkupDollarChange(Number(e.target.value))}
                className="flex-1 text-sm border rounded px-2 py-1 focus:outline-none focus:ring-1 focus:ring-[#0F9ED5]" />
            </div>
          </div>

          <div className="flex gap-2">
            <Button size="sm" variant="outline" onClick={handleSaveMarkup} className="text-xs">
              Save Pricing
            </Button>
            <Button
              onClick={handleGenerateQuote}
              disabled={isGenerating}
              className="flex-1 bg-[#0F9ED5] hover:bg-[#0B7FAD] text-white"
            >
              {isGenerating ? "Generating..." : "Generate Customer Quote"}
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}


/** Won/Lost/Cancel button (#100) — marks RFQ as terminal. */
function OutcomeButton({
  rfqId,
  outcome,
  label,
  className,
  variant = "default",
  onSuccess,
}: {
  rfqId: number
  outcome: string
  label: string
  className?: string
  variant?: "default" | "outline"
  onSuccess: () => void
}) {
  const [isPending, setIsPending] = useState(false)
  const queryClient = useQueryClient()

  const handleClick = async () => {
    setIsPending(true)
    try {
      await fetch(
        `${import.meta.env.DEV ? "http://localhost:8001" : ""}/api/rfqs/${rfqId}/outcome`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ outcome }),
        }
      )
      queryClient.invalidateQueries()
      toast.success(`RFQ marked as ${label}`)
      onSuccess()
    } catch {
      toast.error("Failed to update outcome")
    } finally {
      setIsPending(false)
    }
  }

  return (
    <Button
      variant={variant}
      size="sm"
      onClick={handleClick}
      disabled={isPending}
      className={className}
    >
      {isPending ? "..." : label}
    </Button>
  )
}


/** Pending actions section — shows approvals waiting for this RFQ with full action controls. */
function RfqPendingActions({ rfqId }: { rfqId: number }) {
  const queryClient = useQueryClient()
  const [actioning, setActioning] = useState<number | null>(null)
  const [editingId, setEditingId] = useState<number | null>(null)
  const [editBody, setEditBody] = useState("")

  const approvals = useQuery({
    queryKey: ["approvals", "rfq", rfqId],
    queryFn: () => api.get<{ approvals: Array<{
      id: number; approval_type: string; status: string; reason: string | null;
      draft_subject: string | null; draft_body: string | null; draft_recipient: string | null;
      rfq_id: number; created_at: string;
    }>; total: number }>("/api/approvals?status=pending_approval"),
  })

  const typeLabels: Record<string, string> = {
    customer_reply: "Customer Reply",
    carrier_rfq: "Carrier RFQ",
    customer_quote: "Customer Quote",
  }

  const rfqApprovals = (approvals.data?.approvals ?? []).filter((a) => a.rfq_id === rfqId)

  if (rfqApprovals.length === 0) return null

  const handleAction = async (id: number, action: "approve" | "reject" | "skip", body?: string) => {
    setActioning(id)
    try {
      const endpoint = action === "approve" ? "approve" : action === "reject" ? "reject" : "skip"
      await api.post(`/api/approvals/${id}/${endpoint}`, {
        approved_by: "operator",
        edited_body: body || undefined,
        reason: action === "reject" ? "Rejected from RFQ detail" : action === "skip" ? "Skipped" : undefined,
      })
      queryClient.invalidateQueries()
      setEditingId(null)
      const msgs: Record<string, string> = {
        approve: "Approved and queued for sending",
        reject: "Rejected — will not be sent",
        skip: "Skipped — you can review later",
      }
      toast.success(msgs[action])
    } catch {
      toast.error(`Failed to ${action}`)
    } finally {
      setActioning(null)
    }
  }

  return (
    <div className="my-3 space-y-2">
      {rfqApprovals.map((a) => {
        const isEditing = editingId === a.id

        return (
          <div key={a.id} className="rounded-lg border border-amber-200 bg-amber-50/50 p-3">
            <div className="flex items-center gap-2 mb-2">
              <AlertCircle className="h-4 w-4 text-amber-600 shrink-0" />
              <span className="text-xs font-semibold text-amber-800">
                {typeLabels[a.approval_type] ?? a.approval_type} — Needs your approval
              </span>
            </div>

            {a.draft_subject && (
              <p className="text-xs text-muted-foreground mb-1">
                To: {a.draft_recipient} · {a.draft_subject}
              </p>
            )}

            {/* Draft body — editable when in edit mode */}
            {a.draft_body && (
              isEditing ? (
                <textarea
                  value={editBody}
                  onChange={(e) => setEditBody(e.target.value)}
                  className="w-full text-sm border rounded p-2 mt-1 min-h-[120px] resize-y focus:outline-none focus:ring-2 focus:ring-[#0F9ED5]/30"
                />
              ) : (
                <p className="text-sm whitespace-pre-wrap bg-white border rounded p-2 mt-1 max-h-40 overflow-y-auto">
                  {a.draft_body}
                </p>
              )
            )}

            {a.reason && (
              <p className="text-xs text-muted-foreground mt-1">{a.reason}</p>
            )}

            {/* Action buttons — Send As-Is, Edit, Reject, Skip */}
            <div className="flex items-center gap-1.5 mt-3">
              {isEditing ? (
                <>
                  <Button
                    size="sm"
                    onClick={() => handleAction(a.id, "approve", editBody)}
                    disabled={actioning !== null}
                    className="bg-green-600 hover:bg-green-700 text-white h-8 px-3"
                  >
                    {actioning === a.id ? "..." : <><Check className="h-3.5 w-3.5 mr-1" /> Send Edited</>}
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => setEditingId(null)}
                    className="h-8 px-2"
                  >
                    Cancel
                  </Button>
                </>
              ) : (
                <>
                  <Button
                    size="sm"
                    onClick={() => handleAction(a.id, "approve")}
                    disabled={actioning !== null}
                    className="bg-green-600 hover:bg-green-700 text-white h-8 px-3"
                  >
                    {actioning === a.id ? "..." : <><Check className="h-3.5 w-3.5 mr-1" /> Send</>}
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => { setEditingId(a.id); setEditBody(a.draft_body ?? "") }}
                    disabled={actioning !== null}
                    className="h-8 px-3"
                  >
                    Edit
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => handleAction(a.id, "reject")}
                    disabled={actioning !== null}
                    className="text-red-600 border-red-300 hover:bg-red-50 h-8 px-2"
                  >
                    Reject
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => handleAction(a.id, "skip")}
                    disabled={actioning !== null}
                    className="text-muted-foreground h-8 px-2"
                  >
                    Skip
                  </Button>
                </>
              )}
            </div>
          </div>
        )
      })}
    </div>
  )
}


/** Reply actions — redraft or manual reply when no pending approval exists. */
function RfqReplyActions({ rfqId, customerEmail, customerName }: { rfqId: number; customerEmail: string | null; customerName: string | null }) {
  const queryClient = useQueryClient()
  const [showManual, setShowManual] = useState(false)
  const [manualTo, setManualTo] = useState(customerEmail ?? "")
  const [manualSubject, setManualSubject] = useState(`Re: Quote Request — ${customerName ?? ""}`)
  const [manualBody, setManualBody] = useState("")
  const [isRedrafting, setIsRedrafting] = useState(false)
  const [isSending, setIsSending] = useState(false)

  /* Check if there are already pending approvals — if so, don't show these buttons */
  const approvals = useQuery({
    queryKey: ["approvals", "rfq-reply-check", rfqId],
    queryFn: () => api.get<{ approvals: Array<{ rfq_id: number; status: string }>; total: number }>("/api/approvals?status=pending_approval"),
  })
  const hasPending = (approvals.data?.approvals ?? []).some((a) => a.rfq_id === rfqId)
  if (hasPending) return null

  const handleRedraft = async () => {
    setIsRedrafting(true)
    try {
      await api.post(`/api/rfqs/${rfqId}/redraft`)
      queryClient.invalidateQueries()
      toast.success("New draft generated — check above")
    } catch {
      toast.error("Failed to redraft")
    } finally {
      setIsRedrafting(false)
    }
  }

  const handleManualSend = async () => {
    if (!manualTo || !manualBody) return
    setIsSending(true)
    try {
      await api.post(`/api/rfqs/${rfqId}/manual-reply`, {
        to: manualTo,
        subject: manualSubject,
        body: manualBody,
      })
      queryClient.invalidateQueries()
      toast.success("Reply queued for sending")
      setShowManual(false)
      setManualBody("")
    } catch {
      toast.error("Failed to send")
    } finally {
      setIsSending(false)
    }
  }

  return (
    <div className="my-3">
      {showManual ? (
        <div className="rounded-lg border p-3 space-y-2">
          <p className="text-xs font-semibold text-muted-foreground uppercase">Manual Reply</p>
          <input
            value={manualTo}
            onChange={(e) => setManualTo(e.target.value)}
            placeholder="To"
            className="w-full px-2 py-1.5 text-sm border rounded-md"
          />
          <input
            value={manualSubject}
            onChange={(e) => setManualSubject(e.target.value)}
            placeholder="Subject"
            className="w-full px-2 py-1.5 text-sm border rounded-md"
          />
          <textarea
            value={manualBody}
            onChange={(e) => setManualBody(e.target.value)}
            placeholder="Write your reply..."
            className="w-full px-2 py-1.5 text-sm border rounded-md min-h-[100px] resize-y"
          />
          <div className="flex gap-1.5">
            <Button
              size="sm"
              onClick={handleManualSend}
              disabled={!manualBody || isSending}
              className="bg-[#0F9ED5] hover:bg-[#0B7FAD] text-white h-8 px-3"
            >
              {isSending ? "Sending..." : <><Send className="h-3.5 w-3.5 mr-1" /> Send Reply</>}
            </Button>
            <Button size="sm" variant="outline" onClick={() => setShowManual(false)} className="h-8 px-2">
              Cancel
            </Button>
          </div>
        </div>
      ) : (
        <div className="flex gap-2">
          <Button
            size="sm"
            variant="outline"
            onClick={handleRedraft}
            disabled={isRedrafting}
            className="h-8 px-3"
          >
            {isRedrafting ? "Drafting..." : "Redraft with AI"}
          </Button>
          <Button
            size="sm"
            variant="outline"
            onClick={() => setShowManual(true)}
            className="h-8 px-3"
          >
            Write Reply
          </Button>
        </div>
      )}
    </div>
  )
}
