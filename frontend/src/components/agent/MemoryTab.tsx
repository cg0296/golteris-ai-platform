/**
 * components/agent/MemoryTab.tsx — Agent memory view (#40, #49).
 *
 * Shows what the agents have learned: style preferences from edited drafts,
 * customer patterns, lane knowledge, and pricing rules. The broker can
 * approve, reject, edit, or delete any learned memory.
 *
 * Data comes from /api/agent/memories (polls every 10s via React Query).
 */

import { useState } from "react"
import { Brain, BookOpen, TrendingUp, Users, DollarSign, Plus, Check, X, Trash2 } from "lucide-react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { toast } from "sonner"
import { useMemories, useCreateMemory, useUpdateMemory, useDeleteMemory, type MemoryItem } from "@/hooks/use-memories"
import { formatRelativeTime } from "@/lib/utils"

/** Category metadata — icons, labels, and colors for each memory type. */
const CATEGORIES = [
  { key: "style", label: "Style Patterns", icon: BookOpen, color: "text-purple-500 bg-purple-50" },
  { key: "preference", label: "Preferences", icon: Brain, color: "text-blue-500 bg-blue-50" },
  { key: "customer", label: "Customer Knowledge", icon: Users, color: "text-green-500 bg-green-50" },
  { key: "lane", label: "Lane Patterns", icon: TrendingUp, color: "text-amber-500 bg-amber-50" },
  { key: "pricing", label: "Pricing Rules", icon: DollarSign, color: "text-red-500 bg-red-50" },
]

const statusColors: Record<string, string> = {
  pending: "bg-amber-100 text-amber-800",
  approved: "bg-green-100 text-green-800",
  rejected: "bg-gray-100 text-gray-600",
}

export function MemoryTab() {
  const [selectedCategory, setSelectedCategory] = useState<string | undefined>()
  const [showAdd, setShowAdd] = useState(false)
  const [newContent, setNewContent] = useState("")
  const [newCategory, setNewCategory] = useState("preference")
  const memories = useMemories(selectedCategory)
  const createMemory = useCreateMemory()
  const updateMemory = useUpdateMemory()
  const deleteMemory = useDeleteMemory()

  const counts = memories.data?.counts ?? {}

  return (
    <div className="space-y-4">
      <p className="text-sm text-muted-foreground">
        What the agents have learned from processing quotes and broker feedback.
        Review pending items — approve to keep, reject to discard.
      </p>

      {/* Category cards with counts */}
      <div className="grid grid-cols-2 lg:grid-cols-5 gap-3">
        {CATEGORIES.map((cat) => (
          <button
            key={cat.key}
            onClick={() => setSelectedCategory(selectedCategory === cat.key ? undefined : cat.key)}
            className={`p-3 rounded-lg border text-left transition-colors ${
              selectedCategory === cat.key
                ? "border-[#0F9ED5] bg-[#E8F4FC]"
                : "bg-white hover:bg-muted/30"
            }`}
          >
            <div className="flex items-center gap-2 mb-1">
              <div className={`p-1 rounded ${cat.color.split(" ")[1]}`}>
                <cat.icon className={`h-3.5 w-3.5 ${cat.color.split(" ")[0]}`} />
              </div>
              <span className="text-xs font-medium">{cat.label}</span>
            </div>
            <p className="text-lg font-bold text-[#0E2841]">{counts[cat.key] ?? 0}</p>
          </button>
        ))}
      </div>

      {/* Add memory + filter controls */}
      <div className="flex items-center justify-between">
        <p className="text-xs text-muted-foreground">
          {memories.data?.total ?? 0} memories{selectedCategory ? ` in ${selectedCategory}` : ""}
        </p>
        <Button size="sm" variant="outline" onClick={() => setShowAdd(!showAdd)}>
          {showAdd ? "Cancel" : <><Plus className="h-3.5 w-3.5 mr-1" /> Add Memory</>}
        </Button>
      </div>

      {/* Add memory form */}
      {showAdd && (
        <div className="border rounded-lg p-3 space-y-2 bg-muted/20">
          <select
            value={newCategory}
            onChange={(e) => setNewCategory(e.target.value)}
            className="w-full px-2 py-1.5 text-sm border rounded-md bg-white"
          >
            {CATEGORIES.map((c) => (
              <option key={c.key} value={c.key}>{c.label}</option>
            ))}
          </select>
          <textarea
            value={newContent}
            onChange={(e) => setNewContent(e.target.value)}
            placeholder="What should the agent remember? (e.g., 'Always include transit time in quotes')"
            className="w-full px-2 py-1.5 text-sm border rounded-md resize-none"
            rows={2}
          />
          <Button
            size="sm"
            disabled={!newContent.trim() || createMemory.isPending}
            onClick={() => {
              createMemory.mutate(
                { category: newCategory, content: newContent.trim() },
                {
                  onSuccess: () => {
                    toast.success("Memory added")
                    setNewContent("")
                    setShowAdd(false)
                  },
                }
              )
            }}
            className="bg-[#0F9ED5] hover:bg-[#0B7FAD] text-white"
          >
            {createMemory.isPending ? "..." : "Save"}
          </Button>
        </div>
      )}

      {/* Memory list */}
      {memories.isLoading ? (
        <div className="space-y-2">
          {[...Array(4)].map((_, i) => (
            <div key={i} className="h-16 bg-white rounded-lg animate-pulse shadow-sm" />
          ))}
        </div>
      ) : (memories.data?.memories ?? []).length === 0 ? (
        <div className="text-center py-8">
          <Brain className="h-8 w-8 text-muted-foreground mx-auto mb-2" />
          <p className="text-sm text-muted-foreground">
            {selectedCategory
              ? `No ${selectedCategory} memories yet`
              : "No memories yet — will populate as quotes are processed and drafts are edited"}
          </p>
        </div>
      ) : (
        <div className="space-y-2">
          {memories.data?.memories.map((mem) => (
            <MemoryCard
              key={mem.id}
              memory={mem}
              onApprove={() => updateMemory.mutate({ id: mem.id, status: "approved" }, {
                onSuccess: () => toast.success("Memory approved"),
              })}
              onReject={() => updateMemory.mutate({ id: mem.id, status: "rejected" }, {
                onSuccess: () => toast.success("Memory rejected"),
              })}
              onDelete={() => deleteMemory.mutate(mem.id, {
                onSuccess: () => toast.success("Memory deleted"),
              })}
            />
          ))}
        </div>
      )}
    </div>
  )
}


function MemoryCard({
  memory,
  onApprove,
  onReject,
  onDelete,
}: {
  memory: MemoryItem
  onApprove: () => void
  onReject: () => void
  onDelete: () => void
}) {
  const cat = CATEGORIES.find((c) => c.key === memory.category)

  return (
    <div className="bg-white rounded-lg border p-3 shadow-sm">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 mb-1">
            {cat && (
              <Badge variant="secondary" className={`text-[10px] ${cat.color.replace("text-", "text-").replace("bg-", "bg-")}`}>
                {cat.label}
              </Badge>
            )}
            <Badge variant="secondary" className={`text-[10px] ${statusColors[memory.status] ?? ""}`}>
              {memory.status}
            </Badge>
            {memory.times_applied > 0 && (
              <span className="text-[10px] text-muted-foreground">
                Applied {memory.times_applied}x
              </span>
            )}
          </div>
          <p className="text-sm">{memory.content}</p>
          {memory.source && (
            <p className="text-xs text-muted-foreground mt-1">{memory.source}</p>
          )}
          {memory.created_at && (
            <p className="text-xs text-muted-foreground mt-0.5">
              {formatRelativeTime(memory.created_at)}
            </p>
          )}
        </div>

        <div className="flex items-center gap-1 shrink-0">
          {memory.status === "pending" && (
            <>
              <Button size="sm" variant="outline" className="h-7 px-2 text-green-600" onClick={onApprove} title="Approve">
                <Check className="h-3.5 w-3.5" />
              </Button>
              <Button size="sm" variant="outline" className="h-7 px-2 text-red-600" onClick={onReject} title="Reject">
                <X className="h-3.5 w-3.5" />
              </Button>
            </>
          )}
          <Button size="sm" variant="outline" className="h-7 px-2 text-gray-500" onClick={onDelete} title="Delete">
            <Trash2 className="h-3.5 w-3.5" />
          </Button>
        </div>
      </div>
    </div>
  )
}
