/**
 * The one box in the top bar: search, ask, filters and actions. These are the
 * rules for which rows its panel lists and what each key does, kept apart from
 * the component so the node tests can load them. No runtime imports.
 *
 * Search is always the default. A question is asked only when the owner picks
 * the 提問 row or switches the box to ask mode; nothing guesses from the wording.
 */

export type OmniMode = 'search' | 'ask'

/** A filter or an action the panel can list. The component adds an icon and what it runs. */
export interface OmniEntry {
  id: string
  group: 'filter' | 'action'
  label: string
  /** Shown after the label: what kind of filter it is, a count, a shortcut. */
  hint?: string
  /** Other words that find this entry (older names, the shortcut's meaning). */
  keywords?: string[]
  /** Listed only once something is typed, so the empty box stays short enough to take in. */
  quiet?: boolean
}

export type OmniRow<E extends OmniEntry = OmniEntry> =
  | { kind: 'search'; id: 'search'; text: string }
  | { kind: 'ask'; id: 'ask'; text: string }
  | { kind: 'entry'; id: string; entry: E }

export function matchesEntry(entry: OmniEntry, query: string): boolean {
  const q = query.trim().toLowerCase()
  if (!q) return true
  return [entry.label, entry.hint ?? '', ...(entry.keywords ?? [])].some((word) => word.toLowerCase().includes(q))
}

/**
 * Rows of the panel, top to bottom.
 * - empty box: the filters, then the actions (without the ones marked quiet)
 * - typing: 搜尋「…」 first (what Enter does), 提問「…」 second, then what matches
 * - ask mode: 提問「…」 first, 搜尋「…」 as the way back; an empty box lists nothing
 */
export function buildRows<E extends OmniEntry>(text: string, mode: OmniMode, entries: E[]): OmniRow<E>[] {
  const query = text.trim()
  const ordered = [...entries.filter((e) => e.group === 'filter'), ...entries.filter((e) => e.group === 'action')]
  const asRows = (list: E[]): OmniRow<E>[] => list.map((entry) => ({ kind: 'entry', id: entry.id, entry }))
  if (mode === 'ask') {
    return query ? [{ kind: 'ask', id: 'ask', text: query }, { kind: 'search', id: 'search', text: query }] : []
  }
  if (!query) return asRows(ordered.filter((entry) => !entry.quiet))
  return [
    { kind: 'search', id: 'search', text: query },
    { kind: 'ask', id: 'ask', text: query },
    ...asRows(ordered.filter((entry) => matchesEntry(entry, query))),
  ]
}

export interface OmniKey {
  key: string
  ctrlKey?: boolean
  metaKey?: boolean
  shiftKey?: boolean
  altKey?: boolean
}

export type OmniKeyAction =
  | { type: 'move'; index: number }
  | { type: 'run'; index: number }
  | { type: 'ask' }
  | { type: 'leave-ask' }
  | { type: 'close' }

/**
 * What a key pressed in the box does, or null to leave it to the browser.
 * Up and Down wrap around; Enter runs the highlighted row; Tab moves to the
 * 提問 row; Ctrl/Cmd+Enter asks straight away; Backspace on an empty box in ask
 * mode goes back to search; Esc closes.
 */
export function keyAction(event: OmniKey, state: { rows: OmniRow[]; index: number; mode: OmniMode; text: string }): OmniKeyAction | null {
  const { rows, index, mode } = state
  const hasText = !!state.text.trim()
  const command = !!(event.ctrlKey || event.metaKey)
  switch (event.key) {
    case 'ArrowDown':
      return rows.length ? { type: 'move', index: (index + 1) % rows.length } : null
    case 'ArrowUp':
      return rows.length ? { type: 'move', index: (index - 1 + rows.length) % rows.length } : null
    case 'Enter':
      if (command) return hasText ? { type: 'ask' } : null
      return rows[index] ? { type: 'run', index } : null
    case 'Tab': {
      if (event.shiftKey || command || event.altKey || mode !== 'search' || !hasText) return null
      const ask = rows.findIndex((row) => row.kind === 'ask')
      return ask >= 0 && ask !== index ? { type: 'move', index: ask } : null
    }
    case 'Backspace':
      return mode === 'ask' && !state.text ? { type: 'leave-ask' } : null
    case 'Escape':
      return { type: 'close' }
    default:
      return null
  }
}

export interface OmniSection<E extends OmniEntry = OmniEntry> {
  /** '' for the search and ask rows, which need no heading. */
  label: string
  rows: { row: OmniRow<E>; index: number }[]
}

/** Rows under their headings, each keeping its position in the flat list the keys walk. */
export function groupRows<E extends OmniEntry>(rows: OmniRow<E>[]): OmniSection<E>[] {
  const labels = { filter: '篩選', action: '動作' }
  const sections: OmniSection<E>[] = []
  rows.forEach((row, index) => {
    const label = row.kind === 'entry' ? labels[row.entry.group] : ''
    const last = sections[sections.length - 1]
    if (last && last.label === label) last.rows.push({ row, index })
    else sections.push({ label, rows: [{ row, index }] })
  })
  return sections
}
