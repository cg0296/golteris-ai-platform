/**
 * pages/InboxPage.tsx — Inbox view showing all messages with routing badges (#28, #111).
 *
 * Shows every inbound message and how Golteris routed it:
 * - Attached to an existing RFQ
 * - Created a new RFQ
 * - Sent to the review queue (ambiguous match)
 * - Ignored (filtered out)
 *
 * Clicking a message row opens the full email thread in a modal (#111).
 * From the thread modal, the broker can jump to the attached RFQ detail.
 *
 * Cross-cutting constraints:
 *   C3 — Routing labels use plain English ("Attached to RFQ" not "attached")
 */

import { useState, useMemo } from "react"
import { Search, Inbox } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { RfqDetailDrawer } from "@/components/dashboard/RfqDetailDrawer"
import { MessageThreadModal } from "@/components/dashboard/MessageThreadModal"
import { useMessageList, useMessageCounts } from "@/hooks/use-messages"
import { formatRelativeTime, cn } from "@/lib/utils"

/** Routing filter options with labels and badge colors. */
const ROUTING_FILTERS = [
  { value: null, label: "All" },
  { value: "attached", label: "Attached", color: "bg-blue-100 text-blue-800" },
  { value: "new_rfq", label: "New RFQ", color: "bg-green-100 text-green-800" },
  { value: "needs_review", label: "Needs Review", color: "bg-amber-100 text-amber-800" },
  { value: "ignored", label: "Ignored", color: "bg-gray-100 text-gray-600" },
] as const

/** Badge colors per routing status. */
const routingColors: Record<string, string> = {
  attached: "bg-blue-100 text-blue-800",
  new_rfq: "bg-green-100 text-green-800",
  needs_review: "bg-amber-100 text-amber-800",
  ignored: "bg-gray-100 text-gray-600",
}

const PAGE_SIZE = 50

export function InboxPage() {
  const [routingFilter, setRoutingFilter] = useState<string | null>(null)
  const [search, setSearch] = useState("")
  const [page, setPage] = useState(0)
  const [selectedRfqId, setSelectedRfqId] = useState<number | null>(null)
  /* Message thread modal state (#111) — which message's thread is open */
  const [selectedMessageId, setSelectedMessageId] = useState<number | null>(null)

  const [debouncedSearch, setDebouncedSearch] = useState("")
  useMemo(() => {
    const timer = setTimeout(() => setDebouncedSearch(search), 300)
    return () => clearTimeout(timer)
  }, [search])

  const handleRoutingFilter = (status: string | null) => {
    setRoutingFilter(status)
    setPage(0)
  }

  const messages = useMessageList({
    limit: PAGE_SIZE,
    offset: page * PAGE_SIZE,
    routingStatus: routingFilter,
    search: debouncedSearch,
  })
  const counts = useMessageCounts()

  const totalPages = Math.ceil((messages.data?.total ?? 0) / PAGE_SIZE)

  return (
    <div className="p-4 lg:p-6 max-w-7xl space-y-4">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
        <h2 className="text-xl font-semibold text-[#0E2841] flex items-center gap-2">
          <Inbox className="h-5 w-5" />
          Inbox
          {messages.data && (
            <span className="text-sm font-normal text-muted-foreground">
              {messages.data.total} messages
            </span>
          )}
        </h2>

        {/* Search */}
        <div className="relative w-full sm:w-72">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <input
            type="text"
            placeholder="Search sender, subject..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full pl-9 pr-3 py-2 text-sm border rounded-md bg-white focus:outline-none focus:ring-2 focus:ring-[#0F9ED5]/30 focus:border-[#0F9ED5]"
          />
        </div>
      </div>

      {/* Routing filter pills */}
      <div className="flex flex-wrap gap-2">
        {ROUTING_FILTERS.map((filter) => {
          const count = filter.value
            ? counts.data?.counts[filter.value] ?? 0
            : Object.values(counts.data?.counts ?? {}).reduce((a, b) => a + b, 0)
          const isActive = routingFilter === filter.value

          return (
            <button
              key={filter.value ?? "all"}
              onClick={() => handleRoutingFilter(filter.value)}
              className={cn(
                "inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-medium transition-colors border",
                isActive
                  ? "bg-[#0E2841] text-white border-[#0E2841]"
                  : "bg-white text-muted-foreground border-border hover:bg-muted/50"
              )}
            >
              {filter.label}
              <span
                className={cn(
                  "text-[10px] font-mono",
                  isActive ? "text-white/70" : "text-muted-foreground/60"
                )}
              >
                {count}
              </span>
            </button>
          )
        })}
      </div>

      {/* Table */}
      {messages.isLoading ? (
        <div className="space-y-2">
          {[...Array(8)].map((_, i) => (
            <div key={i} className="h-12 bg-white rounded animate-pulse shadow-sm" />
          ))}
        </div>
      ) : (messages.data?.messages.length ?? 0) === 0 ? (
        <div className="bg-white rounded-lg shadow-sm py-12 text-center">
          <p className="text-muted-foreground">
            {search ? `No messages matching "${search}"` : "No messages yet"}
          </p>
        </div>
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
                <TableRow
                  key={msg.id}
                  className="hover:bg-muted/50 cursor-pointer"
                  onClick={() => setSelectedMessageId(msg.id)}
                >
                  <TableCell className="py-3">
                    <p className="text-sm font-medium truncate max-w-[200px]">
                      {msg.sender}
                    </p>
                  </TableCell>
                  <TableCell className="py-3 hidden md:table-cell">
                    <p className="text-sm truncate max-w-[300px]">
                      {msg.subject ?? "—"}
                    </p>
                  </TableCell>
                  <TableCell className="py-3">
                    {msg.routing_status ? (
                      <Badge
                        variant="secondary"
                        className={`text-xs ${routingColors[msg.routing_status] ?? ""}`}
                      >
                        {msg.routing_label}
                      </Badge>
                    ) : (
                      <span className="text-xs text-muted-foreground">—</span>
                    )}
                  </TableCell>
                  <TableCell className="py-3 hidden lg:table-cell">
                    {msg.rfq ? (
                      <span className="text-xs text-[#0F9ED5]">
                        #{msg.rfq.id} {msg.rfq.customer_name}
                      </span>
                    ) : (
                      <span className="text-xs text-muted-foreground">—</span>
                    )}
                  </TableCell>
                  <TableCell className="text-xs text-muted-foreground text-right py-3">
                    {msg.received_at ? formatRelativeTime(msg.received_at) : "—"}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-between">
          <p className="text-xs text-muted-foreground">
            Showing {page * PAGE_SIZE + 1}–
            {Math.min((page + 1) * PAGE_SIZE, messages.data?.total ?? 0)} of{" "}
            {messages.data?.total}
          </p>
          <div className="flex gap-2">
            <button
              onClick={() => setPage((p) => Math.max(0, p - 1))}
              disabled={page === 0}
              className="px-3 py-1 text-xs border rounded-md disabled:opacity-40 hover:bg-muted/50"
            >
              Previous
            </button>
            <button
              onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
              disabled={page >= totalPages - 1}
              className="px-3 py-1 text-xs border rounded-md disabled:opacity-40 hover:bg-muted/50"
            >
              Next
            </button>
          </div>
        </div>
      )}

      {/* Email thread modal (#111) — opens when clicking any message row */}
      <MessageThreadModal
        messageId={selectedMessageId}
        onClose={() => setSelectedMessageId(null)}
        onOpenRfq={(rfqId) => setSelectedRfqId(rfqId)}
      />

      {/* RFQ detail modal (#110, #112) — accessible from thread modal's RFQ link */}
      <RfqDetailDrawer
        rfqId={selectedRfqId}
        onClose={() => setSelectedRfqId(null)}
        rfqIds={messages.data?.messages
          ?.map((m: { rfq_id: number | null }) => m.rfq_id)
          .filter((id: number | null): id is number => id != null)
          .filter((id: number, i: number, arr: number[]) => arr.indexOf(id) === i)}
        onSelectRfq={setSelectedRfqId}
      />
    </div>
  )
}
