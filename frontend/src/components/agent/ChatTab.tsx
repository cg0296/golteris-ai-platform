/**
 * components/agent/ChatTab.tsx — Ask Golteris chat interface (#42).
 *
 * Ad-hoc instructions and questions to the AI agent.
 */

import { useState } from "react"
import { Send } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { Card, CardContent } from "@/components/ui/card"

export function ChatTab() {
  const [message, setMessage] = useState("")

  return (
    <div className="space-y-4 max-w-2xl">
      <p className="text-sm text-muted-foreground">
        Ask Golteris a question or give an ad-hoc instruction. The AI can look up RFQ status,
        explain decisions, or take actions on your behalf.
      </p>

      {/* Chat area */}
      <Card className="shadow-sm">
        <CardContent className="p-4 min-h-[300px] flex flex-col justify-end">
          <div className="flex-1 flex items-center justify-center">
            <p className="text-sm text-muted-foreground italic">
              Start a conversation — ask about an RFQ, carrier, or give an instruction
            </p>
          </div>
        </CardContent>
      </Card>

      {/* Input */}
      <div className="flex gap-2">
        <Textarea
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          placeholder="Ask Golteris anything..."
          className="min-h-[44px] max-h-[120px] resize-none"
          rows={1}
        />
        <Button
          disabled={!message.trim()}
          className="bg-[#0F9ED5] hover:bg-[#0B7FAD] text-white shrink-0"
        >
          <Send className="h-4 w-4" />
        </Button>
      </div>
    </div>
  )
}
