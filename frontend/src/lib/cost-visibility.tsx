/**
 * lib/cost-visibility.tsx — Cost visibility context (#113).
 *
 * Provides a global toggle for showing/hiding cost information across
 * agent views (Decisions, Timeline, Controls). Stored in localStorage
 * so it persists across sessions. Default: visible (on).
 *
 * Usage:
 *   const { showCost } = useCostVisibility()
 *   {showCost && <span>${cost}</span>}
 */

import { createContext, useContext, useState, type ReactNode } from "react"

interface CostVisibilityContextType {
  showCost: boolean
  setShowCost: (show: boolean) => void
}

const STORAGE_KEY = "golteris_show_cost"

const CostVisibilityContext = createContext<CostVisibilityContextType>({
  showCost: true,
  setShowCost: () => {},
})

export function CostVisibilityProvider({ children }: { children: ReactNode }) {
  const [showCost, setShowCostState] = useState(() => {
    const stored = localStorage.getItem(STORAGE_KEY)
    return stored !== null ? stored === "true" : true
  })

  const setShowCost = (show: boolean) => {
    setShowCostState(show)
    localStorage.setItem(STORAGE_KEY, String(show))
  }

  return (
    <CostVisibilityContext.Provider value={{ showCost, setShowCost }}>
      {children}
    </CostVisibilityContext.Provider>
  )
}

export function useCostVisibility() {
  return useContext(CostVisibilityContext)
}
