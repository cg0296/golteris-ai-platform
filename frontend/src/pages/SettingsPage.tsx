/**
 * pages/SettingsPage.tsx — Settings page with demo reseed button (#88).
 *
 * Currently provides a "Reset Demo Data" button that clears and reseeds
 * the database with realistic Beltmann demo scenarios. Future issues
 * will add workflow toggles (#31) and agent controls (#44).
 */

import { useState } from "react"
import { RotateCcw, AlertTriangle, Settings } from "lucide-react"
import { toast } from "sonner"
import { useQueryClient } from "@tanstack/react-query"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { api } from "@/lib/api"

export function SettingsPage() {
  const [isReseeding, setIsReseeding] = useState(false)
  const [showConfirm, setShowConfirm] = useState(false)
  const queryClient = useQueryClient()

  const handleReseed = async () => {
    setIsReseeding(true)
    setShowConfirm(false)
    try {
      const result = await api.post<{ status: string; seeded: Record<string, number> }>(
        "/api/dev/reseed"
      )
      // Invalidate all cached queries so the UI refreshes everywhere
      queryClient.invalidateQueries()
      const counts = result.seeded
      toast.success("Demo data reset", {
        description: `Seeded ${counts.rfqs} RFQs, ${counts.messages} messages, ${counts.approvals} approvals`,
      })
    } catch (err) {
      toast.error("Reseed failed", {
        description: err instanceof Error ? err.message : "Unknown error",
      })
    } finally {
      setIsReseeding(false)
    }
  }

  return (
    <div className="p-4 lg:p-6 max-w-3xl space-y-6">
      <h2 className="text-xl font-semibold text-[#0E2841] flex items-center gap-2">
        <Settings className="h-5 w-5" />
        Settings
      </h2>

      {/* Demo Data section */}
      <Card className="shadow-sm">
        <CardHeader>
          <CardTitle className="text-base">Demo Data</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <p className="text-sm text-muted-foreground">
            Reset all data to a fresh demo state with realistic Beltmann scenarios.
            This clears everything and reseeds RFQs, messages, approvals, and activity.
          </p>

          {showConfirm ? (
            <div className="bg-amber-50 border border-amber-200 rounded-lg p-4 space-y-3">
              <div className="flex items-start gap-2">
                <AlertTriangle className="h-4 w-4 text-amber-600 mt-0.5 shrink-0" />
                <p className="text-sm text-amber-800">
                  This will delete all existing data and replace it with demo data.
                  This cannot be undone.
                </p>
              </div>
              <div className="flex gap-2">
                <Button
                  onClick={handleReseed}
                  disabled={isReseeding}
                  className="bg-red-600 hover:bg-red-700 text-white"
                  size="sm"
                >
                  {isReseeding ? (
                    <>
                      <RotateCcw className="h-3.5 w-3.5 mr-1.5 animate-spin" />
                      Reseeding...
                    </>
                  ) : (
                    "Yes, reset all data"
                  )}
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setShowConfirm(false)}
                  disabled={isReseeding}
                >
                  Cancel
                </Button>
              </div>
            </div>
          ) : (
            <Button
              variant="outline"
              onClick={() => setShowConfirm(true)}
              className="text-amber-700 border-amber-300 hover:bg-amber-50"
            >
              <RotateCcw className="h-4 w-4 mr-2" />
              Reset Demo Data
            </Button>
          )}
        </CardContent>
      </Card>

      {/* Placeholder for future settings */}
      <Card className="shadow-sm">
        <CardHeader>
          <CardTitle className="text-base">Workflow Controls</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">
            Workflow toggles and kill switch coming in issue #31.
          </p>
        </CardContent>
      </Card>

      <Card className="shadow-sm">
        <CardHeader>
          <CardTitle className="text-base">Agent Permissions</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">
            Per-agent permissions and cost caps coming in issue #44.
          </p>
        </CardContent>
      </Card>
    </div>
  )
}
