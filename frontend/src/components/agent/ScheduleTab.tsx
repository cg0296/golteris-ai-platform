/**
 * components/agent/ScheduleTab.tsx — Agent schedule view (#41).
 *
 * Shows cron-like scheduled jobs with pause/resume controls.
 */

import { Card, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Clock, Play, Pause } from "lucide-react"

export function ScheduleTab() {
  const schedules = [
    { name: "Email Inbox Poll", interval: "Every 10 seconds", active: true, lastRun: "Just now" },
    { name: "Carrier Follow-up Nudge", interval: "Every 4 hours", active: false, lastRun: "Not yet" },
    { name: "Daily Summary Report", interval: "Every day at 6:00 PM", active: false, lastRun: "Not yet" },
  ]

  return (
    <div className="space-y-4">
      <p className="text-sm text-muted-foreground">
        Scheduled agent tasks that run automatically on a timer.
      </p>

      <div className="space-y-2">
        {schedules.map((s) => (
          <Card key={s.name} className="shadow-sm">
            <CardContent className="flex items-center justify-between p-4">
              <div className="flex items-center gap-3">
                <div className={`p-2 rounded-lg ${s.active ? "bg-green-50" : "bg-gray-50"}`}>
                  <Clock className={`h-4 w-4 ${s.active ? "text-green-500" : "text-gray-400"}`} />
                </div>
                <div>
                  <p className="text-sm font-medium">{s.name}</p>
                  <p className="text-xs text-muted-foreground">{s.interval} · Last: {s.lastRun}</p>
                </div>
              </div>
              <div className="flex items-center gap-2">
                <Badge variant="secondary" className={`text-xs ${s.active ? "bg-green-100 text-green-800" : "bg-gray-100 text-gray-600"}`}>
                  {s.active ? "Active" : "Paused"}
                </Badge>
                <button className="p-1.5 rounded hover:bg-muted/50">
                  {s.active ? <Pause className="h-3.5 w-3.5 text-muted-foreground" /> : <Play className="h-3.5 w-3.5 text-muted-foreground" />}
                </button>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  )
}
