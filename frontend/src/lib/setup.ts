/**
 * Provider cards (GET /api/ai/catalog, app/provider_catalog.py) turned into the
 * connection the first-run wizard and 設定 › AI test and save.
 * Kept free of app imports so tests can run it directly under node.
 */

export type CardKind = 'openai' | 'gemini' | 'ollama'
/** required: refuse to continue without one; optional: may be blank; none: field hidden */
export type KeyMode = 'required' | 'optional' | 'none'

/** The fields of a catalog card this module needs. */
export interface SetupCard {
  id: string
  label: string
  kind: CardKind
  base_url: string
  model: string
  models?: string[]
  key_mode: KeyMode
  key_url?: string
  editable_url?: boolean
  /** usable with no account at all */
  no_signup?: boolean
  /** a limited-time free offer that is over */
  ended?: boolean
}

/**
 * The cards the first-run guide lists before "顯示全部": the ones a newcomer can start with
 * right away, judged from the card's own fields only. Either the service needs no account
 * (`no_signup`) or the card takes no key at all (a local Ollama). An offer that has ended is
 * not one of them.
 */
export function isStarterCard(card: SetupCard): boolean {
  return !card.ended && (card.no_signup === true || card.key_mode === 'none')
}

export interface SetupForm {
  baseUrl: string
  apiKey: string
  model: string
}

/** What is tested and then saved as a connection (POST /api/ai/test, /api/ai/connections). */
export interface ConnectionDraft {
  card: string
  base_url?: string
  key?: string
  model: string
}

export function cardById<T extends SetupCard>(cards: T[], id: string): T | undefined {
  return cards.find((c) => c.id === id)
}

export function initialForm(card: SetupCard): SetupForm {
  return { baseUrl: card.base_url, apiKey: '', model: card.model }
}

/** The address has a part the owner must fill in, e.g. Cloudflare's <帳號 ID>. */
export function hasPlaceholder(url: string): boolean {
  return /[<>]/.test(url)
}

/** What is wrong with the form, or null when it can be tested. */
export function formProblem(card: SetupCard, form: SetupForm): string | null {
  if (card.kind !== 'gemini') {
    const raw = form.baseUrl.trim()
    if (hasPlaceholder(raw)) return '把 API 位址裡角括號的部分（例如 <帳號 ID>）換成你自己的值'
    let url: URL | null = null
    try {
      url = new URL(raw)
    } catch {
      url = null
    }
    if (!url || !['http:', 'https:'].includes(url.protocol)) return '請填 http:// 或 https:// 開頭的 API 位址'
  }
  if (card.key_mode === 'required' && !form.apiKey.trim()) return '請輸入 API 金鑰'
  if (/\s/.test(form.apiKey.trim()) && card.kind !== 'gemini') return '金鑰中不能有空白'
  if (!form.model.trim()) return '請輸入模型名稱'
  return null
}

/**
 * The connection to test and save. A card that takes no key never sends one,
 * so a key typed earlier for another card cannot follow it to a new address.
 */
export function connectionDraft(card: SetupCard, form: SetupForm): ConnectionDraft {
  const draft: ConnectionDraft = { card: card.id, model: form.model.trim() }
  if (card.kind !== 'gemini') draft.base_url = form.baseUrl.trim().replace(/\/+$/, '')
  if (card.key_mode !== 'none') {
    draft.key = card.kind === 'gemini'
      ? form.apiKey.split(',').map((k) => k.trim()).filter(Boolean).join(',')
      : form.apiKey.trim()
  }
  return draft
}

/** Saving is allowed only after a successful test of exactly these values. */
export function sameValues(a: object | null, b: object): boolean {
  if (!a) return false
  const left = a as Record<string, unknown>
  const right = b as Record<string, unknown>
  const keys = Object.keys(right)
  return keys.length === Object.keys(left).length && keys.every((k) => left[k] === right[k])
}

/** Seconds as a short Chinese duration for cooldowns. */
export function formatCooldown(seconds: number): string {
  if (seconds <= 0) return ''
  if (seconds < 60) return `${seconds} 秒`
  return `${Math.ceil(seconds / 60)} 分鐘`
}
