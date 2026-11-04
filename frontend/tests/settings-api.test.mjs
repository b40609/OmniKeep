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
    calls.push({ url, method: init?.method || 'GET', headers: init?.headers || {}, body: init?.body })
    return new Response(JSON.stringify(responseBody), { status })
  }
  return calls
}

test('getSettings reads the settings page with Bearer auth', async () => {
  api.setApiKey('settings-token')
  const calls = captureFetch({ groups: [], secret_key: {}, env_importable: [], bootstrap: [] })
  await api.getSettings()
  assert.equal(calls[0].url, '/api/settings')
  assert.equal(calls[0].method, 'GET')
  assert.equal(calls[0].headers.Authorization, 'Bearer settings-token')
})

test('saveSettings sends values and resets in one PUT', async () => {
  api.setApiKey('settings-token')
  const calls = captureFetch({ groups: [], changed: ['OPENAI_API_KEY'] })
  await api.saveSettings({ OPENAI_API_KEY: 'sk-typed', LLM_MAX_CONCURRENCY: 3 }, ['PRIMARY_MODEL'])
  assert.equal(calls[0].url, '/api/settings')
  assert.equal(calls[0].method, 'PUT')
  assert.deepEqual(JSON.parse(calls[0].body), {
    values: { OPENAI_API_KEY: 'sk-typed', LLM_MAX_CONCURRENCY: 3 },
    reset: ['PRIMARY_MODEL'],
  })
})

test('a refused save exposes the per-field errors', async () => {
  api.setApiKey('settings-token')
  captureFetch({ detail: '更換 API 位址時，請一併重新輸入 API 金鑰', errors: { OPENAI_API_KEY: '更換 API 位址時，請一併重新輸入 API 金鑰' } }, 400)
  await assert.rejects(api.saveSettings({ OPENAI_BASE_URL: 'https://elsewhere.example/v1' }), (error) => {
    assert.match(error.message, /重新輸入 API 金鑰/)
    assert.deepEqual(Object.keys(error.fieldErrors), ['OPENAI_API_KEY'])
    return true
  })
})

test('checkConnection posts the unsaved values to the service check', async () => {
  api.setApiKey('settings-token')
  const calls = captureFetch({ ok: false, status: 401, message: '金鑰無效、已停用，或沒有這項權限', detail: '' })
  const result = await api.checkConnection('embeddings', { OPENAI_API_KEY: 'sk-typed' })
  assert.equal(calls[0].url, '/api/settings/check/embeddings')
  assert.equal(calls[0].method, 'POST')
  assert.deepEqual(JSON.parse(calls[0].body), { values: { OPENAI_API_KEY: 'sk-typed' } })
  assert.equal(result.status, 401)
})

test('import and status use their own endpoints', async () => {
  api.setApiKey('settings-token')
  let calls = captureFetch({ groups: [], imported: ['GITHUB_TOKEN'] })
  await api.importEnvSettings()
  assert.deepEqual([calls[0].url, calls[0].method], ['/api/settings/import-env', 'POST'])
  calls = captureFetch({ services: {}, needs_setup: false, undecryptable: [] })
  await api.getServiceStatus()
  assert.deepEqual([calls[0].url, calls[0].method], ['/api/settings/status', 'GET'])
})
