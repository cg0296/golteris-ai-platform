/**
 * hooks/use-org-profile.ts — Fetches the org profile for dynamic branding (#174).
 */

import { useQuery } from "@tanstack/react-query"
import { api } from "@/lib/api"

interface OrgProfile {
  company_name: string
  sign_off: string
  ref_prefix: string
  tagline: string
  org_id: number | null
  org_name: string
}

export function useOrgProfile() {
  return useQuery({
    queryKey: ["org", "profile"],
    queryFn: () => api.get<OrgProfile>("/api/organizations/profile"),
    staleTime: 60_000, // Cache for 1 minute — org profile rarely changes
  })
}
