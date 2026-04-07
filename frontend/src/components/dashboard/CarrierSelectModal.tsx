/**
 * components/dashboard/CarrierSelectModal.tsx — Carrier selection for RFQ distribution (#32).
 *
 * Opens from the RFQ detail drawer when the broker clicks "Send to Carriers".
 * Shows matching carriers with checkboxes, preferred badges, and equipment tags.
 * Selecting carriers and clicking "Send RFQs" creates a batch approval (C2 gate).
 *
 * C2 — Distribution creates a pending approval; nothing sends until approved.
 */

import { useState, useEffect } from "react"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { toast } from "sonner"
import { useMatchingCarriers, useDistributeRfq } from "@/hooks/use-carriers"
import type { CarrierItem } from "@/hooks/use-carriers"

interface CarrierSelectModalProps {
  rfqId: number | null
  onClose: () => void
}

export function CarrierSelectModal({ rfqId, onClose }: CarrierSelectModalProps) {
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set())
  const carriers = useMatchingCarriers(rfqId)
  const distribute = useDistributeRfq()

  const isOpen = rfqId !== null

  // Reset selection when modal opens with a new RFQ
  useEffect(() => {
    if (rfqId) {
      // Pre-select preferred carriers
      const preferred = (carriers.data?.carriers ?? [])
        .filter((c) => c.preferred)
        .map((c) => c.id)
      setSelectedIds(new Set(preferred))
    }
  }, [rfqId, carriers.data])

  const toggleCarrier = (id: number) => {
    setSelectedIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const selectAll = () => {
    const allIds = (carriers.data?.carriers ?? []).map((c) => c.id)
    setSelectedIds(new Set(allIds))
  }

  const selectNone = () => setSelectedIds(new Set())

  const handleDistribute = () => {
    if (!rfqId || selectedIds.size === 0) return
    distribute.mutate(
      { rfqId, carrierIds: Array.from(selectedIds) },
      {
        onSuccess: () => {
          toast.success("Carrier RFQs prepared", {
            description: `${selectedIds.size} carrier RFQ(s) awaiting your approval`,
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

  return (
    <Dialog open={isOpen} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-w-lg max-h-[80vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Send to Carriers</DialogTitle>
        </DialogHeader>

        {carriers.isLoading ? (
          <div className="space-y-3 py-4">
            {[...Array(4)].map((_, i) => (
              <div key={i} className="h-14 bg-muted/50 rounded animate-pulse" />
            ))}
          </div>
        ) : (carriers.data?.carriers.length ?? 0) === 0 ? (
          <p className="text-sm text-muted-foreground py-6 text-center">
            No carriers match this RFQ's equipment type
          </p>
        ) : (
          <div className="space-y-3">
            {/* Select all / none */}
            <div className="flex gap-2 text-xs">
              <button onClick={selectAll} className="text-[#0F9ED5] hover:underline">
                Select all
              </button>
              <span className="text-muted-foreground">·</span>
              <button onClick={selectNone} className="text-muted-foreground hover:underline">
                Select none
              </button>
              <span className="ml-auto text-muted-foreground">
                {selectedIds.size} of {carriers.data?.carriers.length} selected
              </span>
            </div>

            {/* Carrier list */}
            {carriers.data?.carriers.map((carrier) => (
              <CarrierRow
                key={carrier.id}
                carrier={carrier}
                selected={selectedIds.has(carrier.id)}
                onToggle={() => toggleCarrier(carrier.id)}
              />
            ))}

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

function CarrierRow({
  carrier,
  selected,
  onToggle,
}: {
  carrier: CarrierItem
  selected: boolean
  onToggle: () => void
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
