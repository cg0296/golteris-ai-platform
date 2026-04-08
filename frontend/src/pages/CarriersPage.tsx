/**
 * pages/CarriersPage.tsx — Carrier management (#137).
 *
 * Add, edit, view, and organize carriers. Supports search, filter by
 * equipment type, preferred status toggle.
 */

import { useState } from "react"
import { Truck, Plus, Search, Star, Trash2, Edit2, X } from "lucide-react"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { api } from "@/lib/api"

interface CarrierItem {
  id: number
  name: string
  email: string
  contact_name: string
  phone: string
  equipment_types: string[]
  lanes: { origin: string; destination: string }[]
  preferred: boolean
}

export function CarriersPage() {
  const [search, setSearch] = useState("")
  const [showAdd, setShowAdd] = useState(false)
  const [newCarrier, setNewCarrier] = useState({ name: "", email: "", contact_name: "", phone: "", equipment_types: "", preferred: false })
  const qc = useQueryClient()

  const carriers = useQuery({
    queryKey: ["carriers"],
    queryFn: () => api.get<{ carriers: CarrierItem[]; total: number }>("/api/carriers"),
  })

  const createCarrier = useMutation({
    mutationFn: (body: Record<string, unknown>) => api.post<CarrierItem>("/api/carriers", body),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["carriers"] }); toast.success("Carrier added"); setShowAdd(false) },
  })

  const deleteCarrier = useMutation({
    mutationFn: (id: number) => api.delete<{ status: string }>(`/api/carriers/${id}`),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["carriers"] }); toast.success("Carrier removed") },
  })

  const togglePreferred = useMutation({
    mutationFn: ({ id, preferred }: { id: number; preferred: boolean }) => api.patch<CarrierItem>(`/api/carriers/${id}`, { preferred }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["carriers"] }),
  })

  const filtered = (carriers.data?.carriers ?? []).filter((c) =>
    !search || c.name.toLowerCase().includes(search.toLowerCase()) || c.email.toLowerCase().includes(search.toLowerCase())
  )

  return (
    <div className="p-4 lg:p-6 max-w-7xl space-y-4">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
        <h2 className="text-xl font-semibold text-[#0E2841] flex items-center gap-2">
          <Truck className="h-5 w-5" />
          Carriers
          <span className="text-sm font-normal text-muted-foreground">({carriers.data?.total ?? 0})</span>
        </h2>
        <div className="flex items-center gap-2">
          <div className="relative w-full sm:w-64">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
            <input type="text" placeholder="Search carriers..." value={search} onChange={(e) => setSearch(e.target.value)} className="w-full pl-9 pr-3 py-2 text-sm border rounded-md bg-white focus:outline-none focus:ring-2 focus:ring-[#0F9ED5]/30" />
          </div>
          <Button size="sm" onClick={() => setShowAdd(!showAdd)}>{showAdd ? <X className="h-4 w-4" /> : <><Plus className="h-4 w-4 mr-1" /> Add</>}</Button>
        </div>
      </div>

      {showAdd && (
        <Card className="shadow-sm">
          <CardContent className="p-4 space-y-3">
            <div className="grid grid-cols-2 gap-3">
              <input placeholder="Company name" value={newCarrier.name} onChange={(e) => setNewCarrier({ ...newCarrier, name: e.target.value })} className="px-3 py-2 text-sm border rounded-md" />
              <input placeholder="Email" value={newCarrier.email} onChange={(e) => setNewCarrier({ ...newCarrier, email: e.target.value })} className="px-3 py-2 text-sm border rounded-md" />
              <input placeholder="Contact name" value={newCarrier.contact_name} onChange={(e) => setNewCarrier({ ...newCarrier, contact_name: e.target.value })} className="px-3 py-2 text-sm border rounded-md" />
              <input placeholder="Phone" value={newCarrier.phone} onChange={(e) => setNewCarrier({ ...newCarrier, phone: e.target.value })} className="px-3 py-2 text-sm border rounded-md" />
              <input placeholder="Equipment types (comma separated)" value={newCarrier.equipment_types} onChange={(e) => setNewCarrier({ ...newCarrier, equipment_types: e.target.value })} className="px-3 py-2 text-sm border rounded-md col-span-2" />
            </div>
            <Button size="sm" disabled={!newCarrier.name || createCarrier.isPending} onClick={() => createCarrier.mutate({ ...newCarrier, equipment_types: newCarrier.equipment_types.split(",").map((s) => s.trim()).filter(Boolean) })} className="bg-[#0F9ED5] hover:bg-[#0B7FAD] text-white">
              {createCarrier.isPending ? "Adding..." : "Add Carrier"}
            </Button>
          </CardContent>
        </Card>
      )}

      <div className="space-y-2">
        {carriers.isLoading ? (
          [...Array(5)].map((_, i) => <div key={i} className="h-16 bg-white rounded-lg animate-pulse shadow-sm" />)
        ) : filtered.length === 0 ? (
          <p className="text-sm text-muted-foreground text-center py-8">No carriers found</p>
        ) : (
          filtered.map((c) => (
            <div key={c.id} className="bg-white rounded-lg border shadow-sm p-4 flex items-center justify-between gap-4">
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <p className="text-sm font-medium">{c.name}</p>
                  {c.preferred && <Star className="h-3.5 w-3.5 text-amber-500 fill-amber-500" />}
                  {c.equipment_types.map((eq) => (
                    <Badge key={eq} variant="secondary" className="text-[10px]">{eq}</Badge>
                  ))}
                </div>
                <p className="text-xs text-muted-foreground">{c.contact_name} · {c.email} · {c.phone}</p>
                {c.lanes.length > 0 && (
                  <p className="text-xs text-muted-foreground mt-0.5">{c.lanes.map((l) => `${l.origin} → ${l.destination}`).join(", ")}</p>
                )}
              </div>
              <div className="flex items-center gap-1.5 shrink-0">
                <Button size="sm" variant="outline" className="h-7 px-2" onClick={() => togglePreferred.mutate({ id: c.id, preferred: !c.preferred })} title={c.preferred ? "Remove preferred" : "Mark preferred"}>
                  <Star className={`h-3.5 w-3.5 ${c.preferred ? "text-amber-500 fill-amber-500" : "text-gray-400"}`} />
                </Button>
                <Button size="sm" variant="outline" className="h-7 px-2 text-red-600 border-red-300" onClick={() => deleteCarrier.mutate(c.id)}>
                  <Trash2 className="h-3.5 w-3.5" />
                </Button>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  )
}
