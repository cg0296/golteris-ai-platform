/**
 * components/agent/GuidanceTab.tsx — Guidance editor (#43).
 *
 * System prompt and active rules editor for configuring agent behavior.
 */

import { useState } from "react"
import { toast } from "sonner"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { Badge } from "@/components/ui/badge"
import { Save } from "lucide-react"

export function GuidanceTab() {
  const [systemPrompt, setSystemPrompt] = useState(
    "You are a freight logistics assistant for Beltmann Logistics. " +
    "Extract shipment details accurately. Always include confidence scores. " +
    "Use professional, clear language in all communications. " +
    "Flag anything uncertain for human review."
  )

  const rules = [
    { id: 1, text: "Always include confidence scores for extracted fields", active: true },
    { id: 2, text: "Flag quotes below $500 as potential errors", active: true },
    { id: 3, text: "Use formal tone for customer-facing emails", active: true },
    { id: 4, text: "Include weight and commodity in carrier RFQs", active: true },
    { id: 5, text: "Escalate if no carrier responds within 24 hours", active: false },
  ]

  return (
    <div className="space-y-6 max-w-2xl">
      {/* System Prompt */}
      <Card className="shadow-sm">
        <CardHeader className="pb-2">
          <CardTitle className="text-sm">System Prompt</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <p className="text-xs text-muted-foreground">
            The base instructions all agents follow. Changes take effect on the next agent run.
          </p>
          <Textarea
            value={systemPrompt}
            onChange={(e) => setSystemPrompt(e.target.value)}
            className="min-h-[120px] text-sm"
          />
          <Button
            size="sm"
            onClick={() => toast.success("System prompt saved")}
            className="bg-[#0F9ED5] hover:bg-[#0B7FAD] text-white"
          >
            <Save className="h-3.5 w-3.5 mr-1.5" />
            Save Prompt
          </Button>
        </CardContent>
      </Card>

      {/* Active Rules */}
      <Card className="shadow-sm">
        <CardHeader className="pb-2">
          <CardTitle className="text-sm">Active Rules</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          <p className="text-xs text-muted-foreground mb-3">
            Specific rules that override or supplement the system prompt.
          </p>
          {rules.map((rule) => (
            <div key={rule.id} className="flex items-center justify-between py-2 border-b last:border-0">
              <p className={`text-sm ${rule.active ? "" : "text-muted-foreground line-through"}`}>
                {rule.text}
              </p>
              <Badge variant="secondary" className={`text-[10px] shrink-0 ml-3 ${
                rule.active ? "bg-green-100 text-green-800" : "bg-gray-100 text-gray-600"
              }`}>
                {rule.active ? "Active" : "Inactive"}
              </Badge>
            </div>
          ))}
        </CardContent>
      </Card>
    </div>
  )
}
