/**
 * components/agent/ChatTab.tsx — Ask Golteris chat interface (#99).
 *
 * Wired to Claude via POST /api/chat. The broker asks questions and
 * gets answers based on live RFQ data from the database.
 */

import { useState, useRef, useEffect } from "react"
import { Send, Bot, User } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { api } from "@/lib/api"

interface ChatMessage {
  role: "user" | "assistant"
  content: string
}

export function ChatTab() {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [input, setInput] = useState("")
  const [isLoading, setIsLoading] = useState(false)
  const scrollRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" })
  }, [messages])

  const handleSend = async () => {
    const msg = input.trim()
    if (!msg || isLoading) return

    setInput("")
    setMessages((prev) => [...prev, { role: "user", content: msg }])
    setIsLoading(true)

    try {
      const res = await api.post<{ reply: string }>("/api/chat", { message: msg })
      setMessages((prev) => [...prev, { role: "assistant", content: res.reply }])
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: "Sorry, I couldn't process that request. Please try again." },
      ])
    } finally {
      setIsLoading(false)
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  return (
    <div className="flex flex-col h-[600px] max-w-2xl">
      {/* Messages area */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto space-y-4 mb-4">
        {messages.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-center">
            <Bot className="h-10 w-10 text-[#0F9ED5] mb-3" />
            <p className="text-sm font-medium text-[#0E2841]">Ask Golteris</p>
            <p className="text-xs text-muted-foreground mt-1 max-w-sm">
              Ask about RFQ status, carrier bids, shipment details, or anything about your freight operations.
            </p>
            <div className="flex flex-wrap gap-2 mt-4 justify-center">
              {[
                "What RFQs need attention?",
                "Show me today's activity",
                "Any carrier bids received?",
              ].map((q) => (
                <button
                  key={q}
                  onClick={() => { setInput(q); }}
                  className="text-xs px-3 py-1.5 rounded-full border hover:bg-muted/50 text-muted-foreground"
                >
                  {q}
                </button>
              ))}
            </div>
          </div>
        ) : (
          messages.map((msg, i) => (
            <div
              key={i}
              className={`flex gap-3 ${msg.role === "user" ? "justify-end" : ""}`}
            >
              {msg.role === "assistant" && (
                <div className="h-7 w-7 rounded-full bg-[#0F9ED5] flex items-center justify-center shrink-0">
                  <Bot className="h-4 w-4 text-white" />
                </div>
              )}
              <div
                className={`rounded-lg px-3 py-2 max-w-[80%] text-sm ${
                  msg.role === "user"
                    ? "bg-[#0E2841] text-white"
                    : "bg-muted/50 border"
                }`}
              >
                <p className="whitespace-pre-wrap">{msg.content}</p>
              </div>
              {msg.role === "user" && (
                <div className="h-7 w-7 rounded-full bg-gray-200 flex items-center justify-center shrink-0">
                  <User className="h-4 w-4 text-gray-600" />
                </div>
              )}
            </div>
          ))
        )}
        {isLoading && (
          <div className="flex gap-3">
            <div className="h-7 w-7 rounded-full bg-[#0F9ED5] flex items-center justify-center shrink-0">
              <Bot className="h-4 w-4 text-white" />
            </div>
            <div className="bg-muted/50 border rounded-lg px-3 py-2">
              <div className="flex gap-1">
                <span className="h-2 w-2 bg-muted-foreground/40 rounded-full animate-bounce" style={{ animationDelay: "0ms" }} />
                <span className="h-2 w-2 bg-muted-foreground/40 rounded-full animate-bounce" style={{ animationDelay: "150ms" }} />
                <span className="h-2 w-2 bg-muted-foreground/40 rounded-full animate-bounce" style={{ animationDelay: "300ms" }} />
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Input */}
      <div className="flex gap-2">
        <Textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Ask Golteris anything..."
          className="min-h-[44px] max-h-[120px] resize-none"
          rows={1}
          disabled={isLoading}
        />
        <Button
          onClick={handleSend}
          disabled={!input.trim() || isLoading}
          className="bg-[#0F9ED5] hover:bg-[#0B7FAD] text-white shrink-0"
        >
          <Send className="h-4 w-4" />
        </Button>
      </div>
    </div>
  )
}
