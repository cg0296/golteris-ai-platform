/**
 * hooks/use-message-thread.ts — React Query hook for message thread data (#111).
 *
 * Fetches GET /api/messages/:id/thread which returns the clicked message
 * plus all messages sharing the same RFQ (the full conversation thread).
 */

import { useQuery } from "@tanstack/react-query"
import { api } from "@/lib/api"

export interface ThreadMessage {
  id: number
  rfq_id: number | null
  direction: "inbound" | "outbound"
  sender: string
  subject: string | null
  body: string
  routing_status: string | null
  routing_label: string | null
  received_at: string | null
  rfq: {
    id: number
    customer_name: string
    state_label: string | null
  } | null
}

export interface MessageThreadResponse {
  message: ThreadMessage
  thread: ThreadMessage[]
  rfq: {
    id: number
    customer_name: string
    customer_company: string | null
    state_label: string | null
    origin: string | null
    destination: string | null
  } | null
}

export function useMessageThread(messageId: number | null) {
  return useQuery({
    queryKey: ["message", "thread", messageId],
    queryFn: () =>
      api.get<MessageThreadResponse>(`/api/messages/${messageId}/thread`),
    enabled: messageId !== null,
  })
}
