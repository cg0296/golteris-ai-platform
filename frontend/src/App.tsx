/**
 * App.tsx — Root layout shell for the Golteris broker console.
 *
 * Renders the navy sidebar (desktop) or hamburger overlay (mobile), a top bar
 * with page title and system status, and an <Outlet/> for the active page.
 *
 * React Router handles client-side routing — the backend catch-all serves
 * index.html for any path that doesn't match /api/* or /health.
 */

import { useState } from "react"
import { Outlet, useLocation } from "react-router-dom"
import { Sidebar } from "@/components/layout/Sidebar"
import { Topbar } from "@/components/layout/Topbar"
import { MobileNav } from "@/components/layout/MobileNav"
import { ChatBubble } from "@/components/layout/ChatBubble"

/** Map route paths to page titles for the top bar. */
const pageTitles: Record<string, string> = {
  "/": "Home",
  "/inbox": "Inbox",
  "/rfqs": "RFQs",
  "/history": "History",
  "/agent": "Agent",
  "/settings": "Settings",
  "/admin": "Admin",
}

export default function App() {
  const [mobileNavOpen, setMobileNavOpen] = useState(false)
  const location = useLocation()
  const title = pageTitles[location.pathname] ?? "Golteris"

  return (
    <div className="flex h-screen bg-[#F5F7FA]">
      <Sidebar />
      <MobileNav open={mobileNavOpen} onClose={() => setMobileNavOpen(false)} />

      <div className="flex flex-col flex-1 min-w-0">
        <Topbar title={title} onMenuClick={() => setMobileNavOpen(true)} />
        <main className="flex-1 overflow-y-auto">
          <Outlet />
        </main>
      </div>

      {/* Global chat bubble (#106) — accessible from every page */}
      <ChatBubble />
    </div>
  )
}
