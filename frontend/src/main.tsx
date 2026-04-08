/**
 * main.tsx — Application entry point for the Golteris broker console.
 *
 * Sets up:
 * 1. AuthProvider for authentication (#54)
 * 2. BrowserRouter for client-side routing (React Router v6)
 * 3. QueryClientProvider for data fetching with 10-second polling (React Query)
 * 4. Route definitions for all pages
 * 5. Login gate — unauthenticated users see the login page
 */

import React from "react"
import ReactDOM from "react-dom/client"
import { BrowserRouter, Routes, Route } from "react-router-dom"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { Toaster } from "@/components/ui/sonner"
import { AuthProvider, useAuth } from "@/lib/auth"
import { CostVisibilityProvider } from "@/lib/cost-visibility"
import App from "./App"
import { LoginPage } from "./pages/LoginPage"
import { DashboardPage } from "./pages/DashboardPage"
import { InboxPage } from "./pages/InboxPage"
import { RfqsPage } from "./pages/RfqsPage"
import { HistoryPage } from "./pages/HistoryPage"
import { AgentPage } from "./pages/AgentPage"
import { SettingsPage } from "./pages/SettingsPage"
import { AdminPage } from "./pages/AdminPage"
import "./index.css"

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 5_000,
      refetchInterval: 10_000,
      retry: 2,
    },
  },
})

/** Gate — shows login page if not authenticated, app if authenticated. */
function AuthGate() {
  const { user, isLoading } = useAuth()

  if (isLoading) {
    return (
      <div className="min-h-screen bg-[#F5F7FA] flex items-center justify-center">
        <div className="text-center">
          <h1 className="text-xl font-bold text-[#0E2841]">Golteris</h1>
          <p className="text-sm text-muted-foreground mt-1">Loading...</p>
        </div>
      </div>
    )
  }

  if (!user) {
    return <LoginPage />
  }

  return (
    <Routes>
      <Route element={<App />}>
        <Route index element={<DashboardPage />} />
        <Route path="inbox" element={<InboxPage />} />
        <Route path="rfqs" element={<RfqsPage />} />
        <Route path="history" element={<HistoryPage />} />
        <Route path="agent" element={<AgentPage />} />
        <Route path="settings" element={<SettingsPage />} />
        <Route path="admin" element={<AdminPage />} />
      </Route>
    </Routes>
  )
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <CostVisibilityProvider>
          <BrowserRouter>
            <AuthGate />
          </BrowserRouter>
        </CostVisibilityProvider>
      </AuthProvider>
      <Toaster position="bottom-right" richColors />
    </QueryClientProvider>
  </React.StrictMode>
)
