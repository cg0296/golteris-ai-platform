/**
 * hooks/use-messages.ts — React Query hooks for the Inbox view (#28).
 *
 * Provides:
 * - useMessageList: paginated messages with routing filter and search
 * - useMessageCounts: routing status counts for filter pill badges
 */

import { useQuery } from "@tanstack/react-query"
import { api } from "@/lib/api"

export interface InboxMessage {
  id: number
  rfq_id: number | null
  direction: "inbound" | "outbound" | null
  sender: string
  subject: string | null
  body: string
  routing_status: string | null
  routing_label: string | null
  received_at: string | null
  rfq: {
    id: number
    customer_name: string | null
    state_label: string | null
  } | null
}

interface MessageListResponse {
  messages: InboxMessage[]
  total: number
  limit: number
  offset: number
}

interface MessageListParams {
  limit?: number
  offset?: number
  routingStatus?: string | null
  search?: string
}

export function useMessageList({
  limit = 50,
  offset = 0,
  routingStatus = null,
  search = "",
}: MessageListParams) {
  const params = new URLSearchParams()
  params.set("limit", limit.toString())
  params.set("offset", offset.toString())
  if (routingStatus) params.set("routing_status", routingStatus)
  if (search) params.set("search", search)

  return useQuery({
    queryKey: ["messages", "list", { limit, offset, routingStatus, search }],
    queryFn: () => api.get<MessageListResponse>(`/api/messages?${params.toString()}`),
  })
}

export function useMessageCounts() {
  return useQuery({
    queryKey: ["messages", "counts"],
    queryFn: () => api.get<{ counts: Record<string, number> }>("/api/messages/counts"),
  })
}
