/**
 * hooks/use-metrics.ts — React Query hooks for system metrics and alerts (#52).
 *
 * Polls /api/metrics and /api/alerts every 30 seconds to keep the
 * Agent page observability cards up to date.
 */

import { useQuery } from "@tanstack/react-query"
import { api } from "@/lib/api"

export interface MetricsData {
  period: string
  calls: { total: number; failed: number; error_rate_pct: number }
  cost: { today_usd: number; week_usd: number }
  latency: { avg_ms: number | null; p95_ms: number | null }
  runs: { total: number; failed: number }
  queue: { pending: number; running: number; failed_24h: number }
}

export interface AlertItem {
  type: string
  severity: "warning" | "critical"
  message: string
}

export interface AlertsData {
  alerts: AlertItem[]
  total: number
  checked_at: string
}

export function useMetrics() {
  return useQuery({
    queryKey: ["metrics"],
    queryFn: () => api.get<MetricsData>("/api/metrics"),
    refetchInterval: 30_000,
  })
}

export function useAlerts() {
  return useQuery({
    queryKey: ["alerts"],
    queryFn: () => api.get<AlertsData>("/api/alerts"),
    refetchInterval: 30_000,
  })
}
