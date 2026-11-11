import type { Item } from './api'

/**
 * Pure helpers for the cover wall: which cover is usable, which kind an item
 * is, how the wall is filtered, ordered and split into date sections.
 * No runtime imports, so the node tests can load this file on its own.
 */

/* ---------------- Covers ---------------- */

/** Addresses that only return a site's favicon: too small to stand in for a cover. */
const ICON_ONLY = [
  /^(www\.)?google\.com\/s2\/favicons/i,
  /^[\w.-]*gstatic\.com\/faviconV2/i,
  /^icons\.duckduckgo\.com\/ip\d/i,
  /^[^?#]*\/favicon(-\d+x\d+)?\.(ico|png|svg)([?#]|$)/i,
]

/** The cover address worth loading, or '' when the item has to use the text fallback. */
export function usableCover(url: string | null | undefined): string {
  const value = (url || '').trim()
  const rest = value.replace(/^https?:\/\//i, '')
  if (rest === value || !rest) return ''
  return ICON_ONLY.some((pattern) => pattern.test(rest)) ? '' : value
}

/**
 * How long to wait before asking for a failed cover again, or null to give up.
 * Only for GitHub's generated repository cards: that host answers 429 when a
 * wall asks for several at once and serves the same address a little later.
 * Everything else that fails (expired or blocked addresses) stays failed.
 */
export function coverRetryDelay(url: string, attempt: number): number | null {
  if (!/^https?:\/\/opengraph\.githubassets\.com\//i.test(url)) return null
  return [4_000, 15_000][attempt] ?? null
}

/** A loaded image this small is an icon or a tracking pixel, not a cover. */
export function isIconSized(width: number, height: number): boolean {
  return width < 64 || height < 64
}

/**
 * Which part of a cover stays in view when it fills a 16:9 frame. A screenshot of
 * a post is taller than the frame and starts with who wrote it, so it keeps its
 * top; anything about as wide as the frame, or wider, is cut evenly at the sides.
 */
export function coverFocus(width: number, height: number): 'top' | 'center' {
  return width > 0 && height > 0 && width / height < 1.5 ? 'top' : 'center'
}

/**
 * How a cover is fitted into the frame. Nearly everything fills it and loses a
 * sliver at the edges. GitHub's generated repository cards are the exception:
 * they are 2:1 with the repository name hard against the left margin and the
 * avatar against the right, so filling the frame shaves both. They are always on
 * white, so they are shown whole on a white backing instead: the strip the frame
 * adds above the card is indistinguishable from the card itself.
 */
export function coverFit(url: string): 'fill' | 'pad' {
  return /^https?:\/\/opengraph\.githubassets\.com\//i.test(url) ? 'pad' : 'fill'
}

/* ---------------- Titles ---------------- */

/** Longest name, in characters, that still reads as a name in front of a colon. */
const NAME_LIMIT = 24

/**
 * Saved titles are mostly "name: what it is" in one line. Shown as two levels they
 * scan much faster, so this splits at the first colon that separates the two:
 * a full-width colon, or a half-width one followed by a space or non-ASCII text.
 * Colons inside an address, a time or a ratio do not count, and a title whose
 * part before the colon is longer than a name stays whole.
 */
export function splitTitle(title: string | null | undefined): { name: string; detail: string } {
  const text = (title || '').trim()
  const chars = Array.from(text)
  for (let i = 0; i < chars.length; i++) {
    const colon = chars[i]
    if (colon !== '：' && colon !== ':') continue
    const before = chars[i - 1] ?? ''
    const after = chars[i + 1] ?? ''
    if (/\d/.test(before) && /\d/.test(after)) continue
    if (colon === ':' && !/\s|[^\x00-\x7f]/.test(after)) continue
    // The colon of "https://…", or one inside the same unbroken run as an address.
    let start = i
    while (start > 0 && !/\s/.test(chars[start - 1])) start--
    if (chars.slice(start, i + 3).join('').includes('://')) continue
    const name = chars.slice(0, i).join('').trim()
    const detail = chars.slice(i + 1).join('').trim()
    if (!name || !detail) continue
    if (Array.from(name).length > NAME_LIMIT) break
    return { name, detail }
  }
  return { name: text, detail: '' }
}

/* ---------------- Kinds ---------------- */

export type ItemKind = 'project' | 'post' | 'video' | 'article'
export type KindFilter = 'all' | ItemKind

export const KIND_LABELS: Record<ItemKind, string> = {
  project: '專案',
  post: '貼文',
  video: '影片',
  article: '文章',
}

export const KIND_TABS: { id: KindFilter; label: string }[] = [
  { id: 'all', label: '全部' },
  { id: 'project', label: KIND_LABELS.project },
  { id: 'post', label: KIND_LABELS.post },
  { id: 'video', label: KIND_LABELS.video },
  { id: 'article', label: KIND_LABELS.article },
]

const VIDEO_SOURCES = ['youtube', 'bilibili', 'reel', 'tiktok', 'video']
const POST_SOURCES = ['threads', 'instagram', 'facebook', 'twitter', 'x', 'social']
const VIDEO_HOSTS = ['youtube.com', 'youtu.be', 'bilibili.com', 'b23.tv', 'tiktok.com', 'vimeo.com']
const POST_HOSTS = ['threads.net', 'threads.com', 'x.com', 'twitter.com', 'facebook.com', 'fb.com', 'instagram.com', 'linkedin.com', 'bsky.app']

const BRANDS: Record<string, string> = {
  'github.com': 'GitHub',
  'threads.net': 'Threads',
  'threads.com': 'Threads',
  'facebook.com': 'Facebook',
  'fb.com': 'Facebook',
  'instagram.com': 'Instagram',
  'youtube.com': 'YouTube',
  'youtu.be': 'YouTube',
  'bilibili.com': 'Bilibili',
  'b23.tv': 'Bilibili',
  'tiktok.com': 'TikTok',
  'x.com': 'X',
  'twitter.com': 'X',
}

function hostOf(url: string | null | undefined): string {
  try {
    const parsed = new URL(url || '')
    return /^https?:$/.test(parsed.protocol) ? parsed.hostname.toLowerCase().replace(/^(www|m|mobile)\./, '') : ''
  } catch {
    return ''
  }
}

/** The listed site this host is, or is a subdomain of (`music.youtube.com` is YouTube). */
function siteOf(host: string, sites: string[]): string {
  return sites.find((site) => host === site || host.endsWith('.' + site)) || ''
}

type Kindable = Pick<Item, 'url' | 'source_type'>

/** Every item is exactly one kind; "project" means a github.com address. */
export function itemKind(item: Kindable): ItemKind {
  const source = String(item.source_type || '').toLowerCase()
  const host = hostOf(item.url)
  if (host === 'github.com' || (!host && source === 'github')) return 'project'
  if (VIDEO_SOURCES.includes(source) || siteOf(host, VIDEO_HOSTS)) return 'video'
  if (POST_SOURCES.includes(source) || siteOf(host, POST_HOSTS)) return 'post'
  return 'article'
}

/** Name shown on the text fallback when an item has no cover: "Facebook 貼文", or the site's host. */
export function sourceName(item: Kindable): string {
  const host = hostOf(item.url)
  if (!host) return '筆記'
  const brand = BRANDS[siteOf(host, Object.keys(BRANDS))]
  return brand ? `${brand} ${KIND_LABELS[itemKind(item)]}` : host
}

/* ---------------- Order ---------------- */

/** `server` keeps the order the API returned: newest first, or by relevance for a search. */
export type WallOrder = 'server' | 'oldest'

/** Stored without a zone, the server's timestamps are UTC. */
export function parseServerTime(value: string | null | undefined): Date | null {
  if (!value) return null
  const normalized = value.includes('T') ? value : value.replace(' ', 'T')
  const date = new Date(/Z|[+-]\d\d:?\d\d$/.test(normalized) ? normalized : normalized + 'Z')
  return Number.isNaN(date.getTime()) ? null : date
}

/** The loaded items a wall shows: one kind (or all), in the chosen order. Never mutates its input. */
export function arrangeItems<T extends Kindable & { created_at: string }>(items: T[], kind: KindFilter, order: WallOrder): T[] {
  const shown = kind === 'all' ? items.slice() : items.filter((item) => itemKind(item) === kind)
  if (order !== 'oldest') return shown
  const time = (item: T) => parseServerTime(item.created_at)?.getTime() ?? 0
  return shown.map((item, index) => ({ item, index })).sort((a, b) => time(a.item) - time(b.item) || a.index - b.index).map((entry) => entry.item)
}

/* ---------------- Date sections ---------------- */

export interface WallSection<T> {
  key: string
  label: string
  items: T[]
}

/**
 * Section an item falls in, by the local day it was saved: today, yesterday,
 * one per day for the rest of the week, then one per month so a long backlog
 * stays a handful of headings instead of hundreds.
 */
export function daySection(createdAt: string | null | undefined, now: Date): { key: string; label: string } {
  const date = parseServerTime(createdAt)
  if (!date) return { key: 'unknown', label: '更早' }
  const midnight = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime()
  const days = Math.round((midnight(now) - midnight(date)) / 86_400_000)
  if (days <= 0) return { key: 'd0', label: '今天' }
  if (days === 1) return { key: 'd1', label: '昨天' }
  if (days < 7) return { key: `d${days}`, label: `${days} 天前` }
  const year = date.getFullYear()
  const month = date.getMonth() + 1
  return { key: `m${year}-${month}`, label: `${year} 年 ${month} 月` }
}

/** Sections in the order their first item appears; an item never lands in two. */
export function groupByDay<T extends { created_at: string }>(items: T[], now: Date = new Date()): WallSection<T>[] {
  const sections = new Map<string, WallSection<T>>()
  for (const item of items) {
    const { key, label } = daySection(item.created_at, now)
    const section = sections.get(key)
    if (section) section.items.push(item)
    else sections.set(key, { key, label, items: [item] })
  }
  return [...sections.values()]
}
