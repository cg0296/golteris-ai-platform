/**
 * components/dashboard/KpiStrip.tsx — Four-card KPI strip for the dashboard.
 *
 * Renders the four top-level metrics: Needs Review, Active RFQs,
 * Quotes Received, and Time Saved Today. Data comes from the
 * useDashboardSummary hook (polls /api/dashboard/summary every 10s).
 */

import { AlertCircle, FileText, TrendingUp, Clock } from "lucide-react"
import { KpiCard } from "./KpiCard"
import { formatTimeSaved } from "@/lib/utils"
import type { DashboardSummary } from "@/types/api"

interface KpiStripProps {
  data: DashboardSummary | undefined
  isLoading: boolean
}

export function KpiStrip({ data, isLoading }: KpiStripProps) {
  if (isLoading || !data) {
    return (
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {[...Array(4)].map((_, i) => (
          <div
            key={i}
            className="h-[88px] rounded-lg bg-white animate-pulse shadow-sm"
          />
        ))}
      </div>
    )
  }

  return (
    <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
      <KpiCard
        icon={AlertCircle}
        value={data.needs_review}
        label="Needs Review"
        iconBg="bg-amber-50"
        iconColor="text-amber-500"
      />
      <KpiCard
        icon={FileText}
        value={data.active_rfqs}
        label="Active RFQs"
        iconBg="bg-[#E8F4FC]"
        iconColor="text-[#0F9ED5]"
      />
      <KpiCard
        icon={TrendingUp}
        value={data.quotes_received_today}
        label="Quotes Received"
        iconBg="bg-green-50"
        iconColor="text-green-600"
      />
      <KpiCard
        icon={Clock}
        value={formatTimeSaved(data.time_saved_minutes)}
        label="Time Saved Today"
        iconBg="bg-purple-50"
        iconColor="text-purple-600"
      />
    </div>
  )
}
