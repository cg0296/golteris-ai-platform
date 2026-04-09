/**
 * pages/RfqsPage.tsx — Consolidated RFQs view (#164).
 *
 * Merges the old Inbox, RFQs, and History pages into a single page with
 * tab filters: All, Active, Needs Attention, Closed, Messages.
 *
 * - All: every RFQ regardless of state
 * - Active: non-terminal RFQs
 * - Needs Attention: needs_clarification + waiting_on_broker
 * - Closed: won/lost/cancelled with stats strip
 * - Messages: all inbound/outbound messages with routing badges
 */

import { useState, useMemo } from "react"
import { Search, Download, FileText, Clock, CheckCircle, ThumbsUp, TrendingUp } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table"
import { KpiCard } from "@/components/dashboard/KpiCard"
import { RfqDetailDrawer } from "@/components/dashboard/RfqDetailDrawer"
import { MessageThreadModal } from "@/components/dashboard/MessageThreadModal"
import { useRfqList, useRfqCounts } from "@/hooks/use-rfq-list"
import { useHistory } from "@/hooks/use-history"
import { useMessageList, useMessageCounts } from "@/hooks/use-messages"
import { formatRelativeTime, cn } from "@/lib/utils"
import { exportToCsv } from "@/lib/export"

/** Top-level view tabs */
const VIEW_TABS = [
  { value: "active", label: "Active" },
  { value: "attention", label: "Needs Attention" },
  { value: "all", label: "All" },
  { value: "closed", label: "Closed" },
  { value: "messages", label: "Messages" },
] as const

type ViewTab = typeof VIEW_TABS[number]["value"]

/** RFQ state badge colors */
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

/** Message routing badge colors */
const routingColors: Record<string, string> = {
  attached: "bg-blue-100 text-blue-800",
  new_rfq: "bg-green-100 text-green-800",
  needs_review: "bg-amber-100 text-amber-800",
  ignored: "bg-gray-100 text-gray-600",
}

const PAGE_SIZE = 50

export function RfqsPage() {
  const [viewTab, setViewTab] = useState<ViewTab>("active")
  const [search, setSearch] = useState("")
  const [page, setPage] = useState(0)
  const [selectedRfqId, setSelectedRfqId] = useState<number | null>(null)
  const [selectedMessageId, setSelectedMessageId] = useState<number | null>(null)

  // Debounced search
  const [debouncedSearch, setDebouncedSearch] = useState("")
  useMemo(() => {
    const timer = setTimeout(() => setDebouncedSearch(search), 300)
    return () => clearTimeout(timer)
  }, [search])

  const handleTabChange = (tab: ViewTab) => {
    setViewTab(tab)
    setPage(0)
  }

  // Determine which state filter to pass based on tab
  const stateFilter = viewTab === "active"
    ? "active"
    : viewTab === "attention"
    ? "attention"
    : viewTab === "closed"
    ? "closed"
    : null // "all" and "messages"

  // RFQ data (used by All, Active, Attention, Closed tabs)
  const rfqs = useRfqList({
    limit: PAGE_SIZE,
    offset: page * PAGE_SIZE,
    state: stateFilter,
    search: debouncedSearch,
    includeTerminal: viewTab !== "active" && viewTab !== "attention",
  })
  const counts = useRfqCounts()

  // History stats (Closed tab only)
  const history = useHistory({ limit: PAGE_SIZE, offset: page * PAGE_SIZE })

  // Messages data (Messages tab only)
  const messages = useMessageList({
    limit: PAGE_SIZE,
    offset: page * PAGE_SIZE,
    search: debouncedSearch,
  })
  const messageCounts = useMessageCounts()

  const isMessagesTab = viewTab === "messages"
  const totalItems = isMessagesTab ? (messages.data?.total ?? 0) : (rfqs.data?.total ?? 0)
  const totalPages = Math.ceil(totalItems / PAGE_SIZE)

  // Count for attention tab badge
  const attentionCount = (counts.data?.counts["needs_clarification"] ?? 0) + (counts.data?.counts["waiting_on_broker"] ?? 0)

  return (
    <div className="p-4 lg:p-6 max-w-7xl space-y-4">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
        <h2 className="text-xl font-semibold text-[#0E2841] flex items-center gap-2">
          <FileText className="h-5 w-5" />
          RFQs
        </h2>

        {/* Search + Export */}
        <div className="flex items-center gap-2">
          <div className="relative w-full sm:w-72">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
            <input
              type="text"
              placeholder={isMessagesTab ? "Search sender, subject..." : "Search shipper, route..."}
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="w-full pl-9 pr-3 py-2 text-sm border rounded-md bg-white focus:outline-none focus:ring-2 focus:ring-[#0F9ED5]/30 focus:border-[#0F9ED5]"
            />
          </div>
          {!isMessagesTab && (
            <button
              onClick={() => {
                const data = rfqs.data?.rfqs ?? []
                exportToCsv(
                  data,
                  [
                    { key: "id", label: "RFQ #" },
                    { key: "customer_name", label: "Customer" },
                    { key: "origin", label: "Origin" },
                    { key: "destination", label: "Destination" },
                    { key: "equipment_type", label: "Equipment" },
                    { key: "state_label", label: "Status" },
                    { key: "updated_at", label: "Updated" },
                  ],
                  `golteris-rfqs-${new Date().toISOString().slice(0, 10)}`
                )
              }}
              disabled={!rfqs.data?.rfqs.length}
              className="shrink-0 flex items-center gap-1.5 px-3 py-2 text-xs border rounded-md bg-white hover:bg-muted/50 disabled:opacity-40"
              title="Download as CSV"
            >
              <Download className="h-3.5 w-3.5" />
              Export
            </button>
          )}
        </div>
      </div>

      {/* View tabs */}
      <div className="flex flex-wrap gap-2 border-b pb-3">
        {VIEW_TABS.map((tab) => {
          const isActive = viewTab === tab.value
          let badge = ""
          if (tab.value === "attention" && attentionCount > 0) badge = String(attentionCount)
          if (tab.value === "messages") badge = String(Object.values(messageCounts.data?.counts ?? {}).reduce((a, b) => a + b, 0))

          return (
            <button
              key={tab.value}
              onClick={() => handleTabChange(tab.value)}
              className={cn(
                "inline-flex items-center gap-1.5 px-4 py-1.5 rounded-full text-xs font-medium transition-colors border",
                isActive
                  ? "bg-[#0E2841] text-white border-[#0E2841]"
                  : "bg-white text-muted-foreground border-border hover:bg-muted/50"
              )}
            >
              {tab.label}
              {badge && (
                <span className={cn("text-[10px] font-mono", isActive ? "text-white/70" : "text-muted-foreground/60")}>
                  {badge}
                </span>
              )}
            </button>
          )
        })}
      </div>

      {/* Closed tab: stats strip */}
      {viewTab === "closed" && history.data?.stats && (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          <KpiCard icon={CheckCircle} value={history.data.stats.completed_today} label="Completed Today" iconBg="bg-green-50" iconColor="text-green-600" />
          <KpiCard icon={Clock} value={history.data.stats.avg_time_to_quote_hours > 0 ? `${history.data.stats.avg_time_to_quote_hours}h` : "—"} label="Avg Time to Quote" iconBg="bg-[#E8F4FC]" iconColor="text-[#0F9ED5]" />
          <KpiCard icon={ThumbsUp} value={history.data.stats.approvals_this_week} label="Approvals This Week" iconBg="bg-purple-50" iconColor="text-purple-600" />
          <KpiCard icon={TrendingUp} value={history.data.stats.time_saved_hours > 0 ? `${history.data.stats.time_saved_hours}h` : "0h"} label="Time Saved This Week" iconBg="bg-amber-50" iconColor="text-amber-600" />
        </div>
      )}

      {/* Messages tab content */}
      {isMessagesTab ? (
        <>
          {messages.isLoading ? (
            <LoadingSkeleton />
          ) : (messages.data?.messages.length ?? 0) === 0 ? (
            <EmptyState text={search ? `No messages matching "${search}"` : "No messages yet"} />
          ) : (
            <div className="bg-white rounded-lg shadow-sm overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="text-xs">Sender</TableHead>
                    <TableHead className="text-xs hidden md:table-cell">Subject</TableHead>
                    <TableHead className="text-xs">Routing</TableHead>
                    <TableHead className="text-xs hidden lg:table-cell">RFQ</TableHead>
                    <TableHead className="text-xs text-right">Received</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {messages.data?.messages.map((msg) => (
                    <TableRow key={msg.id} className="hover:bg-muted/50 cursor-pointer" onClick={() => setSelectedMessageId(msg.id)}>
                      <TableCell className="py-3"><p className="text-sm font-medium truncate max-w-[200px]">{msg.sender}</p></TableCell>
                      <TableCell className="py-3 hidden md:table-cell"><p className="text-sm truncate max-w-[300px]">{msg.subject ?? "—"}</p></TableCell>
                      <TableCell className="py-3">
                        {msg.routing_status ? (
                          <Badge variant="secondary" className={`text-xs ${routingColors[msg.routing_status] ?? ""}`}>{msg.routing_label}</Badge>
                        ) : <span className="text-xs text-muted-foreground">—</span>}
                      </TableCell>
                      <TableCell className="py-3 hidden lg:table-cell">
                        {msg.rfq ? <span className="text-xs text-[#0F9ED5]">#{msg.rfq.id} {msg.rfq.customer_name}</span> : <span className="text-xs text-muted-foreground">—</span>}
                      </TableCell>
                      <TableCell className="text-xs text-muted-foreground text-right py-3">{msg.received_at ? formatRelativeTime(msg.received_at) : "—"}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </>
      ) : (
        /* RFQ tabs content (All, Active, Attention, Closed) */
        <>
          {rfqs.isLoading ? (
            <LoadingSkeleton />
          ) : (rfqs.data?.rfqs.length ?? 0) === 0 ? (
            <EmptyState text={search ? `No RFQs matching "${search}"` : "No RFQs found"} />
          ) : (
            <div className="bg-white rounded-lg shadow-sm overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="text-xs w-16">#</TableHead>
                    <TableHead className="text-xs">Shipper</TableHead>
                    <TableHead className="text-xs hidden md:table-cell">Route</TableHead>
                    <TableHead className="text-xs hidden lg:table-cell">Equipment</TableHead>
                    <TableHead className="text-xs">Status</TableHead>
                    {viewTab === "closed" && <TableHead className="text-xs hidden lg:table-cell text-right">Quoted</TableHead>}
                    <TableHead className="text-xs text-right">{viewTab === "closed" ? "Closed" : "Updated"}</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {rfqs.data?.rfqs.map((rfq) => (
                    <TableRow key={rfq.id} className="cursor-pointer hover:bg-muted/50" onClick={() => setSelectedRfqId(rfq.id)}>
                      <TableCell className="text-xs font-mono text-muted-foreground py-3">{rfq.ref_number ?? rfq.id}</TableCell>
                      <TableCell className="py-3">
                        <p className="text-sm font-medium">{rfq.customer_name ?? "Unknown"}</p>
                        {rfq.customer_company && <p className="text-xs text-muted-foreground">{rfq.customer_company}</p>}
                      </TableCell>
                      <TableCell className="text-sm py-3 hidden md:table-cell">
                        {rfq.origin && rfq.destination ? `${rfq.origin} → ${rfq.destination}` : "—"}
                      </TableCell>
                      <TableCell className="text-sm py-3 hidden lg:table-cell">
                        {rfq.equipment_type ?? "—"}
                        {rfq.truck_count && rfq.truck_count > 1 && <span className="text-xs text-muted-foreground ml-1">×{rfq.truck_count}</span>}
                      </TableCell>
                      <TableCell className="py-3">
                        <Badge variant="secondary" className={`text-xs ${stateColors[rfq.state] ?? ""}`}>{rfq.state_label}</Badge>
                      </TableCell>
                      {viewTab === "closed" && (
                        <TableCell className="text-sm text-right py-3 hidden lg:table-cell">
                          {rfq.quoted_amount ? `$${Number(rfq.quoted_amount).toLocaleString()}` : "—"}
                        </TableCell>
                      )}
                      <TableCell className="text-xs text-muted-foreground text-right py-3">
                        {viewTab === "closed"
                          ? (rfq.closed_at ? formatRelativeTime(rfq.closed_at) : "—")
                          : formatRelativeTime(rfq.updated_at)}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </>
      )}

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-between">
          <p className="text-xs text-muted-foreground">
            Showing {page * PAGE_SIZE + 1}–{Math.min((page + 1) * PAGE_SIZE, totalItems)} of {totalItems}
          </p>
          <div className="flex gap-2">
            <button onClick={() => setPage((p) => Math.max(0, p - 1))} disabled={page === 0} className="px-3 py-1 text-xs border rounded-md disabled:opacity-40 hover:bg-muted/50">Previous</button>
            <button onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))} disabled={page >= totalPages - 1} className="px-3 py-1 text-xs border rounded-md disabled:opacity-40 hover:bg-muted/50">Next</button>
          </div>
        </div>
      )}

      {/* Message thread modal */}
      <MessageThreadModal
        messageId={selectedMessageId}
        onClose={() => setSelectedMessageId(null)}
        onOpenRfq={(rfqId) => { setSelectedMessageId(null); setSelectedRfqId(rfqId) }}
      />

      {/* RFQ detail drawer */}
      <RfqDetailDrawer
        rfqId={selectedRfqId}
        onClose={() => setSelectedRfqId(null)}
        rfqIds={rfqs.data?.rfqs?.map((r: { id: number }) => r.id)}
        onSelectRfq={setSelectedRfqId}
      />
    </div>
  )
}

function LoadingSkeleton() {
  return (
    <div className="space-y-2">
      {[...Array(6)].map((_, i) => (
        <div key={i} className="h-12 bg-white rounded animate-pulse shadow-sm" />
      ))}
    </div>
  )
}

function EmptyState({ text }: { text: string }) {
  return (
    <div className="bg-white rounded-lg shadow-sm py-12 text-center">
      <p className="text-muted-foreground">{text}</p>
    </div>
  )
}
