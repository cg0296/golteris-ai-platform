/**
 * hooks/use-mailboxes.ts — React Query hooks for mailbox management (#48).
 *
 * CRUD operations for email mailbox connections. The broker uses these
 * from the Settings page to add, remove, test, and toggle mailboxes.
 */

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { api } from "@/lib/api"

export interface MailboxItem {
  id: number
  name: string
  email: string
  provider_type: string
  config: Record<string, string>
  active: boolean
  poll_interval_seconds: number
  last_polled_at: string | null
  last_error: string | null
  created_at: string | null
}

interface MailboxListResponse {
  mailboxes: MailboxItem[]
  total: number
}

/** Fetch all configured mailboxes. */
export function useMailboxes() {
  return useQuery({
    queryKey: ["mailboxes"],
    queryFn: () => api.get<MailboxListResponse>("/api/mailboxes"),
  })
}

/** Add a new mailbox connection. */
export function useCreateMailbox() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: {
      name: string
      email: string
      provider_type: string
      config: Record<string, string>
      poll_interval_seconds?: number
    }) => api.post<MailboxItem>("/api/mailboxes", body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["mailboxes"] }),
  })
}

/** Delete a mailbox connection. */
export function useDeleteMailbox() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => api.delete<{ status: string }>(`/api/mailboxes/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["mailboxes"] }),
  })
}

/** Test connectivity to a mailbox. */
export function useTestMailbox() {
  return useMutation({
    mutationFn: (id: number) =>
      api.post<{ status: string; provider: string; messages_found: number; message: string }>(
        `/api/mailboxes/${id}/test`
      ),
  })
}

/** Toggle a mailbox's active status. */
export function useToggleMailbox() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, active }: { id: number; active: boolean }) =>
      api.patch<MailboxItem>(`/api/mailboxes/${id}`, { active }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["mailboxes"] }),
  })
}
