/**
 * Experimental features are off until switched on in 設定 › 實驗功能. The switches are
 * settings on the server (so every device agrees); a server from before they existed
 * simply has none, which reads as off. No runtime imports: the node tests load this file.
 */

export type ExperimentId = 'radar' | 'watch' | 'daily'

export interface Experiment {
  id: ExperimentId
  /** Setting key on the server (app/app_settings.py, group "labs"). */
  key: string
  label: string
  /** What it does and what is still missing. */
  description: string
  /** What switching it off does not stop. */
  background: string
}

export const EXPERIMENTS: Experiment[] = [
  {
    id: 'radar',
    key: 'EXPERIMENT_RADAR',
    label: '探索',
    description: '依你設定的探索來源定期找新內容，放進「探索」清單讓你逐則篩選。評分和精選的品質還在調整。',
    background: '這個開關只決定介面上看不看得到。背景檢查由探索自己的「啟用」決定：開著的話，關掉這裡仍會繼續抓內容、用 AI 額度。',
  },
  {
    id: 'watch',
    key: 'EXPERIMENT_WATCH',
    label: '專案監看',
    description: '掃描你指定的本機專案資料夾，拿新收藏和專案比對，提出可以用在專案上的建議。建議的準確度還不穩定。',
    background: '這個開關只決定介面上看不看得到。已加入的專案仍在：探索抓到新內容時，還是會和它們比對並產生建議。',
  },
  {
    id: 'daily',
    key: 'EXPERIMENT_DAILY_REVIEW',
    label: '每日回顧',
    description: '每天挑幾則未讀和值得重看的舊收藏，一則一則看過。挑選方式還在調整。',
    background: '沒有背景工作，關掉就不會執行。',
  },
]

export type ExperimentFlags = Record<ExperimentId, boolean>

export const NO_EXPERIMENTS: ExperimentFlags = { radar: false, watch: false, daily: false }

interface FieldLike {
  key: string
  value?: unknown
}
interface GroupLike {
  fields: FieldLike[]
}

/** Which experiments are on, from the settings the server describes. Missing means off. */
export function readExperiments(groups: GroupLike[] | null | undefined): ExperimentFlags {
  const flags: ExperimentFlags = { ...NO_EXPERIMENTS }
  for (const group of groups ?? []) {
    for (const field of group.fields ?? []) {
      const experiment = EXPERIMENTS.find((e) => e.key === field.key)
      if (experiment) flags[experiment.id] = field.value === true
    }
  }
  return flags
}

/** False for a server from before the switches existed: they cannot be turned on there. */
export function experimentsSupported(groups: GroupLike[] | null | undefined): boolean {
  const keys = new Set((groups ?? []).flatMap((g) => (g.fields ?? []).map((f) => f.key)))
  return EXPERIMENTS.every((e) => keys.has(e.key))
}

/** Categories the project watcher files its own records under (app/watch), not ones the owner made. */
export const WATCH_CATEGORIES = ['監看', '提案']

/** Single-key shortcuts that belong to an experiment and do nothing while it is off. */
export const EXPERIMENT_SHORTCUTS: Record<string, ExperimentId> = { r: 'radar', R: 'radar', d: 'radar', D: 'daily' }

/** The experiment a shortcut key belongs to and that is switched off; null when the key may run. */
export function blockedShortcut(key: string, flags: ExperimentFlags): ExperimentId | null {
  const experiment = EXPERIMENT_SHORTCUTS[key]
  return experiment && !flags[experiment] ? experiment : null
}
