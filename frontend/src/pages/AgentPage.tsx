/**
 * pages/AgentPage.tsx — Agent observability page (#37-43, #163).
 *
 * Tabbed layout with 5 tabs:
 * 1. Metrics — KPIs and cost summary
 * 2. Activity — Timeline + Decisions + Tasks collapsed into one view
 * 3. Memory (#40) — Facts, preferences, rules, patterns
 * 4. Schedule (#41) — Cron jobs with pause/resume
 * 5. Guidance (#43) — System prompt and active rules editor
 *
 * Chat removed — the global chat bubble handles it.
 *
 * C4: Every agent decision is traceable to its prompt, model, tokens, and cost.
 * C5: Cost tracking visible per run and per call.
 */

import { Bot } from "lucide-react"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { ActivityTab } from "@/components/agent/ActivityTab"
import { MemoryTab } from "@/components/agent/MemoryTab"
import { ScheduleTab } from "@/components/agent/ScheduleTab"
import { GuidanceTab } from "@/components/agent/GuidanceTab"
import { MetricsTab } from "@/components/agent/MetricsTab"

export function AgentPage() {
  return (
    <div className="p-4 lg:p-6 max-w-7xl space-y-4">
      <h2 className="text-xl font-semibold text-[#0E2841] flex items-center gap-2">
        <Bot className="h-5 w-5" />
        Agent
      </h2>

      <Tabs defaultValue="metrics">
        <TabsList className="grid w-full grid-cols-5">
          <TabsTrigger value="metrics" className="text-xs">Metrics</TabsTrigger>
          <TabsTrigger value="activity" className="text-xs">Activity</TabsTrigger>
          <TabsTrigger value="memory" className="text-xs">Memory</TabsTrigger>
          <TabsTrigger value="schedule" className="text-xs">Schedule</TabsTrigger>
          <TabsTrigger value="guidance" className="text-xs">Guidance</TabsTrigger>
        </TabsList>

        <TabsContent value="metrics" className="mt-4">
          <MetricsTab />
        </TabsContent>

        {/* Activity tab — unified chronological list of runs + jobs (#165) */}
        <TabsContent value="activity" className="mt-4">
          <ActivityTab />
        </TabsContent>

        <TabsContent value="memory" className="mt-4">
          <MemoryTab />
        </TabsContent>
        <TabsContent value="schedule" className="mt-4">
          <ScheduleTab />
        </TabsContent>
        <TabsContent value="guidance" className="mt-4">
          <GuidanceTab />
        </TabsContent>
      </Tabs>
    </div>
  )
}
