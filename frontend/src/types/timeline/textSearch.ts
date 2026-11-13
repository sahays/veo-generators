export interface TextPart {
  text: string
  match: boolean
}

/** Trimmed, lower-cased query; empty means "no search". */
export function normalizeQuery(query: string): string {
  return query.trim().toLowerCase()
}

/** Case-insensitive "contains" over several optional fields. An empty query matches everything. */
export function matchesQuery(query: string, ...fields: (string | undefined)[]): boolean {
  const needle = normalizeQuery(query)
  if (!needle) return true
  return fields.some((field) => field !== undefined && field.toLowerCase().includes(needle))
}

/**
 * Split `text` into matching and non-matching parts for highlighting.
 * The query is matched literally (no pattern syntax), case-insensitively.
 */
export function splitHighlight(text: string, query: string): TextPart[] {
  const needle = normalizeQuery(query)
  if (!needle) return text ? [{ text, match: false }] : []
  const haystack = text.toLowerCase()
  const parts: TextPart[] = []
  let cursor = 0
  for (let hit = haystack.indexOf(needle); hit !== -1; hit = haystack.indexOf(needle, cursor)) {
    if (hit > cursor) parts.push({ text: text.slice(cursor, hit), match: false })
    parts.push({ text: text.slice(hit, hit + needle.length), match: true })
    cursor = hit + needle.length
  }
  if (cursor < text.length) parts.push({ text: text.slice(cursor), match: false })
  return parts
}
