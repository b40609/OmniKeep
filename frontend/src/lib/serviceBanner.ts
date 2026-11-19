import type { ServiceOutcome, ServiceStatus } from './api'

export interface ServiceBannerProblem {
  /** Concise single-line message shown inside the top alert bar. */
  text: string
  /** Full detail (including every failing connection name) shown in tooltip. */
  detail: string
  action: string
  tab: 'ai' | 'push-keys' | 'wizard'
}

const LEGACY_LABELS: Record<string, string> = {
  llm: 'AI 分析',
  embeddings: '雲端向量',
  gemini: 'Gemini',
  ollama: '本機 Ollama 向量',
}

function connectionLabel(name: string, outcome: ServiceOutcome): string {
  return outcome.label || LEGACY_LABELS[name] || name
}

/**
 * Turns /api/service-status into a single actionable top-bar alert.
 * When 3+ connections fail at once, collapse the list into a count so the
 * actual error reason is never pushed off-screen by connection names.
 */
export function summarizeServiceStatus(status: ServiceStatus | null): ServiceBannerProblem | null {
  if (!status) return null

  const unreadable = (status.undecryptable || []).filter((k) => !k.startsWith('VAPID_'))
  if (unreadable.length) {
    const connections = unreadable.filter((k) => k.startsWith('ai_connection:')).length
    const where =
      connections === unreadable.length
        ? '請到「設定 › AI」重新輸入那幾條連線的金鑰。'
        : '目前改用 .env 的值，請到設定重新輸入。'
    const text = `有 ${unreadable.length} 個金鑰無法解密（主金鑰和當初加密時不同），${where}`
    return { text, detail: text, action: '重新輸入', tab: 'ai' }
  }

  if ((status.undecryptable || []).length) {
    const text = '推播金鑰無法解密（主金鑰和當初加密時不同），推播暫停。請還原主金鑰檔，或到設定重新產生。'
    return { text, detail: text, action: '查看', tab: 'push-keys' }
  }

  const services = status.services || {}
  const failing = Object.entries(services).filter(([, o]) => o && !o.ok)
  if (failing.length) {
    // A key that needs a person goes first: retrying will not fix it.
    failing.sort(([, a], [, b]) => Number(!!b.action_required) - Number(!!a.action_required))
    const [name, outcome] = failing[0]
    const topLabel = connectionLabel(name, outcome)
    const reason = outcome.hint || outcome.message || (outcome.status ? `HTTP ${outcome.status}` : '連線失敗')
    const allNames = failing.map(([n, o]) => connectionLabel(n, o)).join('、')
    const backup = failing.length < Object.keys(services).length ? '其他連線仍可備援。' : ''

    const text =
      failing.length <= 2
        ? `${allNames} 目前無法使用（${topLabel}：${reason}）。${backup}`
        : `有 ${failing.length} 條 AI 連線暫時無法使用（${topLabel}：${reason}）。${backup}`
    const detail = failing.length <= 2 ? text : `${text}受影響連線：${allNames}`

    return {
      text,
      detail,
      action: outcome.action_required ? '前往處理' : '檢查設定',
      tab: 'ai',
    }
  }

  if (status.needs_setup) {
    const text = '還沒有接上 AI。新收藏會先存下來，標成「尚未分析」，接上後補分析。'
    return { text, detail: text, action: '開始設定', tab: 'wizard' }
  }

  return null
}
