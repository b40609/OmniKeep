export type SecurityBadgeCode = 'skill_scan_pass' | 'executable_needs_review' | 'risk_flagged'

export interface BadgeUiMeta {
  code: SecurityBadgeCode
  tone: 'green' | 'amber' | 'red'
  label: string
  detail: string
  pillClass: string
}

export const SECURITY_BADGES: Record<SecurityBadgeCode, BadgeUiMeta> = {
  skill_scan_pass: {
    code: 'skill_scan_pass',
    tone: 'green',
    label: 'Skill 靜態掃描通過',
    detail: '已檢查靜態 Skill 規格，未發現高危規則或可執行安裝腳本。',
    pillClass: 'border-emerald-500/40 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300',
  },
  executable_needs_review: {
    code: 'executable_needs_review',
    tone: 'amber',
    label: '含可執行 CLI／MCP，需隔離檢視',
    detail: '含可執行程式碼、套件設定或缺少 SKILL.md，靜態掃描無法涵蓋執行期行為，請於 L2 沙盒檢視。',
    pillClass: 'border-amber-500/40 bg-amber-500/10 text-amber-700 dark:text-amber-300',
  },
  risk_flagged: {
    code: 'risk_flagged',
    tone: 'red',
    label: '掃出風險項目',
    detail: '靜態檢查發現高風險指令或安全疑慮，建議先檢視風險明細再決定。',
    pillClass: 'border-red-500/40 bg-red-500/10 text-red-700 dark:text-red-300',
  },
}

export function resolveBadgeUi(code?: string | null): BadgeUiMeta {
  if (code === 'skill_scan_pass' || code === 'risk_flagged' || code === 'executable_needs_review') {
    return SECURITY_BADGES[code]
  }
  return SECURITY_BADGES.executable_needs_review
}

export const REJECT_REASONS: readonly string[] = [
  '現任工具已夠用',
  '依賴與維護成本過高',
  '僅包裝／行銷成分居多',
  '安全疑慮不符合需求',
]

export const AGENT_STATUS_LABELS: Record<string, string> = {
  none: '未評估',
  queued: '排隊預研中',
  evaluating: '背景預研中',
  needs_decision: '待拍板',
  approved_l2: '待桌機 L2 實測',
  adopted: '已採納使用',
  on_demand: '情境備案（0 token 常駐）',
  rejected: '已拒絕',
  eval_failed: '評估未完成',
}

export const EVAL_FILTER_TABS: ReadonlyArray<{ id: string; label: string }> = [
  { id: 'needs_decision', label: '待拍板' },
  { id: 'evaluating', label: '預研中' },
  { id: 'approved_l2', label: '待 L2 實測' },
  { id: 'on_demand', label: '情境備案' },
  { id: 'rejected', label: '已拒絕' },
]

export function suggestedTriggerWhen(ev: {
  trigger_when?: string | null
  user_note?: string | null
  l1?: { scenarios?: string[]; slots?: string[]; summary?: string } | null
}): string {
  const existing = (ev.trigger_when || '').trim()
  if (existing) return existing
  const scenarios = ev.l1?.scenarios || []
  if (scenarios.length && scenarios[0]?.trim()) return scenarios[0].trim()
  if (ev.user_note?.trim()) return `遇到「${ev.user_note.trim().slice(0, 60)}」情境時啟用`
  const slots = ev.l1?.slots || []
  if (slots.length && slots[0]?.trim()) return `現任 ${slots[0].trim()} 流程需要替代方案時`
  return '遇到相關專案 bottleneck 或特定檔案類型再按需調用'
}
