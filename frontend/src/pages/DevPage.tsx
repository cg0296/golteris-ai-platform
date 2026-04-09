/**
 * pages/DevPage.tsx — Dev Area for testing the pipeline with fake emails (#169).
 *
 * Persona-based email injection with templates. Select a role (Carrier/Customer),
 * pick a persona (real Gmail address), choose a template, edit, and send.
 * Goes through the full pipeline via POST /api/dev/inject-email.
 *
 * Admin-only page.
 */

import { useState, useMemo, useEffect } from "react"
import { FlaskConical, Send } from "lucide-react"
import { useQuery } from "@tanstack/react-query"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Textarea } from "@/components/ui/textarea"
import { toast } from "sonner"
import { api } from "@/lib/api"
import { cn } from "@/lib/utils"

interface Persona {
  id: string
  name: string
  email: string
  company: string
  role: "carrier" | "customer"
}

interface Template {
  id: string
  name: string
  role: "carrier" | "customer"
  subject: string
  body: string
}

interface PersonasResponse {
  personas: Persona[]
  templates: Template[]
}

type Role = "carrier" | "customer"

export function DevPage() {
  const [role, setRole] = useState<Role>("customer")
  const [personaId, setPersonaId] = useState<string>("")
  const [templateId, setTemplateId] = useState<string>("")
  const [rfqId, setRfqId] = useState("")
  const [subject, setSubject] = useState("")
  const [body, setBody] = useState("")
  const [sending, setSending] = useState(false)

  // Fetch personas and templates
  const data = useQuery({
    queryKey: ["dev", "personas"],
    queryFn: () => api.get<PersonasResponse>("/api/dev/personas"),
  })

  const personas = useMemo(
    () => (data.data?.personas ?? []).filter((p) => p.role === role),
    [data.data, role]
  )

  const templates = useMemo(
    () => (data.data?.templates ?? []).filter((t) => t.role === role),
    [data.data, role]
  )

  const selectedPersona = personas.find((p) => p.id === personaId)

  // Auto-select first persona when role changes
  useEffect(() => {
    if (personas.length > 0 && !personas.find((p) => p.id === personaId)) {
      setPersonaId(personas[0].id)
    }
  }, [personas, personaId])

  // Apply template — fills in subject and body with persona details
  const applyTemplate = (tplId: string) => {
    setTemplateId(tplId)
    const tpl = templates.find((t) => t.id === tplId)
    if (!tpl || !selectedPersona) return

    const vars: Record<string, string> = {
      name: selectedPersona.name,
      company: selectedPersona.company,
      origin: "",
      destination: "",
      equipment: "",
      truck_count: "",
      commodity: "",
      weight: "",
      pickup_date: "",
      rate: "",
      availability: "",
      reply_text: "",
    }

    let subj = tpl.subject
    let bod = tpl.body
    for (const [key, val] of Object.entries(vars)) {
      subj = subj.replaceAll(`{${key}}`, val)
      bod = bod.replaceAll(`{${key}}`, val)
    }

    // Add [RFQ-NN] tag if replying to an existing RFQ
    if (rfqId.trim()) {
      if (!subj.includes(`[RFQ-${rfqId.trim()}]`)) {
        subj = `${subj} [RFQ-${rfqId.trim()}]`
      }
    }

    setSubject(subj)
    setBody(bod)
  }

  const handleSend = async () => {
    if (!selectedPersona || !subject.trim()) return
    setSending(true)

    // Add [RFQ-NN] tag if specified and not already in subject
    let finalSubject = subject
    if (rfqId.trim() && !finalSubject.includes(`[RFQ-${rfqId.trim()}]`)) {
      finalSubject = `${finalSubject} [RFQ-${rfqId.trim()}]`
    }

    try {
      const result = await api.post<{ status: string; message_id?: number; rfq_id?: number }>("/api/dev/inject-email", {
        sender: `${selectedPersona.name} <${selectedPersona.email}>`,
        subject: finalSubject,
        body: body,
      })

      if (result.status === "duplicate") {
        toast.warning("Duplicate — this exact email was already injected")
      } else {
        toast.success(`Injected as ${selectedPersona.name}`, {
          description: `Message #${result.message_id} — pipeline processing`,
        })
      }

      // Clear body for next send but keep persona and subject pattern
      setBody("")
    } catch (err) {
      toast.error("Injection failed", {
        description: err instanceof Error ? err.message : "Unknown error",
      })
    } finally {
      setSending(false)
    }
  }

  return (
    <div className="p-4 lg:p-6 max-w-3xl space-y-6">
      <h2 className="text-xl font-semibold text-[#0E2841] flex items-center gap-2">
        <FlaskConical className="h-5 w-5" />
        Dev Area
      </h2>

      {/* Role selector */}
      <div className="flex gap-2">
        {(["customer", "carrier"] as Role[]).map((r) => (
          <button
            key={r}
            onClick={() => { setRole(r); setTemplateId("") }}
            className={cn(
              "px-4 py-2 rounded-lg text-sm font-medium border transition-colors",
              role === r
                ? "bg-[#0E2841] text-white border-[#0E2841]"
                : "bg-white text-muted-foreground border-border hover:bg-muted/50"
            )}
          >
            {r === "customer" ? "Customer" : "Carrier"}
          </button>
        ))}
      </div>

      {/* Persona selector */}
      <div className="space-y-2">
        <label className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
          Send as
        </label>
        <div className="flex flex-wrap gap-2">
          {personas.map((p) => (
            <button
              key={p.id}
              onClick={() => setPersonaId(p.id)}
              className={cn(
                "flex items-center gap-2 px-3 py-2 rounded-lg border text-left transition-colors",
                personaId === p.id
                  ? "border-[#0F9ED5] bg-[#E8F4FC]"
                  : "border-border hover:bg-muted/30"
              )}
            >
              <div>
                <p className="text-sm font-medium">{p.name}</p>
                <p className="text-[10px] text-muted-foreground">{p.company} · {p.email}</p>
              </div>
              <Badge variant="secondary" className={cn("text-[9px]", role === "carrier" ? "bg-purple-100 text-purple-800" : "bg-blue-100 text-blue-800")}>
                {p.role}
              </Badge>
            </button>
          ))}
        </div>
      </div>

      {/* Template selector */}
      <div className="space-y-2">
        <label className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
          Template
        </label>
        <div className="flex flex-wrap gap-2">
          <button
            onClick={() => { setTemplateId(""); setSubject(""); setBody("") }}
            className={cn(
              "px-3 py-1.5 rounded-full text-xs font-medium border transition-colors",
              !templateId
                ? "bg-[#0F9ED5] text-white border-[#0F9ED5]"
                : "bg-white text-muted-foreground border-border hover:bg-muted/50"
            )}
          >
            Custom
          </button>
          {templates.map((t) => (
            <button
              key={t.id}
              onClick={() => applyTemplate(t.id)}
              className={cn(
                "px-3 py-1.5 rounded-full text-xs font-medium border transition-colors",
                templateId === t.id
                  ? "bg-[#0F9ED5] text-white border-[#0F9ED5]"
                  : "bg-white text-muted-foreground border-border hover:bg-muted/50"
              )}
            >
              {t.name}
            </button>
          ))}
        </div>
      </div>

      {/* RFQ # for replies */}
      <div className="space-y-2">
        <label className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
          Replying to RFQ # <span className="font-normal">(optional — adds [RFQ-NN] tag for matching)</span>
        </label>
        <input
          type="text"
          placeholder="e.g., 40"
          value={rfqId}
          onChange={(e) => setRfqId(e.target.value.replace(/\D/g, ""))}
          className="w-32 text-sm border rounded-md px-3 py-2 focus:outline-none focus:ring-2 focus:ring-[#0F9ED5]/30 focus:border-[#0F9ED5]"
        />
      </div>

      {/* Subject */}
      <div className="space-y-2">
        <label className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
          Subject
        </label>
        <input
          type="text"
          value={subject}
          onChange={(e) => setSubject(e.target.value)}
          placeholder="Email subject..."
          className="w-full text-sm border rounded-md px-3 py-2 focus:outline-none focus:ring-2 focus:ring-[#0F9ED5]/30 focus:border-[#0F9ED5]"
        />
      </div>

      {/* Body */}
      <div className="space-y-2">
        <label className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
          Body
        </label>
        <Textarea
          value={body}
          onChange={(e) => setBody(e.target.value)}
          placeholder="Email body... (fill in template placeholders like origin, destination, rate)"
          className="min-h-[160px] text-sm"
        />
      </div>

      {/* Send */}
      <div className="flex items-center gap-3">
        <Button
          onClick={handleSend}
          disabled={!selectedPersona || !subject.trim() || sending}
          className="bg-[#0F9ED5] hover:bg-[#0B7FAD] text-white px-6"
        >
          {sending ? (
            "Injecting..."
          ) : (
            <>
              <Send className="h-4 w-4 mr-2" />
              Send as {selectedPersona?.name ?? "..."}
            </>
          )}
        </Button>
        {selectedPersona && (
          <p className="text-xs text-muted-foreground">
            From: {selectedPersona.name} &lt;{selectedPersona.email}&gt; → full pipeline
          </p>
        )}
      </div>
    </div>
  )
}
