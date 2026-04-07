/**
 * components/layout/ChatBubble.tsx — Global floating chat widget (#106).
 *
 * A small bubble in the bottom-right corner of every page. Clicking it
 * opens an Ask Golteris chat panel as an overlay. Chat state persists
 * across page navigations since this component lives in App.tsx.
 *
 * Uses the same POST /api/chat endpoint as the Agent page's ChatTab (#99).
 *
 * Cross-cutting constraints:
 *   C3 — Chat responses use plain English (enforced by the backend prompt)
 *   C4 — Every chat message logs as an agent_call (handled by backend)
 */

import { useState, useRef, useEffect } from "react"
import { MessageCircle, X, Send, Bot, User } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { api } from "@/lib/api"

interface ChatMessage {
  role: "user" | "assistant"
  content: string
}

export function ChatBubble() {
  const [isOpen, setIsOpen] = useState(false)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [input, setInput] = useState("")
  const [isLoading, setIsLoading] = useState(false)
  const scrollRef = useRef<HTMLDivElement>(null)

  /* Auto-scroll to the latest message */
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
    } catch {
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
    <>
      {/* Chat panel — fixed overlay above the bubble */}
      {isOpen && (
        <div className="fixed bottom-20 right-4 sm:right-6 z-50 w-[360px] max-w-[calc(100vw-2rem)] bg-white rounded-xl shadow-2xl border flex flex-col overflow-hidden"
          style={{ height: "480px" }}
        >
          {/* Header */}
          <div className="flex items-center justify-between px-4 py-3 border-b bg-[#0E2841]">
            <div className="flex items-center gap-2">
              <Bot className="h-4 w-4 text-[#0F9ED5]" />
              <span className="text-sm font-medium text-white">Ask Golteris</span>
            </div>
            <button
              onClick={() => setIsOpen(false)}
              className="text-white/70 hover:text-white"
            >
              <X className="h-4 w-4" />
            </button>
          </div>

          {/* Messages */}
          <div ref={scrollRef} className="flex-1 overflow-y-auto p-4 space-y-3">
            {messages.length === 0 ? (
              <div className="flex flex-col items-center justify-center h-full text-center">
                <Bot className="h-8 w-8 text-[#0F9ED5] mb-2" />
                <p className="text-xs text-muted-foreground max-w-[240px]">
                  Ask about RFQ status, carrier bids, shipment details, or anything about your operations.
                </p>
                <div className="flex flex-wrap gap-1.5 mt-3 justify-center">
                  {["What needs attention?", "Today's activity", "Carrier bids?"].map((q) => (
                    <button
                      key={q}
                      onClick={() => setInput(q)}
                      className="text-[10px] px-2 py-1 rounded-full border hover:bg-muted/50 text-muted-foreground"
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
                  className={`flex gap-2 ${msg.role === "user" ? "justify-end" : ""}`}
                >
                  {msg.role === "assistant" && (
                    <div className="h-6 w-6 rounded-full bg-[#0F9ED5] flex items-center justify-center shrink-0">
                      <Bot className="h-3 w-3 text-white" />
                    </div>
                  )}
                  <div
                    className={`rounded-lg px-3 py-2 max-w-[80%] text-xs ${
                      msg.role === "user"
                        ? "bg-[#0E2841] text-white"
                        : "bg-muted/50 border"
                    }`}
                  >
                    <p className="whitespace-pre-wrap">{msg.content}</p>
                  </div>
                  {msg.role === "user" && (
                    <div className="h-6 w-6 rounded-full bg-gray-200 flex items-center justify-center shrink-0">
                      <User className="h-3 w-3 text-gray-600" />
                    </div>
                  )}
                </div>
              ))
            )}
            {isLoading && (
              <div className="flex gap-2">
                <div className="h-6 w-6 rounded-full bg-[#0F9ED5] flex items-center justify-center shrink-0">
                  <Bot className="h-3 w-3 text-white" />
                </div>
                <div className="bg-muted/50 border rounded-lg px-3 py-2">
                  <div className="flex gap-1">
                    <span className="h-1.5 w-1.5 bg-muted-foreground/40 rounded-full animate-bounce" style={{ animationDelay: "0ms" }} />
                    <span className="h-1.5 w-1.5 bg-muted-foreground/40 rounded-full animate-bounce" style={{ animationDelay: "150ms" }} />
                    <span className="h-1.5 w-1.5 bg-muted-foreground/40 rounded-full animate-bounce" style={{ animationDelay: "300ms" }} />
                  </div>
                </div>
              </div>
            )}
          </div>

          {/* Input */}
          <div className="flex gap-2 p-3 border-t">
            <Textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Ask anything..."
              className="min-h-[36px] max-h-[80px] resize-none text-xs"
              rows={1}
              disabled={isLoading}
            />
            <Button
              onClick={handleSend}
              disabled={!input.trim() || isLoading}
              size="icon-sm"
              className="bg-[#0F9ED5] hover:bg-[#0B7FAD] text-white shrink-0"
            >
              <Send className="h-3.5 w-3.5" />
            </Button>
          </div>
        </div>
      )}

      {/* Floating bubble button */}
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="fixed bottom-4 right-4 sm:right-6 z-50 h-12 w-12 rounded-full bg-[#0F9ED5] hover:bg-[#0B7FAD] text-white shadow-lg flex items-center justify-center transition-transform hover:scale-105 active:scale-95"
        aria-label={isOpen ? "Close chat" : "Open chat"}
      >
        {isOpen ? (
          <X className="h-5 w-5" />
        ) : (
          <MessageCircle className="h-5 w-5" />
        )}
      </button>
    </>
  )
}
