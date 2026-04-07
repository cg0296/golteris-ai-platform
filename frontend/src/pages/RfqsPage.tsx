/**
 * pages/RfqsPage.tsx — Full RFQs list view (#29).
 *
 * Shows all RFQs in a paginated table with:
 * - State filter pills with live counts
 * - Search input for shipper/route
 * - Full-width table: Load #, Shipper, Route, Equipment, State, Updated
 * - Row click opens the RFQ detail drawer (#27)
 *
 * Designed to scale to 500+ RFQs per acceptance criteria.
 *
 * Cross-cutting constraints:
 *   C3 — State labels use plain English from backend
 */

import { useState, useMemo } from "react"
import { Search } from "lucide-react"
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
import { useRfqList, useRfqCounts } from "@/hooks/use-rfq-list"
import { formatRelativeTime } from "@/lib/utils"
import { cn } from "@/lib/utils"

/** State filter options with plain-English labels (C3) and colors. */
const STATE_FILTERS = [
  { value: null, label: "All" },
  { value: "needs_clarification", label: "Needs clarification", color: "bg-amber-100 text-amber-800" },
  { value: "ready_to_quote", label: "Ready to quote", color: "bg-blue-100 text-blue-800" },
  { value: "waiting_on_carriers", label: "Waiting on carriers", color: "bg-purple-100 text-purple-800" },
  { value: "quotes_received", label: "Quotes received", color: "bg-green-100 text-green-800" },
  { value: "waiting_on_broker", label: "Waiting on broker", color: "bg-red-100 text-red-800" },
  { value: "quote_sent", label: "Quote sent", color: "bg-teal-100 text-teal-800" },
  { value: "won", label: "Won", color: "bg-green-200 text-green-900" },
  { value: "lost", label: "Lost", color: "bg-gray-100 text-gray-600" },
  { value: "cancelled", label: "Cancelled", color: "bg-gray-100 text-gray-600" },
] as const

/** Map state values to badge color classes (reused from ActiveRfqsTable). */
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

const PAGE_SIZE = 50

export function RfqsPage() {
  const [stateFilter, setStateFilter] = useState<string | null>(null)
  const [search, setSearch] = useState("")
  const [page, setPage] = useState(0)
  const [selectedRfqId, setSelectedRfqId] = useState<number | null>(null)

  // Debounce search to avoid hammering the API on every keystroke
  const [debouncedSearch, setDebouncedSearch] = useState("")
  useMemo(() => {
    const timer = setTimeout(() => setDebouncedSearch(search), 300)
    return () => clearTimeout(timer)
  }, [search])

  // Reset to first page when filters change
  const handleStateFilter = (state: string | null) => {
    setStateFilter(state)
    setPage(0)
  }

  const rfqs = useRfqList({
    limit: PAGE_SIZE,
    offset: page * PAGE_SIZE,
    state: stateFilter,
    search: debouncedSearch,
    includeTerminal: true,
  })
  const counts = useRfqCounts()

  const totalPages = Math.ceil((rfqs.data?.total ?? 0) / PAGE_SIZE)

  return (
    <div className="p-4 lg:p-6 max-w-7xl space-y-4">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
        <h2 className="text-xl font-semibold text-[#0E2841]">
          RFQs
          {rfqs.data && (
            <span className="text-sm font-normal text-muted-foreground ml-2">
              {rfqs.data.total} total
            </span>
          )}
        </h2>

        {/* Search input */}
        <div className="relative w-full sm:w-72">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <input
            type="text"
            placeholder="Search shipper, route..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full pl-9 pr-3 py-2 text-sm border rounded-md bg-white focus:outline-none focus:ring-2 focus:ring-[#0F9ED5]/30 focus:border-[#0F9ED5]"
          />
        </div>
      </div>

      {/* Filter pills */}
      <div className="flex flex-wrap gap-2">
        {STATE_FILTERS.map((filter) => {
          const count = filter.value
            ? counts.data?.counts[filter.value] ?? 0
            : Object.values(counts.data?.counts ?? {}).reduce((a, b) => a + b, 0)
          const isActive = stateFilter === filter.value

          return (
            <button
              key={filter.value ?? "all"}
              onClick={() => handleStateFilter(filter.value)}
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
      {rfqs.isLoading ? (
        <div className="space-y-2">
          {[...Array(8)].map((_, i) => (
            <div key={i} className="h-12 bg-white rounded animate-pulse shadow-sm" />
          ))}
        </div>
      ) : (rfqs.data?.rfqs.length ?? 0) === 0 ? (
        <div className="bg-white rounded-lg shadow-sm py-12 text-center">
          <p className="text-muted-foreground">
            {search ? `No RFQs matching "${search}"` : "No RFQs found"}
          </p>
        </div>
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
                <TableHead className="text-xs text-right">Updated</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rfqs.data?.rfqs.map((rfq) => (
                <TableRow
                  key={rfq.id}
                  className="cursor-pointer hover:bg-muted/50"
                  onClick={() => setSelectedRfqId(rfq.id)}
                >
                  <TableCell className="text-xs font-mono text-muted-foreground py-3">
                    {rfq.id}
                  </TableCell>
                  <TableCell className="py-3">
                    <p className="text-sm font-medium">{rfq.customer_name ?? "Unknown"}</p>
                    {rfq.customer_company && (
                      <p className="text-xs text-muted-foreground">{rfq.customer_company}</p>
                    )}
                  </TableCell>
                  <TableCell className="text-sm py-3 hidden md:table-cell">
                    {rfq.origin && rfq.destination
                      ? `${rfq.origin} → ${rfq.destination}`
                      : "—"}
                  </TableCell>
                  <TableCell className="text-sm py-3 hidden lg:table-cell">
                    {rfq.equipment_type ?? "—"}
                    {rfq.truck_count && rfq.truck_count > 1 && (
                      <span className="text-xs text-muted-foreground ml-1">
                        ×{rfq.truck_count}
                      </span>
                    )}
                  </TableCell>
                  <TableCell className="py-3">
                    <Badge
                      variant="secondary"
                      className={`text-xs ${stateColors[rfq.state] ?? ""}`}
                    >
                      {rfq.state_label}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-xs text-muted-foreground text-right py-3">
                    {formatRelativeTime(rfq.updated_at)}
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
            {Math.min((page + 1) * PAGE_SIZE, rfqs.data?.total ?? 0)} of{" "}
            {rfqs.data?.total}
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

      {/* RFQ detail modal (#110, #112) — J/K navigates prev/next */}
      <RfqDetailDrawer
        rfqId={selectedRfqId}
        onClose={() => setSelectedRfqId(null)}
        rfqIds={rfqs.data?.rfqs.map((r: { id: number }) => r.id)}
        onSelectRfq={setSelectedRfqId}
      />
    </div>
  )
}
