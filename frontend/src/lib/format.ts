import type { SourceType } from './api'

/** Extract a clean hostname from an item URL, with friendly labels for notes/snippets. */
export function cleanHost(url: string | null | undefined): string {
  if (!url) return ''
  if (url.startsWith('note://')) return '筆記片段'
  if (url.includes('#snippet-')) {
    try {
      return new URL(url).hostname.replace(/^www\./, '') + ' (引文)'
    } catch {
      return '技術段落'
    }
  }
  try {
    return new URL(url).hostname.replace(/^www\./, '')
  } catch {
    return '筆記片段'
  }
}

/** Compact relative time in zh-TW. */
export function formatRelativeTime(timeStr: string | null | undefined): string {
  if (!timeStr) return ''
  const normalized = timeStr.includes('T') ? timeStr : timeStr.replace(' ', 'T')
  const d = new Date(normalized.includes('Z') || normalized.includes('+') ? normalized : normalized + 'Z')
  const diffSec = Math.floor((Date.now() - d.getTime()) / 1000)
  if (diffSec < 60) return '剛才'
  if (diffSec < 3600) return `${Math.floor(diffSec / 60)} 分鐘前`
  if (diffSec < 86400) return `${Math.floor(diffSec / 3600)} 小時前`
  if (diffSec < 2592000) return `${Math.floor(diffSec / 86400)} 天前`
  return `${d.getMonth() + 1}月${d.getDate()}日`
}

/** Estimated reading time in minutes for long-form content. */
export function estimateReadTime(text: string | null | undefined): number {
  if (!text) return 0
  // CJK chars ≈ 400/min, latin words ≈ 200/min
  const cjk = (text.match(/[\u4e00-\u9fff\u3400-\u4dbf]/g) || []).length
  const latinWords = text.replace(/[\u4e00-\u9fff\u3400-\u4dbf]/g, ' ').split(/\s+/).filter(Boolean).length
  return Math.max(1, Math.round(cjk / 400 + latinWords / 220))
}

export type SourceVariant = 'youtube' | 'github' | 'note' | 'rss' | 'web'

export interface SourceMeta {
  variant: SourceVariant
  label: string
  /** Tailwind classes for the source badge — theme-aware. */
  badgeClass: string
}

/** Source badge registry — iOS tinted pill style. */
export function sourceMeta(source: SourceType | null | undefined): SourceMeta {
  switch ((source || '').toLowerCase()) {
    case 'youtube':
      return {
        variant: 'youtube',
        label: 'YouTube',
        badgeClass: 'bg-danger-soft text-danger',
      }
    case 'github':
      return {
        variant: 'github',
        label: 'GitHub',
        badgeClass: 'bg-purple-soft text-purple',
      }
    case 'note':
    case 'snippet':
      return {
        variant: 'note',
        label: '筆記',
        badgeClass: 'bg-success-soft text-success',
      }
    case 'rss':
      return {
        variant: 'rss',
        label: 'RSS',
        badgeClass: 'bg-warning-soft text-warning',
      }
    case 'reel':
      return {
        variant: 'note',
        label: 'Reel',
        badgeClass: 'bg-info-soft text-info',
      }
    case 'google_news':
      return {
        variant: 'rss',
        label: 'Google新聞',
        badgeClass: 'bg-sky-500/10 text-sky-600 dark:text-sky-400',
      }
    case 'web_change':
      return {
        variant: 'web',
        label: '網頁監控',
        badgeClass: 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400',
      }
    default:
      return {
        variant: 'web',
        label: (source || 'WEB').toString().toUpperCase(),
        badgeClass: 'bg-primary-soft text-primary',
      }
  }
}
