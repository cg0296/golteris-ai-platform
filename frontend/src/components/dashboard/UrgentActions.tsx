/**
 * components/dashboard/UrgentActions.tsx — Pending approval list for the dashboard.
 *
 * Shows items that need the broker's attention: draft emails waiting for
 * approval, low-confidence extractions, etc. Each item has an inline
 * "Approve" button that calls POST /api/approvals/{id}/approve (C2).
 *
 * Data comes from usePendingApprovals (polls every 10s).
 */

import { AlertCircle } from "lucide-react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { UrgentActionCard } from "./UrgentActionCard"
import type { ApprovalItem } from "@/types/api"

interface UrgentActionsProps {
  approvals: ApprovalItem[]
  total: number
  isLoading: boolean
  onApprove: (id: number) => void
  approvingId: number | null
}

export function UrgentActions({
  approvals,
  total,
  isLoading,
  onApprove,
  approvingId,
}: UrgentActionsProps) {
  return (
    <Card className="shadow-sm">
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <CardTitle className="text-base font-semibold flex items-center gap-2">
            <AlertCircle className="h-4 w-4 text-red-500" />
            Urgent Actions
            {total > 0 && (
              <span className="text-xs font-normal text-muted-foreground">
                ({total})
              </span>
            )}
          </CardTitle>
        </div>
      </CardHeader>
      <CardContent className="pt-0">
        {isLoading ? (
          <div className="space-y-3">
            {[...Array(3)].map((_, i) => (
              <div key={i} className="h-16 bg-muted/50 rounded animate-pulse" />
            ))}
          </div>
        ) : approvals.length === 0 ? (
          <p className="text-sm text-muted-foreground py-4 text-center">
            No urgent actions right now
          </p>
        ) : (
          <div>
            {approvals.map((approval) => (
              <UrgentActionCard
                key={approval.id}
                approval={approval}
                onApprove={onApprove}
                isApproving={approvingId === approval.id}
              />
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  )
}
