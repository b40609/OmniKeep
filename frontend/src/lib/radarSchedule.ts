/**
 * What the background radar is actually doing, worded for the settings panel.
 * Reads the saved settings (not unsaved edits). Free of app imports for tests.
 */
import type { RadarSettings, RadarSource } from './api'

export interface ScheduleNote {
  tone: 'ok' | 'off' | 'warn'
  text: string
}

function every(minutes: number): string {
  return minutes % 60 === 0 ? `${minutes / 60} 小時` : `${minutes} 分鐘`
}

export function radarScheduleNote(saved: RadarSettings | null, sources: RadarSource[]): ScheduleNote | null {
  if (!saved) return null
  if (saved.scheduler_running === false) {
    return { tone: 'warn', text: '伺服器的背景服務沒有啟動（BACKGROUND_SERVICES_ENABLED=false），這個開關目前不會生效。' }
  }
  if (!saved.enabled) return { tone: 'off', text: '目前：關閉，只在按「立即檢查」時檢查。' }
  if (!saved.interval_minutes) return { tone: 'off', text: '目前：開啟，但週期是「手動檢查」，不會自動檢查。' }
  const active = sources.filter((source) => Boolean(source.is_active)).length
  if (!active) return { tone: 'warn', text: '目前：開啟，但沒有啟用中的來源，檢查不會抓到新內容。' }
  return { tone: 'ok', text: `目前：開啟，每 ${every(saved.interval_minutes)}檢查 ${active} 個來源。` }
}
