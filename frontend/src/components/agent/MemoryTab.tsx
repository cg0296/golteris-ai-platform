/**
 * components/agent/MemoryTab.tsx — Agent memory view (#40).
 *
 * Shows what the agents have learned: facts about customers, preferences
 * from approved drafts, lane patterns, and pricing rules.
 */

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Brain, BookOpen, TrendingUp, Users } from "lucide-react"

export function MemoryTab() {
  const memoryCategories = [
    {
      icon: Users,
      title: "Customer Preferences",
      description: "Contact preferences, communication style, past interactions",
      count: 0,
      color: "text-blue-500 bg-blue-50",
    },
    {
      icon: TrendingUp,
      title: "Lane Patterns",
      description: "Frequently quoted routes, seasonal patterns, typical rates",
      count: 0,
      color: "text-green-500 bg-green-50",
    },
    {
      icon: BookOpen,
      title: "Approved Draft Patterns",
      description: "Language and formatting from broker-approved drafts",
      count: 0,
      color: "text-purple-500 bg-purple-50",
    },
    {
      icon: Brain,
      title: "Pricing Rules",
      description: "Per-customer markup preferences, minimum margins, special terms",
      count: 0,
      color: "text-amber-500 bg-amber-50",
    },
  ]

  return (
    <div className="space-y-4">
      <p className="text-sm text-muted-foreground">
        What the agents have learned from processing quotes and broker feedback.
        Memory builds over time as more quotes are processed.
      </p>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {memoryCategories.map((cat) => (
          <Card key={cat.title} className="shadow-sm">
            <CardHeader className="pb-2">
              <CardTitle className="text-sm flex items-center gap-2">
                <div className={`p-1.5 rounded ${cat.color.split(" ")[1]}`}>
                  <cat.icon className={`h-4 w-4 ${cat.color.split(" ")[0]}`} />
                </div>
                {cat.title}
              </CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-xs text-muted-foreground">{cat.description}</p>
              <p className="text-xs text-muted-foreground mt-2 italic">
                {cat.count === 0 ? "No memories yet — will populate as quotes are processed" : `${cat.count} entries`}
              </p>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  )
}
