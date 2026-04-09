/**
 * components/layout/Topbar.tsx — Top bar with page title, user, and system status (#157).
 */

import { Menu, LogOut } from "lucide-react"
import { Button } from "@/components/ui/button"
import { useAuth } from "@/lib/auth"
import { useSystemStatus, type SystemState } from "@/hooks/use-system-status"

interface TopbarProps {
  title: string
  onMenuClick: () => void
}

const DOT_STYLES: Record<SystemState, { bg: string; ping: string; text: string }> = {
  processing: { bg: "bg-green-500", ping: "bg-green-400", text: "text-green-700" },
  idle:       { bg: "bg-yellow-400", ping: "", text: "text-yellow-700" },
  stuck:      { bg: "bg-red-500", ping: "", text: "text-red-700" },
}

export function Topbar({ title, onMenuClick }: TopbarProps) {
  const { user, logout } = useAuth()
  const status = useSystemStatus()
  const dot = DOT_STYLES[status.state]

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
        {/* System status indicator (#157) */}
        <div className="flex items-center gap-2 text-sm text-muted-foreground group relative cursor-default">
          <span className="relative flex h-2.5 w-2.5">
            {dot.ping && (
              <span className={`animate-ping absolute inline-flex h-full w-full rounded-full ${dot.ping} opacity-75`} />
            )}
            <span className={`relative inline-flex h-2.5 w-2.5 rounded-full ${dot.bg}`} />
          </span>
          <span className={dot.text}>{status.label}</span>
          {/* Tooltip */}
          <div className="absolute top-full right-0 mt-1 hidden group-hover:block z-50">
            <div className="bg-gray-900 text-white text-xs rounded px-3 py-1.5 whitespace-nowrap shadow-lg">
              {status.detail}
            </div>
          </div>
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
