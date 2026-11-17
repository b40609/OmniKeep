/**
 * Tells an open tab that a newer build is live. The page is a single-page app, so a tab opened before a
 * deploy keeps running the old code until it is reloaded (2026-11-17: a fixed diagram bug "came back"
 * because the tab still ran the build from before the fix). The check reads the page shell again and
 * compares the entry script it names with the one this tab loaded.
 */

const ENTRY = /<script[^>]+type="module"[^>]+src="([^"]*\/assets\/index-[^"]+\.js)"/

/** The entry script a page shell (index.html) loads, or '' when it names none. */
export function entryOf(html: string): string {
  return html.match(ENTRY)?.[1] || ''
}

/** The entry script this tab is running. */
export function runningEntry(doc: Document = document): string {
  const s = doc.querySelector<HTMLScriptElement>('script[type="module"][src*="/assets/index-"]')
  return s ? new URL(s.getAttribute('src') || '', location.href).pathname : ''
}

const EVERY = 5 * 60 * 1000, MIN_GAP = 60 * 1000

/** Check now and then (and when the tab comes back to the front); call `onNew` once when a new build is live. */
export function watchForUpdates(onNew: () => void): () => void {
  const mine = runningEntry()
  if (!mine) return () => {} // dev server: no built entry to compare
  let last = 0, told = false
  const check = async () => {
    if (told || Date.now() - last < MIN_GAP) return
    last = Date.now()
    try {
      const r = await fetch('/', { cache: 'no-store', credentials: 'same-origin' })
      if (!r.ok) return
      const live = entryOf(await r.text())
      if (live && new URL(live, location.href).pathname !== mine) { told = true; onNew() }
    } catch { /* offline or restarting: try again later */ }
  }
  const onVis = () => { if (document.visibilityState === 'visible') void check() }
  const timer = window.setInterval(() => void check(), EVERY)
  document.addEventListener('visibilitychange', onVis)
  window.addEventListener('focus', onVis)
  return () => { clearInterval(timer); document.removeEventListener('visibilitychange', onVis); window.removeEventListener('focus', onVis) }
}
