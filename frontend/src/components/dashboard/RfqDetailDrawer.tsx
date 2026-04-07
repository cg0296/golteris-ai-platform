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
import { useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { Send, FileText, Mail, ChevronDown, ChevronRight } from "lucide-react"
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
import { useRfqDetail } from "@/hooks/use-rfq-detail"
import { useRankedBids, type RankedBid } from "@/hooks/use-ranked-bids"
import { useQuoteSheet } from "@/hooks/use-quote-sheet"
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
  const [showQuoteSheet, setShowQuoteSheet] = useState(false)

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
      <SheetContent side="center" className="overflow-y-auto p-6">
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
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => setShowQuoteSheet(!showQuoteSheet)}
                    >
                      <FileText className="h-3.5 w-3.5 mr-1.5" />
                      {showQuoteSheet ? "Hide" : "View Quote Sheet"}
                    </Button>
                  </div>
                  {showQuoteSheet && (
                    <div className="bg-muted/30 border rounded-lg p-4 text-sm space-y-2">
                      {(() => {
                        const qs = quoteSheet.data.quote_sheet as Record<string, unknown>
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
                          </>
                        )
                      })()}
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* Send to Carriers action (#32) — shown for RFQs ready to distribute */}
            {data.state === "ready_to_quote" && (
              <div className="mt-6">
                <Separator className="mb-4" />
                <Button
                  onClick={() => setCarrierModalRfqId(data.id)}
                  className="w-full bg-[#0F9ED5] hover:bg-[#0B7FAD] text-white"
                >
                  <Send className="h-4 w-4 mr-2" />
                  Send to Carriers
                </Button>
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
      queryClient.invalidateQueries({ queryKey: ["rfq", "detail"] })
      toast.success("Pricing applied", { description: `Customer rate: $${data.customer_rate?.toLocaleString()}` })
    } catch { toast.error("Pricing failed") }
    finally { setIsPricing(false) }
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
          <div
            key={bid.id}
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
              {bid.reason && (
                <p className="text-xs text-muted-foreground mt-0.5">{bid.reason}</p>
              )}
              {bid.availability && (
                <p className="text-xs text-muted-foreground">{bid.availability}</p>
              )}
            </div>
            <div className="text-right shrink-0 ml-4 space-y-1">
              {bid.rate != null && (
                <p className="text-sm font-bold text-[#0E2841]">
                  ${bid.rate.toLocaleString()}
                </p>
              )}
              <Button
                size="sm"
                variant="outline"
                onClick={() => handleSelectBid(bid.id)}
                disabled={isPricing}
                className="text-xs"
              >
                {isPricing ? "..." : "Select & Price"}
              </Button>
            </div>
          </div>
        ))}
      </div>

      {/* Pricing result (#101) */}
      {pricingResult && (
        <div className="mt-4 bg-blue-50 border border-blue-200 rounded-lg p-3 space-y-2">
          <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Pricing Applied</p>
          <div className="grid grid-cols-3 gap-2 text-sm">
            <div>
              <p className="text-xs text-muted-foreground">Carrier Rate</p>
              <p className="font-medium">${Number(pricingResult.carrier_rate).toLocaleString()}</p>
            </div>
            <div>
              <p className="text-xs text-muted-foreground">Markup</p>
              <p className="font-medium">${Number(pricingResult.markup_amount).toLocaleString()}</p>
            </div>
            <div>
              <p className="text-xs text-muted-foreground">Customer Rate</p>
              <p className="font-bold text-[#0E2841]">${Number(pricingResult.customer_rate).toLocaleString()}</p>
            </div>
          </div>
          <Button
            onClick={handleGenerateQuote}
            disabled={isGenerating}
            className="w-full mt-2 bg-[#0F9ED5] hover:bg-[#0B7FAD] text-white"
          >
            {isGenerating ? "Generating..." : "Generate Customer Quote"}
          </Button>
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
