/**
 * components/layout/Topbar.tsx — Top bar with page title, user, and system status.
 */

import { Menu, LogOut } from "lucide-react"
import { Button } from "@/components/ui/button"
import { useAuth } from "@/lib/auth"

interface TopbarProps {
  title: string
  onMenuClick: () => void
}

export function Topbar({ title, onMenuClick }: TopbarProps) {
  const { user, logout } = useAuth()

  return (
    <header className="h-14 border-b bg-white flex items-center justify-between px-4 lg:px-6 shrink-0">
      <div className="flex items-center gap-3">
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

      <div className="flex items-center gap-4">
        {/* System status */}
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <span className="relative flex h-2 w-2">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-green-400 opacity-75" />
            <span className="relative inline-flex h-2 w-2 rounded-full bg-green-500" />
          </span>
          System Live
        </div>

        {/* User info + logout */}
        {user && (
          <div className="flex items-center gap-2">
            <span className="text-sm text-muted-foreground hidden sm:block">
              {user.name}
            </span>
            <Button
              variant="ghost"
              size="icon"
              onClick={logout}
              className="h-8 w-8"
              aria-label="Sign out"
            >
              <LogOut className="h-4 w-4 text-muted-foreground" />
            </Button>
          </div>
        )}
      </div>
    </header>
  )
}
