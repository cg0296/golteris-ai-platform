/**
 * pages/AgentPage.tsx — Agent observability page (Phase 10, #37-43).
 *
 * Tabbed layout with 7 sub-views:
 * 1. Timeline (#38) — Agent runs with duration, cost, status
 * 2. Decisions (#37) — Per-call audit with prompt/response drill-down
 * 3. Tasks (#39) — Running, queued, scheduled, done
 * 4. Memory (#40) — Facts, preferences, rules, patterns
 * 5. Schedule (#41) — Cron jobs with pause/resume
 * 6. Chat (#42) — Ask Golteris chat interface
 * 7. Guidance (#43) — System prompt and active rules editor
 *
 * C4: Every agent decision is traceable to its prompt, model, tokens, and cost.
 * C5: Cost tracking visible per run and per call.
 */

import { useState } from "react"
import { Bot } from "lucide-react"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { TimelineTab } from "@/components/agent/TimelineTab"
import { DecisionsTab } from "@/components/agent/DecisionsTab"
import { TasksTab } from "@/components/agent/TasksTab"
import { MemoryTab } from "@/components/agent/MemoryTab"
import { ScheduleTab } from "@/components/agent/ScheduleTab"
import { ChatTab } from "@/components/agent/ChatTab"
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
        <TabsList className="grid w-full grid-cols-4 lg:grid-cols-8">
          <TabsTrigger value="metrics" className="text-xs">Metrics</TabsTrigger>
          <TabsTrigger value="timeline" className="text-xs">Timeline</TabsTrigger>
          <TabsTrigger value="decisions" className="text-xs">Decisions</TabsTrigger>
          <TabsTrigger value="tasks" className="text-xs">Tasks</TabsTrigger>
          <TabsTrigger value="memory" className="text-xs">Memory</TabsTrigger>
          <TabsTrigger value="schedule" className="text-xs hidden lg:block">Schedule</TabsTrigger>
          <TabsTrigger value="chat" className="text-xs hidden lg:block">Chat</TabsTrigger>
          <TabsTrigger value="guidance" className="text-xs hidden lg:block">Guidance</TabsTrigger>
        </TabsList>

        <TabsContent value="metrics" className="mt-4">
          <MetricsTab />
        </TabsContent>
        <TabsContent value="timeline" className="mt-4">
          <TimelineTab />
        </TabsContent>
        <TabsContent value="decisions" className="mt-4">
          <DecisionsTab />
        </TabsContent>
        <TabsContent value="tasks" className="mt-4">
          <TasksTab />
        </TabsContent>
        <TabsContent value="memory" className="mt-4">
          <MemoryTab />
        </TabsContent>
        <TabsContent value="schedule" className="mt-4">
          <ScheduleTab />
        </TabsContent>
        <TabsContent value="chat" className="mt-4">
          <ChatTab />
        </TabsContent>
        <TabsContent value="guidance" className="mt-4">
          <GuidanceTab />
        </TabsContent>
      </Tabs>
    </div>
  )
}
