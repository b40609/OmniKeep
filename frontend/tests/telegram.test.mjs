import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import ts from 'typescript'

const source = await readFile(new URL('../src/lib/api.ts', import.meta.url), 'utf8')
const { outputText } = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
})
const api = await import(`data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`)
globalThis.window = new EventTarget()

function captureFetch(responseBody, status = 200) {
  const calls = []
  globalThis.fetch = async (url, init) => {
    calls.push({ url, method: init?.method || 'GET', headers: init?.headers || {} })
    return new Response(JSON.stringify(responseBody), { status })
  }
  return calls
}

test('getTelegramStatus reads the binding state with Bearer auth', async () => {
  api.setApiKey('tg-token')
  const calls = captureFetch({ configured: true, bound_user_ids: [2222], pairing_expires_at: null })
  const status = await api.getTelegramStatus()
  assert.equal(calls[0].url, '/api/telegram/status')
  assert.equal(calls[0].method, 'GET')
  assert.equal(calls[0].headers.Authorization, 'Bearer tg-token')
  assert.deepEqual(status.bound_user_ids, [2222])
})

test('createTelegramPairing asks the server for a one-time t.me link', async () => {
  api.setApiKey('tg-token')
  const calls = captureFetch({ link: 'https://t.me/omnikeep_bot?start=abc_DEF-123', expires_at: 1793760000 })
  const pairing = await api.createTelegramPairing()
  assert.equal(calls[0].url, '/api/telegram/pairing')
  assert.equal(calls[0].method, 'POST')
  assert.equal(pairing.link, 'https://t.me/omnikeep_bot?start=abc_DEF-123')
})

test('a server without a bot token surfaces its 503 detail', async () => {
  api.setApiKey('tg-token')
  captureFetch({ detail: 'TELEGRAM_BOT_TOKEN is not configured' }, 503)
  await assert.rejects(api.createTelegramPairing(), /TELEGRAM_BOT_TOKEN is not configured/)
})
