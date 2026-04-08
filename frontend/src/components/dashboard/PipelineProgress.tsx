/**
 * components/dashboard/PipelineProgress.tsx — Visual pipeline progress (#139).
 *
 * Horizontal step indicator showing where an RFQ is in the workflow.
 * Displayed at the top of the RFQ detail modal so the broker immediately
 * sees the status without clicking through tabs.
 *
 * Steps: Received → Extracted → Clarification → Ready → Carriers → Bids → Quoted → Closed
 *
 * Cross-cutting constraints:
 *   C3 — All labels use plain English
 */

import { Check } from "lucide-react"

/** Pipeline stages in order. Each maps to one or more RFQ states. */
const PIPELINE_STAGES = [
  { key: "received", label: "Received", states: [] },
  { key: "extracted", label: "Extracted", states: [] },
  { key: "clarification", label: "Clarification", states: ["needs_clarification"] },
  { key: "ready", label: "Ready", states: ["ready_to_quote"] },
  { key: "carriers", label: "Carriers", states: ["waiting_on_carriers"] },
  { key: "bids", label: "Bids", states: ["quotes_received", "waiting_on_broker"] },
  { key: "quoted", label: "Quoted", states: ["quote_sent"] },
  { key: "closed", label: "Closed", states: ["won", "lost", "cancelled"] },
]

/** Map RFQ state to the pipeline stage index it represents. */
function getActiveStageIndex(state: string): number {
  for (let i = PIPELINE_STAGES.length - 1; i >= 0; i--) {
    if (PIPELINE_STAGES[i].states.includes(state)) return i
  }
  // Default: if state doesn't match, assume at least "received"
  return 0
}

interface PipelineProgressProps {
  state: string
  createdAt?: string | null
}

export function PipelineProgress({ state, createdAt }: PipelineProgressProps) {
  const activeIndex = getActiveStageIndex(state)
  // "received" and "extracted" are always complete if the RFQ exists
  const effectiveIndex = Math.max(activeIndex, 1) // At least extracted if RFQ exists

  return (
    <div className="flex items-center gap-1 py-3 overflow-x-auto">
      {PIPELINE_STAGES.map((stage, i) => {
        const isComplete = i < effectiveIndex
        const isActive = i === effectiveIndex
        const isFuture = i > effectiveIndex

        return (
          <div key={stage.key} className="flex items-center flex-1 min-w-0">
            {/* Step indicator */}
            <div className="flex flex-col items-center gap-1 flex-shrink-0">
              <div
                className={`flex h-7 w-7 items-center justify-center rounded-full text-xs font-bold transition-all ${
                  isComplete
                    ? "bg-green-500 text-white"
                    : isActive
                    ? "bg-[#0F9ED5] text-white ring-2 ring-[#0F9ED5]/30"
                    : "bg-gray-100 text-gray-400"
                }`}
              >
                {isComplete ? <Check className="h-3.5 w-3.5" /> : i + 1}
              </div>
              <span
                className={`text-[10px] text-center leading-tight ${
                  isComplete
                    ? "text-green-700 font-medium"
                    : isActive
                    ? "text-[#0F9ED5] font-semibold"
                    : "text-gray-400"
                }`}
              >
                {stage.label}
              </span>
            </div>

            {/* Connector line */}
            {i < PIPELINE_STAGES.length - 1 && (
              <div
                className={`flex-1 h-0.5 mx-1 rounded-full min-w-[8px] ${
                  i < effectiveIndex ? "bg-green-400" : "bg-gray-200"
                }`}
              />
            )}
          </div>
        )
      })}
    </div>
  )
}
