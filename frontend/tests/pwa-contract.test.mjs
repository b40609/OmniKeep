import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

// 2026-11-17: the built worker routed navigations to a precached index.html that was no longer precached,
// so it threw on start and never installed. Guard the config, and the build when one is present.
test('the worker config does not fall back to a page it does not precache', async () => {
  const cfg = await readFile(new URL('../vite.config.ts', import.meta.url), 'utf8')
  assert.match(cfg, /navigateFallback:\s*null/)
  assert.doesNotMatch(cfg, /globPatterns:[^\n]*index\.html/)
})

test('a built worker only binds navigations to precached pages', async (t) => {
  let sw
  try { sw = await readFile(new URL('../../static/dist/sw.js', import.meta.url), 'utf8') } catch { t.skip('no build here'); return }
  for (const m of sw.matchAll(/createHandlerBoundToURL\("([^"]+)"\)/g)) {
    assert.match(sw, new RegExp(`url:"${m[1].replace('.', '\.')}"`), `${m[1]} is routed to but not precached`)
  }
})

test('iOS standalone PWA pushes top chrome past the system status-bar blur veil', async () => {
  const html = await readFile(new URL('../index.html', import.meta.url), 'utf8')
  assert.doesNotMatch(html, /apple-mobile-web-app-status-bar-style"\s+content="black-translucent"/)
  const css = await readFile(new URL('../src/assets/main.css', import.meta.url), 'utf8')
  assert.match(css, /@supports\s*\(-webkit-touch-callout:\s*none\)/)
  assert.match(css, /@media\s*\(display-mode:\s*standalone\)/)
  assert.match(css, /--safe-top:\s*calc\(max\(0px,\s*env\(safe-area-inset-top\)\)\s*\+\s*18px\)/)
})
