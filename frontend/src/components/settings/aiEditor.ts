import type { AiSlotId } from '@/lib/api'

/** The form behind 新增連線 and 編輯 in 設定 › AI. */
export interface AiEditor {
  mode: 'new' | 'edit'
  id?: number
  cardId: string
  label: string
  baseUrl: string
  key: string
  clearKey: boolean
  model: string
  minInterval: string
  maxConcurrency: string
  jsonMode: boolean
  /** caps.extra_body as JSON text; '' sends none */
  extraBody: string
  /** the model extraBody was last filled for (a model with a preset fills it again) */
  extraFor: string
  /** Gemini / Vertex thinking level; '' keeps the model's default */
  thinkingLevel: '' | 'low' | 'medium' | 'high'
  slot: AiSlotId | ''
  errors: Record<string, string>
  models: string[]
}
