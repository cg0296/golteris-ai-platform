/**
 * components/layout/Sidebar.tsx — Navy sidebar navigation for the Golteris console.
 *
 * Matches the proof-of-concept design: dark navy background (#0E2841), white
 * active text, muted inactive text. Shows the Golteris logo at the top and
 * navigation items with Lucide icons.
 *
 * On mobile (<lg), this is hidden and replaced by MobileNav hamburger overlay.
 */

import { NavLink } from "react-router-dom"
import {
  Home,
  FileText,
  Bot,
  Settings,
  Shield,
  Truck,
  FlaskConical,
} from "lucide-react"
import { cn } from "@/lib/utils"
import { useAuth } from "@/lib/auth"

const navItems = [
  { to: "/", icon: Home, label: "Home" },
  { to: "/rfqs", icon: FileText, label: "RFQs" },
  { to: "/carriers", icon: Truck, label: "Carriers" },
  { to: "/agent", icon: Bot, label: "Agent" },
  { to: "/settings", icon: Settings, label: "Settings" },
]

/** Admin-only nav items */
const adminItems = [
  { to: "/dev", icon: FlaskConical, label: "Dev" },
  { to: "/admin", icon: Shield, label: "Admin" },
]

/** @deprecated — replaced by adminItems array above */

export function Sidebar() {
  const { user } = useAuth()
  const isAdmin = user?.role === "admin" || user?.role === "owner"

  return (
    <aside className="hidden lg:flex lg:flex-col lg:w-56 bg-[#0E2841] text-white min-h-screen">
      {/* Logo */}
      <div className="px-5 py-5 border-b border-[#1c3a56]">
        <h1 className="text-lg font-bold tracking-tight">Golteris</h1>
        <p className="text-xs text-[#a8b9cc] mt-0.5">Beltmann Logistics</p>
      </div>

      {/* Nav items */}
      <nav className="flex-1 px-3 py-4 space-y-1">
        {[...navItems, ...(isAdmin ? adminItems : [])].map(({ to, icon: Icon, label }) => (
          <NavLink
            key={to}
            to={to}
            end={to === "/"}
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

      {/* Footer */}
      <div className="px-5 py-4 border-t border-[#1c3a56] text-xs text-[#a8b9cc]">
        v0.1.0
      </div>
    </aside>
  )
}
