/** The web page an item was kept from, and how the reader gets back to it. */
export type OriginBrand = 'github' | 'youtube' | 'x'

export interface OriginLink {
  /** The kept address, opened in a new tab. */
  href: string
  /** Shown beside the icon: the host without www. */
  host: string
  brand: OriginBrand | null
  /** Text of the main button under the title. */
  action: string
  /** The site's own icon, for sources without a brand logo; may not exist (show a globe then). */
  favicon: string
}

const BRAND_SITES: Record<OriginBrand, string[]> = {
  github: ['github.com'],
  youtube: ['youtube.com', 'youtu.be'],
  x: ['x.com', 'twitter.com'],
}
const ACTIONS: Record<OriginBrand, string> = {
  github: '在 GitHub 開啟',
  youtube: '在 YouTube 觀看',
  x: '在 X 查看',
}

/** True when the address is a web page the browser can open (not a note:// or other app-only address). */
export function isWebUrl(url: string | null | undefined): boolean {
  return originLink(url) !== null
}

/** null for notes and anything that is not an http(s) address: there is no page to go back to. */
export function originLink(url: string | null | undefined): OriginLink | null {
  let parsed: URL
  try {
    parsed = new URL(url || '')
  } catch {
    return null
  }
  if (!/^https?:$/.test(parsed.protocol) || !parsed.hostname) return null
  const host = parsed.hostname.toLowerCase().replace(/^www\./, '')
  const bare = host.replace(/^(m|mobile|music)\./, '')
  const brand = (Object.keys(BRAND_SITES) as OriginBrand[])
    .find((b) => BRAND_SITES[b].some((site) => bare === site || bare.endsWith('.' + site))) ?? null
  return {
    href: parsed.href,
    host,
    brand,
    action: brand ? ACTIONS[brand] : '開啟原網頁',
    favicon: `${parsed.origin}/favicon.ico`,
  }
}
