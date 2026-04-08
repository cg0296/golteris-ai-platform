/**
 * components/agent/MetricsTab.tsx — System metrics and alerts dashboard (#52).
 *
 * Shows real-time system health: call counts, error rates, cost tracking,
 * latency, queue status, and active alerts. Polls every 30 seconds.
 *
 * Cross-cutting constraints:
 *   C5 — Cost per day/week visible and monitored
 *   NFR-OB-4 — Call count, error rate, p95 latency, cost per day
 */

import { AlertTriangle, Activity, DollarSign, Zap, AlertCircle } from "lucide-react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { useMetrics, useAlerts } from "@/hooks/use-metrics"

export function MetricsTab() {
  const metrics = useMetrics()
  const alerts = useAlerts()

  const m = metrics.data
  const a = alerts.data

  return (
    <div className="space-y-6">
      {/* Active alerts */}
      {(a?.total ?? 0) > 0 && (
        <div className="space-y-2">
          {a?.alerts.map((alert, i) => (
            <div
              key={i}
              className={`flex items-start gap-2 p-3 rounded-lg border ${
                alert.severity === "critical"
                  ? "bg-red-50 border-red-200"
                  : "bg-amber-50 border-amber-200"
              }`}
            >
              <AlertTriangle className={`h-4 w-4 mt-0.5 shrink-0 ${
                alert.severity === "critical" ? "text-red-600" : "text-amber-600"
              }`} />
              <div>
                <Badge variant="secondary" className={`text-[10px] mb-1 ${
                  alert.severity === "critical" ? "bg-red-100 text-red-800" : "bg-amber-100 text-amber-800"
                }`}>
                  {alert.type}
                </Badge>
                <p className="text-sm">{alert.message}</p>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Metrics grid */}
      {metrics.isLoading ? (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          {[...Array(8)].map((_, i) => (
            <div key={i} className="h-24 bg-white rounded-lg animate-pulse shadow-sm" />
          ))}
        </div>
      ) : m ? (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          {/* Calls */}
          <MetricCard
            icon={<Activity className="h-4 w-4 text-blue-500" />}
            label="API Calls (24h)"
            value={m.calls.total.toString()}
          />
          <MetricCard
            icon={<AlertCircle className="h-4 w-4 text-red-500" />}
            label="Error Rate"
            value={`${m.calls.error_rate_pct}%`}
            subtext={`${m.calls.failed} failed`}
            alert={m.calls.error_rate_pct > 5}
          />

          {/* Cost */}
          <MetricCard
            icon={<DollarSign className="h-4 w-4 text-green-500" />}
            label="Cost Today"
            value={`$${m.cost.today_usd.toFixed(2)}`}
          />
          <MetricCard
            icon={<DollarSign className="h-4 w-4 text-green-500" />}
            label="Cost This Week"
            value={`$${m.cost.week_usd.toFixed(2)}`}
          />

          {/* Latency */}
          <MetricCard
            icon={<Zap className="h-4 w-4 text-amber-500" />}
            label="Avg Latency"
            value={m.latency.avg_ms ? `${m.latency.avg_ms.toFixed(0)}ms` : "—"}
          />
          <MetricCard
            icon={<Zap className="h-4 w-4 text-amber-500" />}
            label="P95 Latency"
            value={m.latency.p95_ms ? `${m.latency.p95_ms.toFixed(0)}ms` : "—"}
          />

          {/* Queue */}
          <MetricCard
            icon={<Activity className="h-4 w-4 text-purple-500" />}
            label="Queue (Pending)"
            value={m.queue.pending.toString()}
            subtext={`${m.queue.running} running`}
            alert={m.queue.pending > 10}
          />
          <MetricCard
            icon={<Activity className="h-4 w-4 text-purple-500" />}
            label="Runs (24h)"
            value={m.runs.total.toString()}
            subtext={m.runs.failed > 0 ? `${m.runs.failed} failed` : "all succeeded"}
          />
        </div>
      ) : (
        <p className="text-sm text-muted-foreground text-center py-8">
          No metrics available
        </p>
      )}

      {/* No alerts message */}
      {(a?.total ?? 0) === 0 && !alerts.isLoading && (
        <div className="text-center py-4">
          <p className="text-sm text-muted-foreground">
            No active alerts — all systems normal
          </p>
        </div>
      )}
    </div>
  )
}

/** Single metric card with icon, label, value, and optional alert styling. */
function MetricCard({
  icon,
  label,
  value,
  subtext,
  alert = false,
}: {
  icon: React.ReactNode
  label: string
  value: string
  subtext?: string
  alert?: boolean
}) {
  return (
    <Card className={`shadow-sm ${alert ? "border-amber-300 bg-amber-50/50" : ""}`}>
      <CardContent className="p-4">
        <div className="flex items-center gap-2 mb-2">
          {icon}
          <p className="text-xs text-muted-foreground">{label}</p>
        </div>
        <p className="text-2xl font-bold text-[#0E2841]">{value}</p>
        {subtext && (
          <p className="text-xs text-muted-foreground mt-0.5">{subtext}</p>
        )}
      </CardContent>
    </Card>
  )
}
