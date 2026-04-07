/**
 * pages/SettingsPage.tsx — Settings page (#31, #44, #88).
 *
 * The broker's control center:
 * - Workflow toggles (C1 — on/off per workflow)
 * - Global kill switch (C1 — stop everything)
 * - System status (cost caps, mailbox, worker)
 * - Demo data reseed
 *
 * C1: The broker must be able to stop all agent work at any time.
 */

import { useState } from "react"
import {
  RotateCcw,
  AlertTriangle,
  Settings,
  Power,
  Mail,
  DollarSign,
  AlertOctagon,
  CheckCircle,
  XCircle,
  Bot,
  Eye,
} from "lucide-react"
import { toast } from "sonner"
import { useQueryClient } from "@tanstack/react-query"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Separator } from "@/components/ui/separator"
import { api } from "@/lib/api"
import {
  useWorkflows,
  useSystemStatus,
  useToggleWorkflow,
  useKillSwitch,
  useAgentControls,
  useUpdateAgent,
} from "@/hooks/use-settings"
import { useCostVisibility } from "@/lib/cost-visibility"

export function SettingsPage() {
  const workflows = useWorkflows()
  const status = useSystemStatus()
  const toggleWorkflow = useToggleWorkflow()
  const killSwitch = useKillSwitch()
  const agentControls = useAgentControls()
  const updateAgent = useUpdateAgent()
  const queryClient = useQueryClient()

  const { showCost, setShowCost } = useCostVisibility()
  const [showReseedConfirm, setShowReseedConfirm] = useState(false)
  const [showClearConfirm, setShowClearConfirm] = useState(false)
  const [isClearing, setIsClearing] = useState(false)
  const [showKillConfirm, setShowKillConfirm] = useState(false)
  const [isReseeding, setIsReseeding] = useState(false)

  const handleToggle = (id: number, currentlyEnabled: boolean) => {
    const action = currentlyEnabled ? "disabled" : "enabled"
    toggleWorkflow.mutate(
      { id, enabled: !currentlyEnabled },
      {
        onSuccess: () => toast.success(`Workflow ${action}`),
      }
    )
  }

  const handleKillSwitch = () => {
    setShowKillConfirm(false)
    killSwitch.mutate(undefined, {
      onSuccess: () => {
        toast.error("Kill switch activated", {
          description: "All workflows have been disabled",
        })
      },
    })
  }

  const handleReseed = async () => {
    setIsReseeding(true)
    setShowReseedConfirm(false)
    try {
      const result = await api.post<{ status: string; seeded: Record<string, number> }>(
        "/api/dev/reseed"
      )
      queryClient.invalidateQueries()
      const c = result.seeded
      toast.success("Demo data reset", {
        description: `Seeded ${c.rfqs} RFQs, ${c.messages} messages, ${c.carriers} carriers`,
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

      {/* Workflow Toggles (C1) */}
      <Card className="shadow-sm">
        <CardHeader className="pb-3">
          <div className="flex items-center justify-between">
            <CardTitle className="text-base flex items-center gap-2">
              <Power className="h-4 w-4" />
              Workflow Controls
            </CardTitle>
            {status.data && (
              <Badge variant="secondary" className="text-xs">
                {status.data.workflows.enabled} of {status.data.workflows.total} active
              </Badge>
            )}
          </div>
        </CardHeader>
        <CardContent className="space-y-3">
          {workflows.isLoading ? (
            <div className="space-y-3">
              {[...Array(3)].map((_, i) => (
                <div key={i} className="h-12 bg-muted/50 rounded animate-pulse" />
              ))}
            </div>
          ) : (workflows.data?.workflows ?? []).length === 0 ? (
            <p className="text-sm text-muted-foreground">No workflows configured</p>
          ) : (
            <>
              {workflows.data?.workflows.map((wf) => (
                <div key={wf.id} className="flex items-center justify-between py-2">
                  <div>
                    <p className="text-sm font-medium">{wf.name}</p>
                    <p className="text-xs text-muted-foreground">
                      {wf.enabled ? "Running — processing jobs" : "Disabled — no new jobs"}
                    </p>
                  </div>
                  <button
                    onClick={() => handleToggle(wf.id, wf.enabled)}
                    disabled={toggleWorkflow.isPending}
                    className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
                      wf.enabled ? "bg-green-500" : "bg-gray-300"
                    }`}
                  >
                    <span
                      className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                        wf.enabled ? "translate-x-6" : "translate-x-1"
                      }`}
                    />
                  </button>
                </div>
              ))}

              <Separator />

              {/* Kill Switch */}
              {showKillConfirm ? (
                <div className="bg-red-50 border border-red-200 rounded-lg p-4 space-y-3">
                  <div className="flex items-start gap-2">
                    <AlertOctagon className="h-4 w-4 text-red-600 mt-0.5 shrink-0" />
                    <p className="text-sm text-red-800">
                      This will immediately disable ALL workflows. No new jobs will be processed
                      until you re-enable them individually.
                    </p>
                  </div>
                  <div className="flex gap-2">
                    <Button
                      size="sm"
                      onClick={handleKillSwitch}
                      disabled={killSwitch.isPending}
                      className="bg-red-600 hover:bg-red-700 text-white"
                    >
                      {killSwitch.isPending ? "Stopping..." : "Confirm — Stop Everything"}
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => setShowKillConfirm(false)}
                    >
                      Cancel
                    </Button>
                  </div>
                </div>
              ) : (
                <Button
                  variant="outline"
                  onClick={() => setShowKillConfirm(true)}
                  className="text-red-600 border-red-300 hover:bg-red-50"
                >
                  <AlertOctagon className="h-4 w-4 mr-2" />
                  Kill Switch — Stop All Workflows
                </Button>
              )}
            </>
          )}
        </CardContent>
      </Card>

      {/* System Status */}
      <Card className="shadow-sm">
        <CardHeader>
          <CardTitle className="text-base">System Status</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          {/* Mailbox */}
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Mail className="h-4 w-4 text-muted-foreground" />
              <div>
                <p className="text-sm font-medium">Email Provider</p>
                <p className="text-xs text-muted-foreground">
                  {status.data?.mailbox.provider ?? "Loading..."}
                  {status.data?.mailbox.email && ` — ${status.data.mailbox.email}`}
                </p>
              </div>
            </div>
            {status.data?.mailbox.connected ? (
              <Badge variant="secondary" className="bg-green-100 text-green-800 text-xs">
                <CheckCircle className="h-3 w-3 mr-1" /> Connected
              </Badge>
            ) : (
              <Badge variant="secondary" className="bg-gray-100 text-gray-600 text-xs">
                <XCircle className="h-3 w-3 mr-1" /> Not connected
              </Badge>
            )}
          </div>

          <Separator />

          {/* Cost Caps */}
          <div className="flex items-center gap-2">
            <DollarSign className="h-4 w-4 text-muted-foreground" />
            <div>
              <p className="text-sm font-medium">LLM Cost Caps</p>
              <p className="text-xs text-muted-foreground">
                Daily: ${status.data?.cost_caps.daily ?? "—"} · Monthly: ${status.data?.cost_caps.monthly ?? "—"}
              </p>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Display Preferences (#113) */}
      <Card className="shadow-sm">
        <CardHeader className="pb-3">
          <CardTitle className="text-base flex items-center gap-2">
            <Eye className="h-4 w-4" />
            Display
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex items-center justify-between py-2">
            <div>
              <p className="text-sm font-medium">Show cost information</p>
              <p className="text-xs text-muted-foreground">
                Display LLM costs in Agent decisions, timeline, and controls
              </p>
            </div>
            <button
              onClick={() => setShowCost(!showCost)}
              className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
                showCost ? "bg-green-500" : "bg-gray-300"
              }`}
            >
              <span className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                showCost ? "translate-x-6" : "translate-x-1"
              }`} />
            </button>
          </div>
        </CardContent>
      </Card>

      {/* Agent Controls (#44) */}
      <Card className="shadow-sm">
        <CardHeader className="pb-3">
          <CardTitle className="text-base flex items-center gap-2">
            <Bot className="h-4 w-4" />
            Agent Controls
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          {agentControls.isLoading ? (
            <div className="space-y-3">
              {[...Array(4)].map((_, i) => (
                <div key={i} className="h-14 bg-muted/50 rounded animate-pulse" />
              ))}
            </div>
          ) : (
            <>
              {Object.entries(agentControls.data?.agents ?? {}).map(([agentId, config]) => (
                <div key={agentId} className="flex items-center justify-between py-2 border-b last:border-0">
                  <div className="flex-1 min-w-0 mr-4">
                    <div className="flex items-center gap-2">
                      <p className="text-sm font-medium">{config.name}</p>
                      <button
                        onClick={() => updateAgent.mutate({
                          agent_id: agentId,
                          enabled: !config.enabled,
                        }, {
                          onSuccess: () => toast.success(`${config.name} ${config.enabled ? "disabled" : "enabled"}`),
                        })}
                        className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors shrink-0 ${
                          config.enabled ? "bg-green-500" : "bg-gray-300"
                        }`}
                      >
                        <span className={`inline-block h-3.5 w-3.5 transform rounded-full bg-white transition-transform ${
                          config.enabled ? "translate-x-5" : "translate-x-0.5"
                        }`} />
                      </button>
                    </div>
                    <p className="text-xs text-muted-foreground mt-0.5">{config.description}</p>
                  </div>
                  <select
                    value={config.model}
                    onChange={(e) => updateAgent.mutate({
                      agent_id: agentId,
                      model: e.target.value,
                    }, {
                      onSuccess: () => toast.success(`${config.name} model updated`),
                    })}
                    className="text-xs border rounded px-2 py-1 bg-white shrink-0"
                  >
                    {(agentControls.data?.models ?? []).map((m) => (
                      <option key={m.id} value={m.id}>{m.name}</option>
                    ))}
                  </select>
                </div>
              ))}
            </>
          )}
        </CardContent>
      </Card>

      {/* Demo Data */}
      <Card className="shadow-sm">
        <CardHeader>
          <CardTitle className="text-base">Demo Data</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <p className="text-sm text-muted-foreground">
            Reset all data to a fresh demo state with realistic Beltmann scenarios.
          </p>
          {showReseedConfirm ? (
            <div className="bg-amber-50 border border-amber-200 rounded-lg p-4 space-y-3">
              <div className="flex items-start gap-2">
                <AlertTriangle className="h-4 w-4 text-amber-600 mt-0.5 shrink-0" />
                <p className="text-sm text-amber-800">
                  This will delete all existing data and replace it with demo data.
                </p>
              </div>
              <div className="flex gap-2">
                <Button
                  size="sm"
                  onClick={handleReseed}
                  disabled={isReseeding}
                  className="bg-red-600 hover:bg-red-700 text-white"
                >
                  {isReseeding ? "Reseeding..." : "Yes, reset all data"}
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setShowReseedConfirm(false)}
                >
                  Cancel
                </Button>
              </div>
            </div>
          ) : (
            <div className="flex gap-2">
              <Button
                variant="outline"
                onClick={() => setShowReseedConfirm(true)}
                className="text-amber-700 border-amber-300 hover:bg-amber-50"
              >
                <RotateCcw className="h-4 w-4 mr-2" />
                Reset Demo Data
              </Button>
              {showClearConfirm ? (
                <div className="flex gap-2">
                  <Button
                    size="sm"
                    onClick={async () => {
                      setIsClearing(true)
                      setShowClearConfirm(false)
                      try {
                        await api.post("/api/dev/clear")
                        queryClient.invalidateQueries()
                        toast.success("All data cleared")
                      } catch { toast.error("Clear failed") }
                      finally { setIsClearing(false) }
                    }}
                    disabled={isClearing}
                    className="bg-red-600 hover:bg-red-700 text-white"
                  >
                    {isClearing ? "Clearing..." : "Confirm Clear"}
                  </Button>
                  <Button variant="outline" size="sm" onClick={() => setShowClearConfirm(false)}>
                    Cancel
                  </Button>
                </div>
              ) : (
                <Button
                  variant="outline"
                  onClick={() => setShowClearConfirm(true)}
                  className="text-red-600 border-red-300 hover:bg-red-50"
                >
                  Clear All Data
                </Button>
              )}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
