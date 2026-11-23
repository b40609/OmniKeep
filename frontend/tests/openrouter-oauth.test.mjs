import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import ts from 'typescript'

const source = await readFile(new URL('../src/lib/openrouterOAuth.ts', import.meta.url), 'utf8')
const { outputText } = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
})
const mod = await import(`data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`)

function memoryStorage() {
  const map = new Map()
  return {
    getItem: (k) => (map.has(k) ? map.get(k) : null),
    setItem: (k, v) => map.set(k, String(v)),
    removeItem: (k) => map.delete(k),
  }
}

test('callbackUrlFromLocation keeps only origin and pathname', () => {
  assert.equal(mod.callbackUrlFromLocation({ origin: 'http://localhost:5000', pathname: '/' }), 'http://localhost:5000/')
  assert.equal(mod.callbackUrlFromLocation({ origin: 'http://127.0.0.1:5173/', pathname: '/app/' }), 'http://127.0.0.1:5173/app/')
  assert.equal(mod.callbackUrlFromLocation({ origin: 'https://keep.example.com', pathname: '' }), 'https://keep.example.com/')
})

test('readOpenRouterCallback extracts code and preserves unrelated query params', () => {
  assert.equal(mod.readOpenRouterCallback(''), null)
  assert.equal(mod.readOpenRouterCallback('?open=proposals'), null)
  assert.deepEqual(mod.readOpenRouterCallback('?code=abc123'), { code: 'abc123', cleanedSearch: '' })
  assert.deepEqual(mod.readOpenRouterCallback('?foo=1&code=abc123&bar=2'), {
    code: 'abc123',
    cleanedSearch: '?foo=1&bar=2',
  })
})

test('pending OAuth state is one-time and expires after TTL', () => {
  const store = memoryStorage()
  const t0 = 1_800_000_000_000
  const item = {
    state: 'state_token_1',
    createdAt: t0,
    source: 'settings',
    mode: 'new',
    label: 'OpenRouter',
    model: 'google/gemma-4-31b-it:free',
    slot: 'analysis',
  }
  mod.savePendingOpenRouterOAuth(store, item)

  assert.deepEqual(mod.takePendingOpenRouterOAuth(store, t0 + 1000), item)
  // Second read gets null (already consumed).
  assert.equal(mod.takePendingOpenRouterOAuth(store, t0 + 2000), null)

  // Expired state is rejected and cleared.
  mod.savePendingOpenRouterOAuth(store, item)
  assert.equal(mod.takePendingOpenRouterOAuth(store, t0 + mod.OPENROUTER_OAUTH_TTL_MS + 1), null)
  assert.equal(store.getItem(mod.OPENROUTER_OAUTH_STORAGE_KEY), null)
})
