/**
 * hooks/use-memories.ts — React Query hooks for agent memory (#49).
 */

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { api } from "@/lib/api"

export interface MemoryItem {
  id: number
  category: string
  content: string
  source: string | null
  status: string
  confidence: number | null
  times_applied: number
  created_at: string | null
  updated_at: string | null
}

interface MemoryListResponse {
  memories: MemoryItem[]
  total: number
  counts: Record<string, number>
}

export function useMemories(category?: string) {
  const params = category ? `?category=${category}` : ""
  return useQuery({
    queryKey: ["memories", category],
    queryFn: () => api.get<MemoryListResponse>(`/api/agent/memories${params}`),
  })
}

export function useCreateMemory() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: { category: string; content: string }) =>
      api.post<MemoryItem>("/api/agent/memories", body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["memories"] }),
  })
}

export function useUpdateMemory() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, ...body }: { id: number; status?: string; content?: string }) =>
      api.patch<MemoryItem>(`/api/agent/memories/${id}`, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["memories"] }),
  })
}

export function useDeleteMemory() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => api.delete<{ status: string }>(`/api/agent/memories/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["memories"] }),
  })
}
