/**
 * The 一鍵隨手存書籤 bookmarklet and the query it opens OmniKeep with. Kept free
 * of app imports so tests can run the bookmarklet and read its query directly.
 */

export function bookmarkletHref(origin: string): string {
  return `javascript:(function(){const u=encodeURIComponent(window.location.href);const t=encodeURIComponent(document.querySelector('title')?.textContent||document.querySelector("meta[property='og:title']")?.getAttribute('content')||'');const d=encodeURIComponent(document.querySelector("meta[name='description']")?.getAttribute('content')||document.querySelector("meta[property='og:description']")?.getAttribute('content')||'');window.open('${origin}/?url='+u+'&title='+t+'&description='+d+'&auto_close=1','_blank','width=520,height=620');})();`
}

export interface ClipRequest {
  url: string
  /** Title and description as the clipped page showed them in the user's browser. */
  title: string
  description: string
  autoClose: boolean
}

export function readClipRequest(search: string): ClipRequest | null {
  const params = new URLSearchParams(search)
  const url = params.get('url')
  if (!url) return null
  return {
    url,
    title: params.get('title')?.trim() ?? '',
    description: params.get('description')?.trim() ?? '',
    autoClose: params.get('auto_close') === '1' || params.has('auto_close'),
  }
}
