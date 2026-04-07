/**
 * lib/api.ts — Fetch wrapper for the Golteris REST API.
 *
 * Provides typed GET and POST helpers that prepend the base URL and
 * handle JSON parsing. In production the frontend is served from the
 * same origin as the API, so the base URL is empty. In local dev
 * (Vite on :5173, FastAPI on :8000) CORS is already configured.
 */

const BASE_URL = import.meta.env.DEV ? "http://localhost:8001" : ""

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body.detail || `API error ${res.status}`)
  }
  return res.json()
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "POST", body: JSON.stringify(body) }),
}
