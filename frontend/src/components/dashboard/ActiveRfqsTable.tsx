/**
 * components/dashboard/ActiveRfqsTable.tsx — 6-row RFQ preview table.
 *
 * Shows the most recently updated active RFQs in a compact table.
 * Includes a "View all" link that navigates to the full /rfqs page.
 * State labels use plain English (C3) — provided by the backend.
 */

import { Link } from "react-router-dom"
import { FileText } from "lucide-react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { Badge } from "@/components/ui/badge"
import { formatRelativeTime } from "@/lib/utils"
import type { RfqSummary } from "@/types/api"

/** Map RFQ state values to badge color variants. */
const stateColors: Record<string, string> = {
  needs_clarification: "bg-amber-100 text-amber-800",
  ready_to_quote: "bg-blue-100 text-blue-800",
  waiting_on_carriers: "bg-purple-100 text-purple-800",
  quotes_received: "bg-green-100 text-green-800",
  waiting_on_broker: "bg-red-100 text-red-800",
  quote_sent: "bg-teal-100 text-teal-800",
}

interface ActiveRfqsTableProps {
  rfqs: RfqSummary[]
  total: number
  isLoading: boolean
}

export function ActiveRfqsTable({
  rfqs,
  total,
  isLoading,
}: ActiveRfqsTableProps) {
  return (
    <Card className="shadow-sm">
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <CardTitle className="text-base font-semibold flex items-center gap-2">
            <FileText className="h-4 w-4 text-[#0F9ED5]" />
            Active RFQs
            {total > 0 && (
              <span className="text-xs font-normal text-muted-foreground">
                ({total})
              </span>
            )}
          </CardTitle>
          <Link
            to="/rfqs"
            className="text-sm text-[#0F9ED5] hover:underline"
          >
            View all
          </Link>
        </div>
      </CardHeader>
      <CardContent className="pt-0">
        {isLoading ? (
          <div className="space-y-2">
            {[...Array(4)].map((_, i) => (
              <div key={i} className="h-10 bg-muted/50 rounded animate-pulse" />
            ))}
          </div>
        ) : rfqs.length === 0 ? (
          <p className="text-sm text-muted-foreground py-4 text-center">
            No active RFQs
          </p>
        ) : (
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="text-xs">Customer</TableHead>
                  <TableHead className="text-xs hidden sm:table-cell">Route</TableHead>
                  <TableHead className="text-xs">Status</TableHead>
                  <TableHead className="text-xs text-right">Updated</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {rfqs.map((rfq) => (
                  <TableRow key={rfq.id} className="cursor-pointer hover:bg-muted/50">
                    <TableCell className="text-sm font-medium py-2">
                      {rfq.customer_name ?? "Unknown"}
                      {rfq.customer_company && (
                        <span className="block text-xs text-muted-foreground">
                          {rfq.customer_company}
                        </span>
                      )}
                    </TableCell>
                    <TableCell className="text-sm py-2 hidden sm:table-cell">
                      {rfq.origin && rfq.destination
                        ? `${rfq.origin} → ${rfq.destination}`
                        : "—"}
                    </TableCell>
                    <TableCell className="py-2">
                      <Badge
                        variant="secondary"
                        className={`text-xs ${stateColors[rfq.state] ?? ""}`}
                      >
                        {rfq.state_label}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground text-right py-2">
                      {formatRelativeTime(rfq.updated_at)}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
