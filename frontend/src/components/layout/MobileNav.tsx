/**
 * components/layout/MobileNav.tsx — Hamburger overlay navigation for mobile.
 *
 * Slides in from the left when triggered by the Topbar hamburger button.
 * Uses the same nav items and styling as the desktop Sidebar.
 * Tapping outside or clicking a link closes it automatically.
 */

import { NavLink } from "react-router-dom"
import {
  Home,
  FileText,
  Bot,
  Settings,
  Truck,
  FlaskConical,
  Shield,
  X,
} from "lucide-react"
import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"

const navItems = [
  { to: "/", icon: Home, label: "Home" },
  { to: "/rfqs", icon: FileText, label: "RFQs" },
  { to: "/carriers", icon: Truck, label: "Carriers" },
  { to: "/agent", icon: Bot, label: "Agent" },
  { to: "/settings", icon: Settings, label: "Settings" },
  { to: "/dev", icon: FlaskConical, label: "Dev" },
  { to: "/admin", icon: Shield, label: "Admin" },
]

interface MobileNavProps {
  open: boolean
  onClose: () => void
}

export function MobileNav({ open, onClose }: MobileNavProps) {
  if (!open) return null

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 z-40 bg-black/50 lg:hidden"
        onClick={onClose}
        aria-hidden="true"
      />

      {/* Slide-in panel */}
      <div className="fixed inset-y-0 left-0 z-50 w-64 bg-[#0E2841] text-white lg:hidden flex flex-col">
        <div className="flex items-center justify-between px-5 py-5 border-b border-[#1c3a56]">
          <div>
            <h1 className="text-lg font-bold tracking-tight">Golteris</h1>
            <p className="text-xs text-[#a8b9cc] mt-0.5">Beltmann Logistics</p>
          </div>
          <Button
            variant="ghost"
            size="icon"
            onClick={onClose}
            className="text-[#a8b9cc] hover:text-white hover:bg-[#1a3a57]"
            aria-label="Close navigation menu"
          >
            <X className="h-5 w-5" />
          </Button>
        </div>

        <nav className="flex-1 px-3 py-4 space-y-1">
          {navItems.map(({ to, icon: Icon, label }) => (
            <NavLink
              key={to}
              to={to}
              end={to === "/"}
              onClick={onClose}
              className={({ isActive }) =>
                cn(
                  "flex items-center gap-3 px-3 py-2 rounded-md text-sm transition-colors",
                  isActive
                    ? "bg-[#0F9ED5] text-white font-medium"
                    : "text-[#a8b9cc] hover:bg-[#1a3a57] hover:text-white"
                )
              }
            >
              <Icon className="h-4 w-4 shrink-0" />
              {label}
            </NavLink>
          ))}
        </nav>
      </div>
    </>
  )
}
