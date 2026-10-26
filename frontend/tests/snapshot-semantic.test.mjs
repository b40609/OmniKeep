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

test('searchSemantic requests /api/items/search/semantic with Bearer token', async () => {
  api.setApiKey('test-key-xyz')
  let requestedUrl = ''
  let requestedHeaders = null

  globalThis.fetch = async (url, init) => {
    requestedUrl = url
    requestedHeaders = init?.headers
    return new Response(JSON.stringify([{ id: 42, title_l1: '向量檢索測試' }]), { status: 200 })
  }

  const items = await api.searchSemantic('sqlite-vec 引擎', 15)
  assert.equal(requestedUrl, '/api/items/search/semantic?q=sqlite-vec+%E5%BC%95%E6%93%8E&limit=15')
  assert.equal(requestedHeaders.Authorization, 'Bearer test-key-xyz')
  assert.equal(items.length, 1)
  assert.equal(items[0].id, 42)
})

test('getSnapshotStatus queries status endpoint', async () => {
  api.setApiKey('test-key-xyz')
  let requestedUrl = ''
  globalThis.fetch = async (url) => {
    requestedUrl = url
    return new Response(JSON.stringify({ available: true, item_id: '99', size_bytes: 4096 }), { status: 200 })
  }

  const status = await api.getSnapshotStatus(99)
  assert.equal(requestedUrl, '/api/items/99/snapshot/status')
  assert.equal(status.available, true)
  assert.equal(status.size_bytes, 4096)
})

test('fetchSnapshotHtml gets raw HTML and handles 404 gracefully', async () => {
  api.setApiKey('test-key-xyz')
  
  // Success case
  globalThis.fetch = async (url) => {
    assert.equal(url, '/api/items/101/snapshot')
    return new Response('<!DOCTYPE html><html><body>Snapshot Content</body></html>', { status: 200 })
  }
  const html = await api.fetchSnapshotHtml(101)
  assert.ok(html.includes('Snapshot Content'))

  // 404 not found case
  globalThis.fetch = async () => new Response('{"detail":"Not found"}', { status: 404 })
  await assert.rejects(api.fetchSnapshotHtml(999), /此項目尚未建立離線快照/)
})
