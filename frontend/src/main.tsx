/**
 * main.tsx — Application entry point for the Golteris broker console.
 *
 * Sets up:
 * 1. BrowserRouter for client-side routing (React Router v6)
 * 2. QueryClientProvider for data fetching with 10-second polling (React Query)
 * 3. Route definitions for all pages
 *
 * The QueryClient defaults to 10-second refetch intervals per REQUIREMENTS.md §2.3.
 */

import React from "react"
import ReactDOM from "react-dom/client"
import { BrowserRouter, Routes, Route } from "react-router-dom"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { Toaster } from "@/components/ui/sonner"
import App from "./App"
import { DashboardPage } from "./pages/DashboardPage"
import { InboxPage } from "./pages/InboxPage"
import { RfqsPage } from "./pages/RfqsPage"
import { HistoryPage } from "./pages/HistoryPage"
import { AgentPage } from "./pages/AgentPage"
import { SettingsPage } from "./pages/SettingsPage"
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

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route element={<App />}>
            <Route index element={<DashboardPage />} />
            <Route path="inbox" element={<InboxPage />} />
            <Route path="rfqs" element={<RfqsPage />} />
            <Route path="history" element={<HistoryPage />} />
            <Route path="agent" element={<AgentPage />} />
            <Route path="settings" element={<SettingsPage />} />
          </Route>
        </Routes>
      </BrowserRouter>
      <Toaster position="bottom-right" richColors />
    </QueryClientProvider>
  </React.StrictMode>
)
