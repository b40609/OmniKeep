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
