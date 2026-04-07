/**
 * components/dashboard/KpiCard.tsx — Single KPI metric card.
 *
 * Displays one of the four dashboard KPIs with an icon, value, label,
 * and optional subtitle. Matches the proof-of-concept KPI strip design.
 */

import type { LucideIcon } from "lucide-react"
import { Card, CardContent } from "@/components/ui/card"
import { cn } from "@/lib/utils"

interface KpiCardProps {
  /** Lucide icon component */
  icon: LucideIcon
  /** Main numeric or string value */
  value: string | number
  /** Label below the value (e.g., "Needs Review") */
  label: string
  /** Subtitle or secondary info (e.g., "3 urgent") */
  subtitle?: string
  /** Background color class for the icon circle */
  iconBg?: string
  /** Text color class for the icon */
  iconColor?: string
}

export function KpiCard({
  icon: Icon,
  value,
  label,
  subtitle,
  iconBg = "bg-[#E8F4FC]",
  iconColor = "text-[#0F9ED5]",
}: KpiCardProps) {
  return (
    <Card className="shadow-sm">
      <CardContent className="flex items-center gap-4 p-4">
        <div
          className={cn(
            "flex items-center justify-center h-10 w-10 rounded-lg shrink-0",
            iconBg
          )}
        >
          <Icon className={cn("h-5 w-5", iconColor)} />
        </div>
        <div className="min-w-0">
          <p className="text-2xl font-bold text-[#0E2841] leading-tight">
            {value}
          </p>
          <p className="text-sm text-muted-foreground truncate">{label}</p>
          {subtitle && (
            <p className="text-xs text-muted-foreground mt-0.5">{subtitle}</p>
          )}
        </div>
      </CardContent>
    </Card>
  )
}
