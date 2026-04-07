/**
 * pages/HistoryPage.tsx — History view with stat strip and closed RFQs (#30).
 *
 * Shows completed RFQs (won/lost/cancelled) with performance stats that
 * justify the product's value. The stat strip shows aggregated metrics;
 * the table shows individual closed RFQs with outcome and cycle time.
 *
 * Historical entries are immutable per FR-DM-5.
 *
 * Cross-cutting constraints:
 *   C3 — Outcome labels use plain English
 *   C5 — Time Saved uses defensible agent run durations
 */

import { useState } from "react"
import { Clock, CheckCircle, ThumbsUp, TrendingUp } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { KpiCard } from "@/components/dashboard/KpiCard"
import { RfqDetailDrawer } from "@/components/dashboard/RfqDetailDrawer"
import { useHistory } from "@/hooks/use-history"
import { formatRelativeTime, cn } from "@/lib/utils"

/** Outcome filter options. */
const OUTCOME_FILTERS = [
  { value: null, label: "All" },
  { value: "won", label: "Won", color: "bg-green-200 text-green-900" },
  { value: "lost", label: "Lost", color: "bg-gray-100 text-gray-600" },
  { value: "cancelled", label: "Cancelled", color: "bg-gray-100 text-gray-600" },
] as const

/** Time range filters. */
const PERIOD_FILTERS = [
  { value: null, label: "All Time" },
  { value: "today", label: "Today" },
  { value: "week", label: "This Week" },
  { value: "month", label: "This Month" },
] as const

const outcomeColors: Record<string, string> = {
  won: "bg-green-200 text-green-900",
  lost: "bg-gray-100 text-gray-600",
  cancelled: "bg-gray-100 text-gray-600",
}

const PAGE_SIZE = 50

export function HistoryPage() {
  const [outcomeFilter, setOutcomeFilter] = useState<string | null>(null)
  const [periodFilter, setPeriodFilter] = useState<string | null>(null)
  const [page, setPage] = useState(0)
  const [selectedRfqId, setSelectedRfqId] = useState<number | null>(null)

  const history = useHistory({
    limit: PAGE_SIZE,
    offset: page * PAGE_SIZE,
    outcome: outcomeFilter,
    period: periodFilter,
  })

  const stats = history.data?.stats
  const totalPages = Math.ceil((history.data?.total ?? 0) / PAGE_SIZE)

  return (
    <div className="p-4 lg:p-6 max-w-7xl space-y-6">
      {/* Header */}
      <h2 className="text-xl font-semibold text-[#0E2841]">History</h2>

      {/* Stat strip — 4 cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {stats ? (
          <>
            <KpiCard
              icon={CheckCircle}
              value={stats.completed_today}
              label="Completed Today"
              iconBg="bg-green-50"
              iconColor="text-green-600"
            />
            <KpiCard
              icon={Clock}
              value={stats.avg_time_to_quote_hours > 0 ? `${stats.avg_time_to_quote_hours}h` : "—"}
              label="Avg Time to Quote"
              iconBg="bg-[#E8F4FC]"
              iconColor="text-[#0F9ED5]"
            />
            <KpiCard
              icon={ThumbsUp}
              value={stats.approvals_this_week}
              label="Approvals This Week"
              iconBg="bg-purple-50"
              iconColor="text-purple-600"
            />
            <KpiCard
              icon={TrendingUp}
              value={stats.time_saved_hours > 0 ? `${stats.time_saved_hours}h` : "0h"}
              label="Time Saved This Week"
              iconBg="bg-amber-50"
              iconColor="text-amber-600"
            />
          </>
        ) : (
          [...Array(4)].map((_, i) => (
            <div key={i} className="h-[88px] rounded-lg bg-white animate-pulse shadow-sm" />
          ))
        )}
      </div>

      {/* Filters */}
      <div className="flex flex-wrap gap-2 items-center">
        {/* Outcome filters */}
        {OUTCOME_FILTERS.map((filter) => (
          <button
            key={filter.value ?? "all-outcome"}
            onClick={() => { setOutcomeFilter(filter.value); setPage(0) }}
            className={cn(
              "px-3 py-1 rounded-full text-xs font-medium transition-colors border",
              outcomeFilter === filter.value
                ? "bg-[#0E2841] text-white border-[#0E2841]"
                : "bg-white text-muted-foreground border-border hover:bg-muted/50"
            )}
          >
            {filter.label}
          </button>
        ))}

        <span className="text-muted-foreground text-xs mx-1">|</span>

        {/* Period filters */}
        {PERIOD_FILTERS.map((filter) => (
          <button
            key={filter.value ?? "all-period"}
            onClick={() => { setPeriodFilter(filter.value); setPage(0) }}
            className={cn(
              "px-3 py-1 rounded-full text-xs font-medium transition-colors border",
              periodFilter === filter.value
                ? "bg-[#0F9ED5] text-white border-[#0F9ED5]"
                : "bg-white text-muted-foreground border-border hover:bg-muted/50"
            )}
          >
            {filter.label}
          </button>
        ))}
      </div>

      {/* Table */}
      {history.isLoading ? (
        <div className="space-y-2">
          {[...Array(6)].map((_, i) => (
            <div key={i} className="h-12 bg-white rounded animate-pulse shadow-sm" />
          ))}
        </div>
      ) : (history.data?.rfqs.length ?? 0) === 0 ? (
        <div className="bg-white rounded-lg shadow-sm py-12 text-center">
          <p className="text-muted-foreground">No completed RFQs yet</p>
        </div>
      ) : (
        <div className="bg-white rounded-lg shadow-sm overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="text-xs w-16">#</TableHead>
                <TableHead className="text-xs">Shipper</TableHead>
                <TableHead className="text-xs hidden md:table-cell">Route</TableHead>
                <TableHead className="text-xs">Outcome</TableHead>
                <TableHead className="text-xs hidden lg:table-cell text-right">Quoted</TableHead>
                <TableHead className="text-xs hidden sm:table-cell text-right">Cycle</TableHead>
                <TableHead className="text-xs text-right">Closed</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {history.data?.rfqs.map((rfq) => (
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
                  <TableCell className="py-3">
                    <Badge
                      variant="secondary"
                      className={`text-xs ${outcomeColors[rfq.state] ?? ""}`}
                    >
                      {rfq.state_label}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-sm text-right py-3 hidden lg:table-cell">
                    {rfq.quoted_amount
                      ? `$${rfq.quoted_amount.toLocaleString()}`
                      : "—"}
                  </TableCell>
                  <TableCell className="text-xs text-muted-foreground text-right py-3 hidden sm:table-cell">
                    {rfq.cycle_hours != null ? `${rfq.cycle_hours}h` : "—"}
                  </TableCell>
                  <TableCell className="text-xs text-muted-foreground text-right py-3">
                    {rfq.closed_at ? formatRelativeTime(rfq.closed_at) : "—"}
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
            {Math.min((page + 1) * PAGE_SIZE, history.data?.total ?? 0)} of{" "}
            {history.data?.total}
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
        rfqIds={history.data?.rfqs.map((r: { id: number }) => r.id)}
        onSelectRfq={setSelectedRfqId}
      />
    </div>
  )
}
