/**
 * pages/LoginPage.tsx — Login and registration page (#54).
 */

import { useState } from "react"
import { useAuth } from "@/lib/auth"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"

export function LoginPage() {
  const { login, register } = useAuth()
  const [isRegister, setIsRegister] = useState(false)
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const [name, setName] = useState("")
  const [error, setError] = useState("")
  const [isLoading, setIsLoading] = useState(false)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError("")
    setIsLoading(true)
    try {
      if (isRegister) {
        await register(email, password, name)
      } else {
        await login(email, password)
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Authentication failed")
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-[#F5F7FA] flex items-center justify-center p-4">
      <Card className="w-full max-w-md shadow-lg">
        <CardHeader className="text-center pb-2">
          <h1 className="text-2xl font-bold text-[#0E2841]">Golteris</h1>
          <p className="text-xs text-muted-foreground">Freight Broker Console</p>
          <CardTitle className="text-lg mt-4">
            {isRegister ? "Create Account" : "Sign In"}
          </CardTitle>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="space-y-4">
            {isRegister && (
              <div>
                <label className="text-sm font-medium">Name</label>
                <input
                  type="text"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  required
                  className="w-full mt-1 px-3 py-2 text-sm border rounded-md focus:outline-none focus:ring-2 focus:ring-[#0F9ED5]/30 focus:border-[#0F9ED5]"
                  placeholder="Jillian"
                />
              </div>
            )}
            <div>
              <label className="text-sm font-medium">Email</label>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                className="w-full mt-1 px-3 py-2 text-sm border rounded-md focus:outline-none focus:ring-2 focus:ring-[#0F9ED5]/30 focus:border-[#0F9ED5]"
                placeholder="you@company.com"
              />
            </div>
            <div>
              <label className="text-sm font-medium">Password</label>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                className="w-full mt-1 px-3 py-2 text-sm border rounded-md focus:outline-none focus:ring-2 focus:ring-[#0F9ED5]/30 focus:border-[#0F9ED5]"
                placeholder="••••••••"
              />
            </div>
            {error && (
              <p className="text-sm text-red-600 bg-red-50 px-3 py-2 rounded">{error}</p>
            )}
            <Button
              type="submit"
              disabled={isLoading}
              className="w-full bg-[#0F9ED5] hover:bg-[#0B7FAD] text-white"
            >
              {isLoading ? "..." : isRegister ? "Create Account" : "Sign In"}
            </Button>
          </form>
          <div className="mt-4 text-center">
            <button
              onClick={() => { setIsRegister(!isRegister); setError("") }}
              className="text-xs text-[#0F9ED5] hover:underline"
            >
              {isRegister ? "Already have an account? Sign in" : "Need an account? Register"}
            </button>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
