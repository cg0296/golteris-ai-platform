/**
 * components/dashboard/ActivityRow.tsx — Single activity event in the feed.
 *
 * Displays an audit event with a colored icon (based on event_type),
 * the human-readable description (C3), and a relative timestamp.
 */

import {
  Plus,
  CheckCircle,
  AlertTriangle,
  FileEdit,
  Send,
  Bot,
  Info,
} from "lucide-react"
import { cn, formatRelativeTime } from "@/lib/utils"
import type { ActivityEvent } from "@/types/api"
import type { LucideIcon } from "lucide-react"

/** Map event_type to icon and color for the activity feed. */
function getEventIcon(eventType: string): { icon: LucideIcon; color: string } {
  switch (eventType) {
    case "rfq_created":
      return { icon: Plus, color: "text-purple-500 bg-purple-50" }
    case "approval_approved":
    case "state_changed":
      return { icon: CheckCircle, color: "text-green-500 bg-green-50" }
    case "escalated_for_review":
      return { icon: AlertTriangle, color: "text-amber-500 bg-amber-50" }
    case "extraction_completed":
      return { icon: FileEdit, color: "text-blue-500 bg-blue-50" }
    case "email_sent":
      return { icon: Send, color: "text-teal-500 bg-teal-50" }
    default:
      return { icon: Info, color: "text-gray-500 bg-gray-50" }
  }
}

interface ActivityRowProps {
  event: ActivityEvent
}

export function ActivityRow({ event }: ActivityRowProps) {
  const { icon: Icon, color } = getEventIcon(event.event_type)
  const [iconColor, iconBg] = color.split(" ")

  return (
    <div className="flex items-start gap-3 py-2.5 border-b last:border-0">
      <div
        className={cn(
          "flex items-center justify-center h-7 w-7 rounded-full shrink-0 mt-0.5",
          iconBg
        )}
      >
        <Icon className={cn("h-3.5 w-3.5", iconColor)} />
      </div>
      <div className="min-w-0 flex-1">
        <p className="text-sm text-[#0E2841] leading-snug">
          {event.description}
        </p>
        <p className="text-xs text-muted-foreground mt-0.5">
          {formatRelativeTime(event.created_at)}
        </p>
      </div>
    </div>
  )
}
