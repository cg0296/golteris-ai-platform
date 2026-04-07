/**
 * lib/auth.tsx — Authentication context and hooks (#54).
 *
 * Provides AuthProvider, useAuth hook, and ProtectedRoute wrapper.
 * Stores JWT token in localStorage. Auto-validates on mount.
 */

import { createContext, useContext, useState, useEffect, type ReactNode } from "react"
import { api } from "./api"

interface AuthUser {
  id: number
  email: string
  name: string
  role: string
}

interface AuthContextType {
  user: AuthUser | null
  token: string | null
  isLoading: boolean
  login: (email: string, password: string) => Promise<void>
  register: (email: string, password: string, name: string) => Promise<void>
  logout: () => void
}

const AuthContext = createContext<AuthContextType | null>(null)

const TOKEN_KEY = "golteris_token"

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null)
  const [token, setToken] = useState<string | null>(localStorage.getItem(TOKEN_KEY))
  const [isLoading, setIsLoading] = useState(true)

  // Validate token on mount
  useEffect(() => {
    if (token) {
      fetch(`${import.meta.env.DEV ? "http://localhost:8001" : ""}/api/auth/me`, {
        headers: { Authorization: `Bearer ${token}` },
      })
        .then((r) => (r.ok ? r.json() : Promise.reject()))
        .then((data) => setUser(data))
        .catch(() => {
          localStorage.removeItem(TOKEN_KEY)
          setToken(null)
          setUser(null)
        })
        .finally(() => setIsLoading(false))
    } else {
      setIsLoading(false)
    }
  }, [token])

  const login = async (email: string, password: string) => {
    const res = await api.post<{ token: string; user: AuthUser }>("/api/auth/login", {
      email,
      password,
    })
    localStorage.setItem(TOKEN_KEY, res.token)
    setToken(res.token)
    setUser(res.user)
  }

  const register = async (email: string, password: string, name: string) => {
    const res = await api.post<{ token: string; user: AuthUser }>("/api/auth/register", {
      email,
      password,
      name,
    })
    localStorage.setItem(TOKEN_KEY, res.token)
    setToken(res.token)
    setUser(res.user)
  }

  const logout = () => {
    localStorage.removeItem(TOKEN_KEY)
    setToken(null)
    setUser(null)
  }

  return (
    <AuthContext.Provider value={{ user, token, isLoading, login, register, logout }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error("useAuth must be used within AuthProvider")
  return ctx
}
