/**
 * First-run setup wizard: provider presets and the values the wizard saves.
 * Kept free of app imports so tests can run it directly under node.
 */

export type SetupProvider = 'openai_compatible' | 'gemini'
/** required: refuse to continue without one; optional: may be blank; none: field hidden */
export type KeyMode = 'required' | 'optional' | 'none'

export interface SetupPreset {
  id: string
  label: string
  description: string
  provider: SetupProvider
  baseUrl: string
  model: string
  keyMode: KeyMode
  /** Where to create a key, shown next to the field. */
  keyUrl?: string
  /** The address can be edited (self-hosted or "other" servers). */
  editableUrl: boolean
}

export const SETUP_PRESETS: SetupPreset[] = [
  {
    id: 'openai', label: 'OpenAI', description: '最省事，需要付費的 API 金鑰',
    provider: 'openai_compatible', baseUrl: 'https://api.openai.com/v1', model: 'gpt-4o-mini',
    keyMode: 'required', keyUrl: 'https://platform.openai.com/api-keys', editableUrl: false,
  },
  {
    id: 'ollama', label: '本機 Ollama', description: '免費、資料不出這台電腦，需要先安裝 Ollama 並下載模型',
    provider: 'openai_compatible', baseUrl: 'http://127.0.0.1:11434/v1', model: 'qwen3:8b',
    keyMode: 'none', editableUrl: true,
  },
  {
    id: 'gemini', label: 'Google Gemini', description: '有免費額度；影片解析也會用到',
    provider: 'gemini', baseUrl: '', model: 'gemini-2.5-flash',
    keyMode: 'required', keyUrl: 'https://aistudio.google.com/apikey', editableUrl: false,
  },
  {
    id: 'openrouter', label: 'OpenRouter', description: '一把金鑰用多家模型',
    provider: 'openai_compatible', baseUrl: 'https://openrouter.ai/api/v1', model: 'openai/gpt-4o-mini',
    keyMode: 'required', keyUrl: 'https://openrouter.ai/keys', editableUrl: false,
  },
  {
    id: 'deepseek', label: 'DeepSeek', description: '價格低的雲端模型',
    provider: 'openai_compatible', baseUrl: 'https://api.deepseek.com/v1', model: 'deepseek-chat',
    keyMode: 'required', keyUrl: 'https://platform.deepseek.com/api_keys', editableUrl: false,
  },
  {
    id: 'custom', label: '其他 OpenAI 相容服務', description: 'Groq、LM Studio、vLLM、自架閘道…',
    provider: 'openai_compatible', baseUrl: '', model: '',
    keyMode: 'optional', editableUrl: true,
  },
]

export interface SetupForm {
  baseUrl: string
  apiKey: string
  model: string
}

export function presetById(id: string): SetupPreset | undefined {
  return SETUP_PRESETS.find((p) => p.id === id)
}

export function initialForm(preset: SetupPreset): SetupForm {
  return { baseUrl: preset.baseUrl, apiKey: '', model: preset.model }
}

/** Which connection check proves the choice works. */
export function checkServiceFor(preset: SetupPreset): 'llm' | 'gemini' {
  return preset.provider === 'gemini' ? 'gemini' : 'llm'
}

/** What is wrong with the form, or null when it can be tested. */
export function formProblem(preset: SetupPreset, form: SetupForm): string | null {
  if (preset.provider === 'openai_compatible') {
    let url: URL | null = null
    try {
      url = new URL(form.baseUrl.trim())
    } catch {
      url = null
    }
    if (!url || !['http:', 'https:'].includes(url.protocol)) return '請填 http:// 或 https:// 開頭的 API 位址'
  }
  if (preset.keyMode === 'required' && !form.apiKey.trim()) return '請輸入 API 金鑰'
  if (/\s/.test(form.apiKey.trim()) && preset.provider !== 'gemini') return '金鑰中不能有空白'
  if (!form.model.trim()) return '請輸入模型名稱'
  return null
}

/**
 * Settings the wizard tests and then saves. An OpenAI-compatible choice always
 * sends the key, even blank: a blank key means "this server needs none", and it
 * tells the server the old key must not travel to the new address.
 */
export function setupValues(preset: SetupPreset, form: SetupForm): Record<string, string> {
  if (preset.provider === 'gemini') {
    return {
      PRIMARY_LLM_PROVIDER: 'gemini',
      GEMINI_API_KEYS: form.apiKey.trim(),
      GEMINI_MODEL: form.model.trim(),
    }
  }
  return {
    PRIMARY_LLM_PROVIDER: 'openai_compatible',
    OPENAI_BASE_URL: form.baseUrl.trim().replace(/\/+$/, ''),
    OPENAI_API_KEY: preset.keyMode === 'none' ? '' : form.apiKey.trim(),
    PRIMARY_MODEL: form.model.trim(),
  }
}

/** Saving is allowed only after a successful test of exactly these values. */
export function sameValues(a: Record<string, string> | null, b: Record<string, string>): boolean {
  if (!a) return false
  const keys = Object.keys(b)
  return keys.length === Object.keys(a).length && keys.every((k) => a[k] === b[k])
}
