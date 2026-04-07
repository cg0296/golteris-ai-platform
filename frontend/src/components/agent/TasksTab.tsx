/**
 * components/agent/TasksTab.tsx — Agent tasks queue view (#39).
 *
 * Shows the current job queue: running, queued, scheduled, completed.
 * Reads from the jobs table via the API.
 */

import { useQuery } from "@tanstack/react-query"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent } from "@/components/ui/card"
import { api } from "@/lib/api"
import { formatRelativeTime } from "@/lib/utils"

interface JobItem {
  id: number
  job_type: string
  status: string
  rfq_id: number | null
  retry_count: number
  created_at: string
  started_at: string | null
  finished_at: string | null
  error_message: string | null
}

const statusColors: Record<string, string> = {
  pending: "bg-amber-100 text-amber-800",
  running: "bg-blue-100 text-blue-800",
  completed: "bg-green-100 text-green-800",
  failed: "bg-red-100 text-red-800",
}

export function TasksTab() {
  const jobs = useQuery({
    queryKey: ["agent", "jobs"],
    queryFn: () => api.get<{ jobs: JobItem[]; total: number }>("/api/agent/jobs"),
  })

  return (
    <div className="space-y-4">
      <p className="text-sm text-muted-foreground">
        Live view of the background job queue — what's running, what's waiting, and what's done.
      </p>

      {jobs.isLoading ? (
        <div className="space-y-2">
          {[...Array(4)].map((_, i) => (
            <div key={i} className="h-12 bg-white rounded animate-pulse shadow-sm" />
          ))}
        </div>
      ) : jobs.isError ? (
        <Card className="shadow-sm">
          <CardContent className="py-8 text-center">
            <p className="text-muted-foreground">Job queue endpoint not available yet</p>
          </CardContent>
        </Card>
      ) : (jobs.data?.jobs.length ?? 0) === 0 ? (
        <Card className="shadow-sm">
          <CardContent className="py-8 text-center">
            <p className="text-muted-foreground">No jobs in queue</p>
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-2">
          {jobs.data?.jobs.map((job) => (
            <div key={job.id} className="flex items-center justify-between bg-white rounded-lg shadow-sm border p-3">
              <div>
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium">{job.job_type}</span>
                  <Badge variant="secondary" className={`text-[10px] ${statusColors[job.status] ?? ""}`}>
                    {job.status}
                  </Badge>
                </div>
                <p className="text-xs text-muted-foreground">
                  {job.rfq_id ? `RFQ #${job.rfq_id}` : "System"} · {formatRelativeTime(job.created_at)}
                  {job.retry_count > 0 && ` · Retry ${job.retry_count}`}
                </p>
              </div>
              {job.error_message && (
                <span className="text-xs text-red-600 max-w-[200px] truncate">{job.error_message}</span>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
