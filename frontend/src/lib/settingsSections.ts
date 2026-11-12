/**
 * The settings page is grouped by what the owner wants to do, not by the module a
 * setting lives in. No runtime imports: the node tests load this file on its own.
 */

export type SettingsSectionId = 'general' | 'channels' | 'ai' | 'notifications' | 'data' | 'advanced' | 'labs'

export interface SettingsSection {
  id: SettingsSectionId
  label: string
  /** One line under the page title. */
  lead: string
}

export const SETTINGS_SECTIONS: SettingsSection[] = [
  { id: 'general', label: '一般', lead: '外觀，以及 AI 分析時參考的背景。' },
  { id: 'channels', label: '收錄管道', lead: '從哪裡把內容送進 OmniKeep，以及讀取時要用的登入。' },
  { id: 'ai', label: 'AI', lead: '分析、提問與搜尋要用哪些 AI 連線。' },
  { id: 'notifications', label: '通知', lead: '哪些裝置會收到通知。' },
  { id: 'data', label: '資料與備份', lead: '備份到哪裡、多久一次，以及把收藏帶走。' },
  { id: 'advanced', label: '進階', lead: '登入方式、金鑰加密與伺服器啟動設定。平常不需要動。' },
  { id: 'labs', label: '實驗功能', lead: '這些功能還在調整，之後可能大改。' },
]

export const DEFAULT_SECTION: SettingsSectionId = 'general'

/**
 * Where an older link lands. Settings links (#settings=telegram) and
 * ui.openSettings('push') used the server's group ids, one tab each.
 * The second value is the block to scroll to inside the section.
 */
const LEGACY_TABS: Record<string, [SettingsSectionId, string]> = {
  ai: ['ai', ''],
  brain: ['ai', 'ask'],
  profile: ['general', 'profile'],
  telegram: ['channels', 'telegram'],
  line: ['channels', 'line'],
  github: ['channels', 'github'],
  backup: ['data', 'backup'],
  push: ['notifications', ''],
  system: ['advanced', ''],
}

export interface SettingsTarget {
  section: SettingsSectionId
  /** Block inside the section to bring into view; '' for the top. */
  block: string
}

/** A section id, an older tab id, or anything else (which opens the first section). */
export function resolveSettingsTarget(tab: string | null | undefined, block = ''): SettingsTarget {
  const id = String(tab ?? '')
  const section = SETTINGS_SECTIONS.find((s) => s.id === id)
  if (section) return { section: section.id, block }
  const legacy = LEGACY_TABS[id]
  if (legacy) return { section: legacy[0], block: block || legacy[1] }
  return { section: DEFAULT_SECTION, block: '' }
}

/** The section a setting is shown in, by the server group it belongs to (for errors on save). */
export function sectionOfGroup(groupId: string): SettingsSectionId {
  return resolveSettingsTarget(groupId).section
}
