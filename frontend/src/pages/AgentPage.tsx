/**
 * pages/AgentPage.tsx — Agent observability page (#37-43, #163, #171).
 *
 * Tabbed layout with 4 tabs:
 * 1. Metrics — KPIs and cost summary
 * 2. Activity — Unified chronological list of runs, jobs, and LLM decisions
 * 3. Context (#171) — Broker context entries injected into agent prompts
 * 4. Schedule (#41) — Cron jobs with pause/resume
 *
 * Context replaces the old Memory + Guidance tabs.
 * Chat removed — the global chat bubble handles it.
 *
 * C4: Every agent decision is traceable to its prompt, model, tokens, and cost.
 * C5: Cost tracking visible per run and per call.
 */

import { Bot } from "lucide-react"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { ActivityTab } from "@/components/agent/ActivityTab"
import { ContextTab } from "@/components/agent/ContextTab"
import { ScheduleTab } from "@/components/agent/ScheduleTab"
import { MetricsTab } from "@/components/agent/MetricsTab"

export function AgentPage() {
  return (
    <div className="p-4 lg:p-6 max-w-7xl space-y-4">
      <h2 className="text-xl font-semibold text-[#0E2841] flex items-center gap-2">
        <Bot className="h-5 w-5" />
        Agent
      </h2>

      <Tabs defaultValue="metrics">
        <TabsList className="grid w-full grid-cols-4">
          <TabsTrigger value="metrics" className="text-xs">Metrics</TabsTrigger>
          <TabsTrigger value="activity" className="text-xs">Activity</TabsTrigger>
          <TabsTrigger value="context" className="text-xs">Context</TabsTrigger>
          <TabsTrigger value="schedule" className="text-xs">Schedule</TabsTrigger>
        </TabsList>

        <TabsContent value="metrics" className="mt-4">
          <MetricsTab />
        </TabsContent>

        <TabsContent value="activity" className="mt-4">
          <ActivityTab />
        </TabsContent>

        {/* Context tab (#171) — replaces Memory + Guidance */}
        <TabsContent value="context" className="mt-4">
          <ContextTab />
        </TabsContent>

        <TabsContent value="schedule" className="mt-4">
          <ScheduleTab />
        </TabsContent>
      </Tabs>
    </div>
  )
}
