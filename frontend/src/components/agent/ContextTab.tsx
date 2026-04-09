/**
 * components/agent/ContextTab.tsx — Broker context management (#171).
 *
 * Single tab replacing the old Guidance + Memory tabs. Manages everything
 * agents should know: style preferences, broker rules, customer knowledge,
 * lane patterns, and pricing rules.
 *
 * Each entry has an active/inactive toggle. Active entries (status=approved)
 * are injected into every agent LLM prompt via backend/services/context.py.
 * Inactive entries (status=rejected) are stored but not used.
 *
 * The broker can add entries in natural language, toggle them on/off,
 * edit content, and delete entries.
 *
 * Data: /api/agent/memories (existing CRUD, reused)
 */

import { useState } from "react"
import {
  Brain, BookOpen, TrendingUp, Users, DollarSign, Plus, Trash2,
  Pencil, Check, X,
} from "lucide-react"
import { Card, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { toast } from "sonner"
import {
  useMemories, useCreateMemory, useUpdateMemory, useDeleteMemory,
  type MemoryItem,
} from "@/hooks/use-memories"
import { formatRelativeTime, cn } from "@/lib/utils"

/** Category metadata — icons, labels, colors, and descriptions. */
const CATEGORIES = [
  { key: "style", label: "Style", icon: BookOpen, color: "text-purple-500", bg: "bg-purple-50", desc: "How agents write — tone, sign-offs, formatting" },
  { key: "preference", label: "Preferences", icon: Brain, color: "text-blue-500", bg: "bg-blue-50", desc: "Broker rules and preferences" },
  { key: "customer", label: "Customers", icon: Users, color: "text-green-500", bg: "bg-green-50", desc: "Customer-specific knowledge" },
  { key: "lane", label: "Lanes", icon: TrendingUp, color: "text-amber-500", bg: "bg-amber-50", desc: "Route and lane patterns" },
  { key: "pricing", label: "Pricing", icon: DollarSign, color: "text-red-500", bg: "bg-red-50", desc: "Markup and pricing rules" },
]

export function ContextTab() {
  const [selectedCategory, setSelectedCategory] = useState<string | undefined>()
  const [showAdd, setShowAdd] = useState(false)
  const [newContent, setNewContent] = useState("")
  const [newCategory, setNewCategory] = useState("preference")
  const memories = useMemories(selectedCategory)
  const createMemory = useCreateMemory()

  const counts = memories.data?.counts ?? {}
  const activeCount = (memories.data?.memories ?? []).filter((m) => m.status === "approved").length
  const totalCount = memories.data?.total ?? 0

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-sm text-muted-foreground">
            Active context entries are injected into every agent prompt.
            Toggle entries on/off to control what agents know.
          </p>
          <p className="text-xs text-muted-foreground mt-1">
            {activeCount} active of {totalCount} total entries
          </p>
        </div>
        <Button size="sm" onClick={() => setShowAdd(!showAdd)} className="bg-[#0F9ED5] hover:bg-[#0B7FAD] text-white">
          {showAdd ? "Cancel" : <><Plus className="h-3.5 w-3.5 mr-1" /> Add Rule</>}
        </Button>
      </div>

      {/* Add entry form */}
      {showAdd && (
        <div className="border rounded-lg p-4 space-y-3 bg-muted/20">
          <p className="text-xs font-semibold text-muted-foreground uppercase">New Context Entry</p>
          <div className="flex gap-2">
            {CATEGORIES.map((c) => (
              <button
                key={c.key}
                onClick={() => setNewCategory(c.key)}
                className={cn(
                  "px-2.5 py-1 rounded-full text-[11px] font-medium border transition-colors",
                  newCategory === c.key
                    ? "bg-[#0E2841] text-white border-[#0E2841]"
                    : "bg-white text-muted-foreground border-border hover:bg-muted/50"
                )}
              >
                {c.label}
              </button>
            ))}
          </div>
          <textarea
            value={newContent}
            onChange={(e) => setNewContent(e.target.value)}
            placeholder="Write in natural language, e.g.: 'Always include transit time estimates in customer quotes' or 'Tom at Reynolds Logistics needs tarping on every load'"
            className="w-full px-3 py-2 text-sm border rounded-md resize-none focus:outline-none focus:ring-2 focus:ring-[#0F9ED5]/30"
            rows={3}
          />
          <Button
            size="sm"
            disabled={!newContent.trim() || createMemory.isPending}
            onClick={() => {
              createMemory.mutate(
                { category: newCategory, content: newContent.trim() },
                {
                  onSuccess: () => {
                    toast.success("Context entry added — active immediately")
                    setNewContent("")
                    setShowAdd(false)
                  },
                }
              )
            }}
            className="bg-[#0F9ED5] hover:bg-[#0B7FAD] text-white"
          >
            {createMemory.isPending ? "Saving..." : "Save & Activate"}
          </Button>
        </div>
      )}

      {/* Category filter pills */}
      <div className="flex flex-wrap gap-2">
        <button
          onClick={() => setSelectedCategory(undefined)}
          className={cn(
            "px-3 py-1.5 rounded-full text-xs font-medium border transition-colors",
            !selectedCategory
              ? "bg-[#0E2841] text-white border-[#0E2841]"
              : "bg-white text-muted-foreground border-border hover:bg-muted/50"
          )}
        >
          All ({totalCount})
        </button>
        {CATEGORIES.map((cat) => (
          <button
            key={cat.key}
            onClick={() => setSelectedCategory(selectedCategory === cat.key ? undefined : cat.key)}
            className={cn(
              "inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium border transition-colors",
              selectedCategory === cat.key
                ? "bg-[#0E2841] text-white border-[#0E2841]"
                : "bg-white text-muted-foreground border-border hover:bg-muted/50"
            )}
          >
            <cat.icon className="h-3 w-3" />
            {cat.label}
            <span className={cn("text-[10px] font-mono", selectedCategory === cat.key ? "text-white/70" : "text-muted-foreground/60")}>
              {counts[cat.key] ?? 0}
            </span>
          </button>
        ))}
      </div>

      {/* Entry list */}
      {memories.isLoading ? (
        <div className="space-y-2">
          {[...Array(4)].map((_, i) => (
            <div key={i} className="h-16 bg-white rounded-lg animate-pulse shadow-sm" />
          ))}
        </div>
      ) : (memories.data?.memories ?? []).length === 0 ? (
        <Card className="shadow-sm">
          <CardContent className="py-8 text-center">
            <Brain className="h-8 w-8 text-muted-foreground mx-auto mb-2" />
            <p className="text-sm text-muted-foreground">
              {selectedCategory
                ? `No ${selectedCategory} entries yet`
                : "No context entries yet — add rules, preferences, or knowledge above"}
            </p>
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-2">
          {memories.data?.memories.map((mem) => (
            <ContextEntry key={mem.id} memory={mem} />
          ))}
        </div>
      )}
    </div>
  )
}


/** Single context entry with toggle, edit, and delete */
function ContextEntry({ memory }: { memory: MemoryItem }) {
  const [editing, setEditing] = useState(false)
  const [editContent, setEditContent] = useState(memory.content)
  const updateMemory = useUpdateMemory()
  const deleteMemory = useDeleteMemory()

  const isActive = memory.status === "approved"
  const cat = CATEGORIES.find((c) => c.key === memory.category)

  const handleToggle = () => {
    const newStatus = isActive ? "rejected" : "approved"
    updateMemory.mutate(
      { id: memory.id, status: newStatus },
      { onSuccess: () => toast.success(isActive ? "Entry deactivated" : "Entry activated") }
    )
  }

  const handleSaveEdit = () => {
    if (!editContent.trim()) return
    updateMemory.mutate(
      { id: memory.id, content: editContent.trim() },
      {
        onSuccess: () => {
          toast.success("Entry updated")
          setEditing(false)
        },
      }
    )
  }

  return (
    <div className={cn(
      "bg-white rounded-lg border p-3 shadow-sm transition-opacity",
      !isActive && "opacity-50"
    )}>
      <div className="flex items-start gap-3">
        {/* Active/inactive toggle */}
        <button
          onClick={handleToggle}
          className={cn(
            "mt-0.5 shrink-0 w-9 h-5 rounded-full transition-colors relative",
            isActive ? "bg-green-500" : "bg-gray-300"
          )}
          title={isActive ? "Active — click to deactivate" : "Inactive — click to activate"}
        >
          <span className={cn(
            "absolute top-0.5 h-4 w-4 rounded-full bg-white shadow transition-transform",
            isActive ? "left-[18px]" : "left-0.5"
          )} />
        </button>

        <div className="flex-1 min-w-0">
          {/* Category badge + usage count */}
          <div className="flex items-center gap-2 mb-1">
            {cat && (
              <Badge variant="secondary" className={`text-[10px] ${cat.bg} ${cat.color}`}>
                {cat.label}
              </Badge>
            )}
            {memory.times_applied > 0 && (
              <span className="text-[10px] text-muted-foreground">
                Used {memory.times_applied}x
              </span>
            )}
            {memory.source && memory.source !== "Manual entry by broker" && (
              <span className="text-[10px] text-muted-foreground">
                From: {memory.source}
              </span>
            )}
          </div>

          {/* Content — editable or display */}
          {editing ? (
            <div className="space-y-2">
              <textarea
                value={editContent}
                onChange={(e) => setEditContent(e.target.value)}
                className="w-full px-2 py-1.5 text-sm border rounded-md resize-none focus:outline-none focus:ring-1 focus:ring-[#0F9ED5]"
                rows={2}
                autoFocus
              />
              <div className="flex gap-1">
                <Button size="sm" onClick={handleSaveEdit} disabled={updateMemory.isPending} className="h-7 px-2 bg-[#0F9ED5] hover:bg-[#0B7FAD] text-white">
                  <Check className="h-3 w-3 mr-1" /> Save
                </Button>
                <Button size="sm" variant="ghost" onClick={() => { setEditing(false); setEditContent(memory.content) }} className="h-7 px-2">
                  <X className="h-3 w-3" />
                </Button>
              </div>
            </div>
          ) : (
            <p className="text-sm">{memory.content}</p>
          )}

          <p className="text-[10px] text-muted-foreground mt-1">
            {memory.created_at ? formatRelativeTime(memory.created_at) : ""}
          </p>
        </div>

        {/* Edit + Delete buttons */}
        {!editing && (
          <div className="flex items-center gap-1 shrink-0">
            <Button size="sm" variant="ghost" className="h-7 w-7 p-0 text-muted-foreground hover:text-[#0F9ED5]" onClick={() => setEditing(true)} title="Edit">
              <Pencil className="h-3 w-3" />
            </Button>
            <Button
              size="sm"
              variant="ghost"
              className="h-7 w-7 p-0 text-muted-foreground hover:text-red-500"
              onClick={() => deleteMemory.mutate(memory.id, { onSuccess: () => toast.success("Entry deleted") })}
              title="Delete"
            >
              <Trash2 className="h-3 w-3" />
            </Button>
          </div>
        )}
      </div>
    </div>
  )
}
