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

import { useState } from "react"
import { Bot, ChevronDown, ChevronRight } from "lucide-react"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { TimelineTab } from "@/components/agent/TimelineTab"
import { DecisionsTab } from "@/components/agent/DecisionsTab"
import { TasksTab } from "@/components/agent/TasksTab"
import { MemoryTab } from "@/components/agent/MemoryTab"
import { ScheduleTab } from "@/components/agent/ScheduleTab"
import { GuidanceTab } from "@/components/agent/GuidanceTab"
import { MetricsTab } from "@/components/agent/MetricsTab"

/** Collapsible section used inside the Activity tab */
function CollapsibleSection({ title, defaultOpen = false, children }: { title: string; defaultOpen?: boolean; children: React.ReactNode }) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <div className="border rounded-lg overflow-hidden">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center gap-2 px-4 py-3 bg-muted/30 hover:bg-muted/50 transition-colors text-left"
      >
        {open ? <ChevronDown className="h-4 w-4 text-muted-foreground" /> : <ChevronRight className="h-4 w-4 text-muted-foreground" />}
        <span className="text-sm font-semibold text-[#0E2841]">{title}</span>
      </button>
      {open && <div className="p-4">{children}</div>}
    </div>
  )
}

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

        {/* Activity tab — Timeline + Decisions + Tasks in collapsible sections (#163) */}
        <TabsContent value="activity" className="mt-4">
          <div className="space-y-3">
            <CollapsibleSection title="Timeline — Agent Runs" defaultOpen={true}>
              <TimelineTab />
            </CollapsibleSection>
            <CollapsibleSection title="Decisions — LLM Call Audit">
              <DecisionsTab />
            </CollapsibleSection>
            <CollapsibleSection title="Tasks — Job Queue">
              <TasksTab />
            </CollapsibleSection>
          </div>
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
