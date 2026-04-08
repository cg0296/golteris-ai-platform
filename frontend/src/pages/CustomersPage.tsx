/**
 * pages/CustomersPage.tsx — Customer (shipper) management (#138).
 *
 * Auto-populated from RFQ data. Shows unique customers with their
 * RFQ count, last activity, and contact info. Links to their RFQs.
 */

import { useState } from "react"
import { Users, Search } from "lucide-react"
import { useQuery } from "@tanstack/react-query"
import { Badge } from "@/components/ui/badge"
import { api } from "@/lib/api"
import { formatRelativeTime } from "@/lib/utils"

interface CustomerSummary {
  customer_name: string
  customer_email: string
  customer_company: string | null
  rfq_count: number
  last_rfq_at: string | null
  states: Record<string, number>
}

export function CustomersPage() {
  const [search, setSearch] = useState("")

  const customers = useQuery({
    queryKey: ["customers"],
    queryFn: () => api.get<{ customers: CustomerSummary[]; total: number }>("/api/customers"),
  })

  const filtered = (customers.data?.customers ?? []).filter((c) =>
    !search ||
    c.customer_name?.toLowerCase().includes(search.toLowerCase()) ||
    c.customer_email?.toLowerCase().includes(search.toLowerCase()) ||
    c.customer_company?.toLowerCase().includes(search.toLowerCase())
  )

  return (
    <div className="p-4 lg:p-6 max-w-7xl space-y-4">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
        <h2 className="text-xl font-semibold text-[#0E2841] flex items-center gap-2">
          <Users className="h-5 w-5" />
          Customers
          <span className="text-sm font-normal text-muted-foreground">({customers.data?.total ?? 0})</span>
        </h2>
        <div className="relative w-full sm:w-72">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <input type="text" placeholder="Search customers..." value={search} onChange={(e) => setSearch(e.target.value)} className="w-full pl-9 pr-3 py-2 text-sm border rounded-md bg-white focus:outline-none focus:ring-2 focus:ring-[#0F9ED5]/30" />
        </div>
      </div>

      <div className="space-y-2">
        {customers.isLoading ? (
          [...Array(5)].map((_, i) => <div key={i} className="h-16 bg-white rounded-lg animate-pulse shadow-sm" />)
        ) : filtered.length === 0 ? (
          <p className="text-sm text-muted-foreground text-center py-8">No customers found</p>
        ) : (
          filtered.map((c) => (
            <div key={c.customer_email} className="bg-white rounded-lg border shadow-sm p-4 flex items-center justify-between gap-4">
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <p className="text-sm font-medium">{c.customer_name}</p>
                  {c.customer_company && (
                    <span className="text-xs text-muted-foreground">{c.customer_company}</span>
                  )}
                </div>
                <p className="text-xs text-muted-foreground">{c.customer_email}</p>
              </div>
              <div className="flex items-center gap-3 shrink-0">
                <div className="text-right">
                  <p className="text-sm font-bold text-[#0E2841]">{c.rfq_count}</p>
                  <p className="text-[10px] text-muted-foreground">RFQs</p>
                </div>
                {c.last_rfq_at && (
                  <div className="text-right">
                    <p className="text-xs text-muted-foreground">{formatRelativeTime(c.last_rfq_at)}</p>
                    <p className="text-[10px] text-muted-foreground">Last RFQ</p>
                  </div>
                )}
                <div className="flex gap-1">
                  {Object.entries(c.states).map(([state, count]) => (
                    <Badge key={state} variant="secondary" className="text-[9px]">{state}: {count}</Badge>
                  ))}
                </div>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  )
}
