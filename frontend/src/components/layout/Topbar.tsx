/**
 * components/layout/Topbar.tsx — Top bar with page title and system status.
 *
 * Shows the current page title on the left and a "System Live" status
 * indicator on the right. On mobile, includes the hamburger menu trigger.
 */

import { Menu } from "lucide-react"
import { Button } from "@/components/ui/button"

interface TopbarProps {
  /** Current page title shown in the top bar */
  title: string
  /** Callback when the mobile hamburger menu is clicked */
  onMenuClick: () => void
}

export function Topbar({ title, onMenuClick }: TopbarProps) {
  return (
    <header className="h-14 border-b bg-white flex items-center justify-between px-4 lg:px-6 shrink-0">
      <div className="flex items-center gap-3">
        {/* Hamburger — visible only on mobile */}
        <Button
          variant="ghost"
          size="icon"
          className="lg:hidden"
          onClick={onMenuClick}
          aria-label="Open navigation menu"
        >
          <Menu className="h-5 w-5" />
        </Button>
        <h2 className="text-lg font-semibold text-[#0E2841]">{title}</h2>
      </div>

      {/* System status indicator */}
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <span className="relative flex h-2 w-2">
          <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-green-400 opacity-75" />
          <span className="relative inline-flex h-2 w-2 rounded-full bg-green-500" />
        </span>
        System Live
      </div>
    </header>
  )
}
