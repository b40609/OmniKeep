import assert from 'node:assert/strict'
import { readdir, readFile } from 'node:fs/promises'
import test from 'node:test'
import ts from 'typescript'

const source = await readFile(new URL('../src/lib/api.ts', import.meta.url), 'utf8')
const { outputText } = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
})
const api = await import(`data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`)
globalThis.window = new EventTarget()

function serveFile(body, headers = {}, status = 200) {
  const calls = []
  globalThis.fetch = async (url, init) => {
    calls.push({ url, headers: init?.headers || {} })
    return new Response(body, { status, headers })
  }
  return calls
}

test('exportItems downloads with the in-memory key, not a remembered one', async () => {
  // Without "記住金鑰" the key lives only in memory; node has no localStorage to fall back on.
  assert.equal(typeof globalThis.localStorage, 'undefined')
  api.setApiKey('memory-only-key')
  const calls = serveFile('{"items":[]}', { 'Content-Disposition': 'attachment; filename="omnikeep_export_20261104.json"' })

  const file = await api.exportItems('json', true)

  assert.equal(calls[0].url, '/api/items/export?format=json&starred_only=true')
  assert.equal(calls[0].headers.Authorization, 'Bearer memory-only-key')
  assert.equal(file.filename, 'omnikeep_export_20261104.json')
  assert.equal(await file.blob.text(), '{"items":[]}')
})

test('exportItems falls back to a default name and keeps binary bodies intact', async () => {
  api.setApiKey('memory-only-key')
  const zip = Uint8Array.from([0x50, 0x4b, 0x03, 0x04, 0xff, 0x00])
  serveFile(zip)
  const file = await api.exportItems('markdown', false)
  assert.equal(file.filename, 'omnikeep_markdown.zip')
  assert.deepEqual(new Uint8Array(await file.blob.arrayBuffer()), zip)
})

test('an expired key during export asks for login like every other request', async () => {
  api.setApiKey('expired-key')
  serveFile(JSON.stringify({ detail: 'Invalid or missing API key' }), {}, 401)
  let asked = 0
  const ask = () => asked++
  window.addEventListener('omnikeep-auth-required', ask)
  try {
    await assert.rejects(api.exportItems('json', false), /Invalid or missing API key/)
    assert.equal(asked, 1)
  } finally {
    window.removeEventListener('omnikeep-auth-required', ask)
  }
  await assert.rejects(api.exportItems('json', false), /請先登入/)
})

test('only App.vue touches the remembered API key', async () => {
  const offenders = []
  async function walk(dir) {
    for (const entry of await readdir(dir, { withFileTypes: true })) {
      const url = new URL(entry.name + (entry.isDirectory() ? '/' : ''), dir)
      if (entry.isDirectory()) await walk(url)
      else if (/\.(vue|ts)$/.test(entry.name) && entry.name !== 'App.vue'
        && (await readFile(url, 'utf8')).includes('omnikeep_api_key')) offenders.push(entry.name)
    }
  }
  await walk(new URL('../src/', import.meta.url))
  assert.deepEqual(offenders, [])
})
