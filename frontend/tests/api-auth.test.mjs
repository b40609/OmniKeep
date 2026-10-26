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

function deferred() {
  let resolve
  const promise = new Promise((done) => { resolve = done })
  return { promise, resolve }
}

test('private requests require a key and use the Authorization header', async () => {
  api.setApiKey('')
  let calls = 0
  globalThis.fetch = async (url, init) => {
    calls++
    assert.equal(url, '/api/items/stats')
    assert.equal(init.headers.Authorization, 'Bearer synthetic-session-a')
    return new Response('{}')
  }
  await assert.rejects(api.getStats(), /請先登入/)
  assert.equal(calls, 0)
  api.setApiKey('synthetic-session-a')
  await api.getStats()
  assert.equal(calls, 1)
})

test('a late 401 cannot sign out a newer login', async () => {
  api.setApiKey('synthetic-session-a')
  const response = deferred()
  globalThis.fetch = () => response.promise
  const pending = api.getStats()
  api.setApiKey('synthetic-session-b')
  let events = 0
  const count = () => events++
  window.addEventListener('omnikeep-auth-required', count)
  try {
    response.resolve(new Response('{}', { status: 401 }))
    await assert.rejects(pending, /登入狀態已變更/)
    assert.equal(events, 0)
    globalThis.fetch = async (url, init) => {
      assert.equal(init.headers.Authorization, 'Bearer synthetic-session-b')
      return new Response('{}')
    }
    await api.getStats()
  } finally {
    window.removeEventListener('omnikeep-auth-required', count)
  }
})

test('a response whose body arrives after logout cannot restore private state', async () => {
  api.setApiKey('synthetic-session-a')
  const body = deferred()
  const reading = deferred()
  globalThis.fetch = async () => ({
    ok: true, status: 200,
    json: () => { reading.resolve(); return body.promise },
  })
  const pending = api.getStats()
  await reading.promise
  api.setApiKey('')
  body.resolve({ total: 123 })
  await assert.rejects(pending, /登入狀態已變更/)
})

test('a current 401 clears credentials and requests login once', async () => {
  api.setApiKey('synthetic-session-a')
  globalThis.fetch = async () => new Response('{"error":"Unauthorized"}', { status: 401 })
  let events = 0
  const count = () => events++
  window.addEventListener('omnikeep-auth-required', count)
  try {
    await assert.rejects(api.getStats(), /Unauthorized/)
    await assert.rejects(api.getStats(), /請先登入/)
    assert.equal(events, 1)
  } finally {
    window.removeEventListener('omnikeep-auth-required', count)
  }
})
