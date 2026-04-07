/**
 * lib/export.ts — CSV export utility (#108).
 *
 * Generates a CSV file from an array of objects and triggers a browser
 * download. Used by the RFQs page and dashboard export buttons.
 */

/**
 * Export an array of objects to a CSV file and trigger a browser download.
 *
 * @param data - Array of row objects
 * @param columns - Column definitions: { key, label } pairs
 * @param filename - Download filename (without extension)
 */
export function exportToCsv<T extends Record<string, unknown>>(
  data: T[],
  columns: { key: keyof T; label: string }[],
  filename: string
) {
  if (data.length === 0) return

  /* Build CSV header row */
  const header = columns.map((c) => escapeCsvField(c.label)).join(",")

  /* Build CSV data rows */
  const rows = data.map((row) =>
    columns
      .map((c) => {
        const value = row[c.key]
        return escapeCsvField(value == null ? "" : String(value))
      })
      .join(",")
  )

  const csv = [header, ...rows].join("\n")

  /* Trigger browser download */
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" })
  const url = URL.createObjectURL(blob)
  const link = document.createElement("a")
  link.href = url
  link.download = `${filename}.csv`
  link.click()
  URL.revokeObjectURL(url)
}

/** Escape a CSV field value — wrap in quotes if it contains commas, quotes, or newlines. */
function escapeCsvField(value: string): string {
  if (value.includes(",") || value.includes('"') || value.includes("\n")) {
    return `"${value.replace(/"/g, '""')}"`
  }
  return value
}
