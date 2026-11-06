/**
 * 設定 › AI 服務商: the "額外請求參數" field of a connection (caps.extra_body).
 *
 * The field holds JSON text. A card can carry per-model presets (model_extra_body, e.g.
 * NVIDIA's DeepSeek needs its reasoning switched off); picking such a model fills the field,
 * and picking another puts back the card's default, unless the text was changed by hand.
 * The server checks the same rules again (app/ai_connections.py _extra_body).
 */

type Body = Record<string, unknown>

interface CardLike {
  caps?: { extra_body?: Body }
  model_extra_body?: Record<string, Body>
}

/** Request fields OmniKeep sets itself (app/ai_connections.py _RESERVED_BODY). */
const RESERVED = ['model', 'messages', 'stream', 'response_format', 'tools', 'tool_choice', 'n']

const isObject = (v: unknown): v is Body => typeof v === 'object' && v !== null && !Array.isArray(v)

export function formatExtraBody(value: Body | undefined | null): string {
  return value && Object.keys(value).length ? JSON.stringify(value) : ''
}

export type ParsedExtraBody = { ok: true; value: Body } | { ok: false; error: string }

/** '' (or only spaces) means no extra fields. */
export function parseExtraBody(text: string): ParsedExtraBody {
  const trimmed = text.trim()
  if (!trimmed) return { ok: true, value: {} }
  let value: unknown
  try {
    value = JSON.parse(trimmed)
  } catch {
    return { ok: false, error: '額外請求參數要是 JSON 物件，例如 {"reasoning": {"effort": "low"}}' }
  }
  if (!isObject(value)) return { ok: false, error: '額外請求參數要是 JSON 物件（大括號包起來）' }
  const reserved = RESERVED.filter((k) => k in value)
  if (reserved.length) return { ok: false, error: `額外請求參數不能改 ${reserved.join('、')}` }
  if (JSON.stringify(value).length > 2000) return { ok: false, error: '額外請求參數太長（上限 2000 字元）' }
  return { ok: true, value }
}

/** What the field holds for `model` when nobody typed in it: the model's preset, else the card's default. */
export function autoExtraBody(card: CardLike | undefined, model: string): Body {
  const preset = card?.model_extra_body?.[model.trim()]
  return { ...(preset ?? card?.caps?.extra_body ?? {}) }
}

const same = (a: Body, b: Body) => JSON.stringify(a) === JSON.stringify(b)

/** The field's text after the model changes from `prevModel` to `nextModel`. */
export function extraBodyAfterModelChange(card: CardLike | undefined, prevModel: string, nextModel: string, text: string): string {
  const parsed = parseExtraBody(text)
  if (!parsed.ok || !same(parsed.value, autoExtraBody(card, prevModel))) return text
  return formatExtraBody(autoExtraBody(card, nextModel))
}
