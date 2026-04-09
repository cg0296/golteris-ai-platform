/**
 * components/dashboard/PipelineProgress.tsx — Visual pipeline progress (#139, #147).
 *
 * Compact horizontal step indicator showing where an RFQ is in the workflow.
 * Text-only labels connected by lines — no circles, fits any modal width.
 *
 * Steps: Inquiry → Received → Extracted → Clarification → Ready → Carriers → Bids → Quoted → Closed
 *
 * Cross-cutting constraints:
 *   C3 — All labels use plain English
 */

/** Pipeline stages in order. Each maps to one or more RFQ states. */
const PIPELINE_STAGES = [
  { key: "inquiry", label: "Inquiry", states: ["inquiry"] },
  { key: "received", label: "Received", states: [] as string[] },
  { key: "extracted", label: "Extracted", states: [] as string[] },
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
  return 0
}

interface PipelineProgressProps {
  state: string
  createdAt?: string | null
}

export function PipelineProgress({ state }: PipelineProgressProps) {
  const activeIndex = getActiveStageIndex(state)
  // "received" and "extracted" are always complete if the RFQ exists
  const effectiveIndex = Math.max(activeIndex, 1)

  return (
    <div className="flex items-center w-full py-2">
      {PIPELINE_STAGES.map((stage, i) => {
        const isComplete = i < effectiveIndex
        const isActive = i === effectiveIndex
        const isFuture = i > effectiveIndex

        return (
          <div key={stage.key} className="flex items-center" style={{ flex: 1 }}>
            {/* Label */}
            <span
              className={`text-[11px] whitespace-nowrap font-medium ${
                isComplete
                  ? "text-green-600"
                  : isActive
                  ? "text-[#0F9ED5] font-bold"
                  : "text-gray-300"
              }`}
            >
              {stage.label}
            </span>

            {/* Connector line */}
            {i < PIPELINE_STAGES.length - 1 && (
              <div
                className={`flex-1 h-0.5 mx-1.5 rounded-full ${
                  i < effectiveIndex ? "bg-green-400" : "bg-gray-200"
                }`}
                style={{ minWidth: 4 }}
              />
            )}
          </div>
        )
      })}
    </div>
  )
}
