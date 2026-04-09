/**
 * components/dashboard/CarrierSelectModal.tsx — Carrier selection for RFQ distribution (#32, #168).
 *
 * Shows ALL active carriers with search, split into:
 * - Recommended: equipment type matches the RFQ
 * - All Carriers: the rest
 *
 * Broker can search by name/email, select across both sections, add new carriers inline.
 *
 * C2 — Distribution creates a pending approval (or auto-sends per workflow toggle).
 */

import { useState, useEffect, useMemo } from "react"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { toast } from "sonner"
import { Plus, Search } from "lucide-react"
import { useAllCarriers, useMatchingCarriers, useDistributeRfq } from "@/hooks/use-carriers"
import { api } from "@/lib/api"
import { useQueryClient } from "@tanstack/react-query"
import type { CarrierItem } from "@/hooks/use-carriers"

interface CarrierSelectModalProps {
  rfqId: number | null
  onClose: () => void
}

export function CarrierSelectModal({ rfqId, onClose }: CarrierSelectModalProps) {
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set())
  const [attachQuoteSheet, setAttachQuoteSheet] = useState(true)
  const [search, setSearch] = useState("")
  const [showAddForm, setShowAddForm] = useState(false)
  const [newName, setNewName] = useState("")
  const [newEmail, setNewEmail] = useState("")
  const [newEquipment, setNewEquipment] = useState("")
  const [adding, setAdding] = useState(false)

  // Fetch ALL carriers + matching carriers for recommendations
  const allCarriers = useAllCarriers()
  const matchingCarriers = useMatchingCarriers(rfqId)
  const distribute = useDistributeRfq()
  const queryClient = useQueryClient()

  const isOpen = rfqId !== null

  // Build recommended set (IDs of equipment-matching carriers)
  const recommendedIds = useMemo(() => {
    return new Set((matchingCarriers.data?.carriers ?? []).map((c) => c.id))
  }, [matchingCarriers.data])

  // Filter carriers by search
  const filteredCarriers = useMemo(() => {
    const all = allCarriers.data?.carriers ?? []
    if (!search.trim()) return all
    const q = search.toLowerCase()
    return all.filter(
      (c) => c.name.toLowerCase().includes(q) || c.email.toLowerCase().includes(q)
    )
  }, [allCarriers.data, search])

  // Split into recommended and others
  const recommended = filteredCarriers.filter((c) => recommendedIds.has(c.id))
  const others = filteredCarriers.filter((c) => !recommendedIds.has(c.id))

  // Reset selection when modal opens with a new RFQ
  useEffect(() => {
    if (rfqId) {
      // Pre-select preferred carriers from the recommended set
      const preferred = (matchingCarriers.data?.carriers ?? [])
        .filter((c) => c.preferred)
        .map((c) => c.id)
      setSelectedIds(new Set(preferred))
      setSearch("")
    }
  }, [rfqId, matchingCarriers.data])

  const toggleCarrier = (id: number) => {
    setSelectedIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const selectAll = () => {
    setSelectedIds(new Set(filteredCarriers.map((c) => c.id)))
  }

  const selectNone = () => setSelectedIds(new Set())

  const handleAddCarrier = async () => {
    if (!newName.trim() || !newEmail.trim()) return
    setAdding(true)
    try {
      const result = await api.post<{ id: number }>("/api/carriers", {
        name: newName.trim(),
        email: newEmail.trim(),
        equipment_types: newEquipment.trim()
          ? newEquipment.split(",").map((s) => s.trim())
          : [],
      })
      await queryClient.invalidateQueries({ queryKey: ["carriers"] })
      if (result?.id) {
        setSelectedIds((prev) => new Set([...prev, result.id]))
      }
      setNewName("")
      setNewEmail("")
      setNewEquipment("")
      setShowAddForm(false)
      toast.success(`Added ${newName.trim()}`)
    } catch (err) {
      toast.error("Failed to add carrier", {
        description: err instanceof Error ? err.message : "Unknown error",
      })
    } finally {
      setAdding(false)
    }
  }

  const handleDistribute = () => {
    if (!rfqId || selectedIds.size === 0) return
    distribute.mutate(
      { rfqId, carrierIds: Array.from(selectedIds), attachQuoteSheet },
      {
        onSuccess: () => {
          toast.success("Carrier RFQs prepared", {
            description: `${selectedIds.size} carrier RFQ(s) sent or awaiting approval`,
          })
          onClose()
        },
        onError: (err) => {
          toast.error("Distribution failed", {
            description: err instanceof Error ? err.message : "Unknown error",
          })
        },
      }
    )
  }

  const totalCarriers = allCarriers.data?.carriers.length ?? 0

  return (
    <Dialog open={isOpen} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-w-lg max-h-[80vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Send to Carriers</DialogTitle>
        </DialogHeader>

        {/* Search box */}
        <div className="relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
          <input
            type="text"
            placeholder="Search carriers by name or email..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full pl-9 pr-3 py-2 text-sm border rounded-md bg-white focus:outline-none focus:ring-2 focus:ring-[#0F9ED5]/30 focus:border-[#0F9ED5]"
          />
        </div>

        {allCarriers.isLoading ? (
          <div className="space-y-3 py-4">
            {[...Array(4)].map((_, i) => (
              <div key={i} className="h-14 bg-muted/50 rounded animate-pulse" />
            ))}
          </div>
        ) : totalCarriers === 0 ? (
          <p className="text-sm text-muted-foreground py-6 text-center">
            No carriers yet — add one below
          </p>
        ) : (
          <div className="space-y-3">
            {/* Add Carrier inline form */}
            {showAddForm ? (
              <div className="border rounded-lg p-3 space-y-2 bg-muted/20">
                <p className="text-xs font-semibold text-muted-foreground uppercase">New Carrier</p>
                <input type="text" placeholder="Carrier name *" value={newName} onChange={(e) => setNewName(e.target.value)} className="w-full text-sm border rounded px-2.5 py-1.5 focus:outline-none focus:ring-1 focus:ring-[#0F9ED5]" autoFocus />
                <input type="email" placeholder="Email address *" value={newEmail} onChange={(e) => setNewEmail(e.target.value)} className="w-full text-sm border rounded px-2.5 py-1.5 focus:outline-none focus:ring-1 focus:ring-[#0F9ED5]" />
                <input type="text" placeholder="Equipment types (comma-separated)" value={newEquipment} onChange={(e) => setNewEquipment(e.target.value)} className="w-full text-sm border rounded px-2.5 py-1.5 focus:outline-none focus:ring-1 focus:ring-[#0F9ED5]" />
                <div className="flex gap-2">
                  <Button size="sm" onClick={handleAddCarrier} disabled={!newName.trim() || !newEmail.trim() || adding} className="bg-[#0F9ED5] hover:bg-[#0B7FAD] text-white">
                    {adding ? "Adding..." : "Add Carrier"}
                  </Button>
                  <Button size="sm" variant="ghost" onClick={() => setShowAddForm(false)}>Cancel</Button>
                </div>
              </div>
            ) : (
              <button onClick={() => setShowAddForm(true)} className="flex items-center gap-1.5 text-xs text-[#0F9ED5] hover:underline">
                <Plus className="h-3.5 w-3.5" />
                Add a carrier
              </button>
            )}

            {/* Select all / none */}
            <div className="flex gap-2 text-xs">
              <button onClick={selectAll} className="text-[#0F9ED5] hover:underline">Select all</button>
              <span className="text-muted-foreground">·</span>
              <button onClick={selectNone} className="text-muted-foreground hover:underline">Select none</button>
              <span className="ml-auto text-muted-foreground">
                {selectedIds.size} of {totalCarriers} selected
              </span>
            </div>

            {/* Recommended carriers */}
            {recommended.length > 0 && (
              <>
                <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider pt-1">
                  Recommended — Equipment Match
                </p>
                {recommended.map((carrier) => (
                  <CarrierRow
                    key={carrier.id}
                    carrier={carrier}
                    selected={selectedIds.has(carrier.id)}
                    onToggle={() => toggleCarrier(carrier.id)}
                    recommended
                  />
                ))}
              </>
            )}

            {/* All other carriers */}
            {others.length > 0 && (
              <>
                <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider pt-1">
                  {recommended.length > 0 ? "Other Carriers" : "All Carriers"}
                </p>
                {others.map((carrier) => (
                  <CarrierRow
                    key={carrier.id}
                    carrier={carrier}
                    selected={selectedIds.has(carrier.id)}
                    onToggle={() => toggleCarrier(carrier.id)}
                  />
                ))}
              </>
            )}

            {filteredCarriers.length === 0 && search && (
              <p className="text-sm text-muted-foreground text-center py-4">
                No carriers matching "{search}"
              </p>
            )}

            {/* Attach quote sheet toggle */}
            <label className="flex items-center gap-2 pt-1 cursor-pointer">
              <input
                type="checkbox"
                checked={attachQuoteSheet}
                onChange={(e) => setAttachQuoteSheet(e.target.checked)}
                className="h-4 w-4 rounded border-gray-300 text-[#0F9ED5] focus:ring-[#0F9ED5]"
              />
              <span className="text-sm text-muted-foreground">Attach Excel quote sheet to emails</span>
            </label>

            {/* Action */}
            <div className="pt-2">
              <Button
                onClick={handleDistribute}
                disabled={selectedIds.size === 0 || distribute.isPending}
                className="w-full bg-[#0F9ED5] hover:bg-[#0B7FAD] text-white"
              >
                {distribute.isPending
                  ? "Preparing..."
                  : `Send RFQs to ${selectedIds.size} Carrier${selectedIds.size !== 1 ? "s" : ""}`}
              </Button>
              <p className="text-xs text-muted-foreground text-center mt-2">
                You'll review the draft before it's sent
              </p>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}

/** Single carrier row with checkbox, badges, and equipment tags */
function CarrierRow({
  carrier,
  selected,
  onToggle,
  recommended = false,
}: {
  carrier: CarrierItem
  selected: boolean
  onToggle: () => void
  recommended?: boolean
}) {
  return (
    <label
      className={`flex items-center gap-3 p-3 rounded-lg border cursor-pointer transition-colors ${
        selected ? "border-[#0F9ED5] bg-[#E8F4FC]" : "border-border hover:bg-muted/30"
      }`}
    >
      <input
        type="checkbox"
        checked={selected}
        onChange={onToggle}
        className="h-4 w-4 rounded border-gray-300 text-[#0F9ED5] focus:ring-[#0F9ED5]"
      />
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium">{carrier.name}</span>
          {carrier.preferred && (
            <Badge variant="secondary" className="text-[10px] bg-amber-100 text-amber-800">
              Preferred
            </Badge>
          )}
          {recommended && (
            <Badge variant="secondary" className="text-[10px] bg-green-100 text-green-800">
              Match
            </Badge>
          )}
        </div>
        <p className="text-xs text-muted-foreground">{carrier.email}</p>
        <div className="flex flex-wrap gap-1 mt-1">
          {carrier.equipment_types.map((e) => (
            <Badge key={e} variant="outline" className="text-[10px]">
              {e}
            </Badge>
          ))}
        </div>
      </div>
    </label>
  )
}
