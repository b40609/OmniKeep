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

test('Interest Profile & Dream Pass API flow', async () => {
  api.setApiKey('test-token-777')
  let requestedUrl = ''
  let requestedMethod = ''
  let requestedBody = null

  // 1. getInterestProfile
  globalThis.fetch = async (url, init) => {
    requestedUrl = url
    requestedMethod = init?.method || 'GET'
    return new Response(JSON.stringify({ success: true, profile: 'AI & Systems', updated_at: '2026-10-26T18:00:00Z' }), { status: 200 })
  }
  const prof = await api.getInterestProfile()
  assert.equal(requestedUrl, '/api/radar/profile')
  assert.equal(requestedMethod, 'GET')
  assert.equal(prof.profile, 'AI & Systems')

  // 2. updateInterestProfile
  globalThis.fetch = async (url, init) => {
    requestedUrl = url
    requestedMethod = init?.method || 'GET'
    requestedBody = JSON.parse(init?.body || '{}')
    return new Response(JSON.stringify({ success: true, profile: requestedBody.profile }), { status: 200 })
  }
  const updated = await api.updateInterestProfile('AI & Rust & Trading')
  assert.equal(requestedUrl, '/api/radar/profile')
  assert.equal(requestedMethod, 'PUT')
  assert.equal(requestedBody.profile, 'AI & Rust & Trading')
  assert.equal(updated.profile, 'AI & Rust & Trading')

  // 3. runDreamPass & applyDreamPass
  globalThis.fetch = async (url, init) => {
    requestedUrl = url
    requestedMethod = init?.method || 'GET'
    if (url.includes('/dreampass/run')) {
      return new Response(JSON.stringify({
        success: true,
        proposal: { id: 10, status: 'pending', observations: 'Observed interest in Rust', suggested_profile: 'Rust focus' },
      }), { status: 200 })
    }
    if (url.includes('/dreampass/10/apply')) {
      return new Response(JSON.stringify({ success: true, message: 'Applied', profile: 'Rust focus' }), { status: 200 })
    }
    return new Response('{}', { status: 200 })
  }

  const runRes = await api.runDreamPass(7)
  assert.equal(requestedUrl, '/api/radar/profile/dreampass/run?days=7')
  assert.equal(runRes.proposal.id, 10)

  const applyRes = await api.applyDreamPass(10)
  assert.equal(requestedUrl, '/api/radar/profile/dreampass/10/apply')
  assert.equal(applyRes.profile, 'Rust focus')
})

test('Hard Rules Engine API flow', async () => {
  api.setApiKey('test-token-777')
  let requestedUrl = ''
  let requestedMethod = ''
  let requestedBody = null

  // 1. getRules
  globalThis.fetch = async (url) => {
    requestedUrl = url
    return new Response(JSON.stringify([
      { id: 1, name: 'GitHub rule', field: 'domain', operator: 'contains', value: 'github.com', action_type: 'add_tag', action_value: 'dev', is_active: 1 },
    ]), { status: 200 })
  }
  const rules = await api.getRules()
  assert.equal(requestedUrl, '/api/rules')
  assert.equal(rules.length, 1)
  assert.equal(rules[0].name, 'GitHub rule')

  // 2. createRule
  globalThis.fetch = async (url, init) => {
    requestedUrl = url
    requestedMethod = init?.method || 'GET'
    requestedBody = JSON.parse(init?.body || '{}')
    return new Response(JSON.stringify({ success: true, rule: { id: 2, ...requestedBody } }), { status: 200 })
  }
  const createRes = await api.createRule({
    name: 'TechCrunch news',
    field: 'domain',
    operator: 'contains',
    value: 'techcrunch.com',
    action_type: 'set_category',
    action_value: '科技新聞',
  })
  assert.equal(requestedUrl, '/api/rules')
  assert.equal(requestedMethod, 'POST')
  assert.equal(createRes.rule.id, 2)
  assert.equal(createRes.rule.name, 'TechCrunch news')

  // 3. testRule
  globalThis.fetch = async (url, init) => {
    requestedUrl = url
    requestedMethod = init?.method || 'GET'
    return new Response(JSON.stringify({
      matched_rules: ['TechCrunch news'],
      changes: { category: { before: '預設', after: '科技新聞' } },
      result_item: { url: 'https://techcrunch.com/article' },
    }), { status: 200 })
  }
  const testRes = await api.testRule({ url: 'https://techcrunch.com/article' })
  assert.equal(requestedUrl, '/api/rules/test')
  assert.equal(testRes.matched_rules[0], 'TechCrunch news')
  assert.equal(testRes.changes.category.after, '科技新聞')
})

test('Bookmark Importer API flow', async () => {
  api.setApiKey('test-token-777')
  let requestedUrl = ''
  let requestedMethod = ''
  let requestedBody = null

  globalThis.fetch = async (url, init) => {
    requestedUrl = url
    requestedMethod = init?.method || 'GET'
    requestedBody = JSON.parse(init?.body || '{}')
    return new Response(JSON.stringify({
      success: true,
      total_parsed: 5,
      imported_count: 5,
      queued_count: 0,
      skipped_count: 0,
      errors: [],
      sample_ids: ['id1', 'id2'],
    }), { status: 200 })
  }

  const res = await api.importBookmarks('<!DOCTYPE NETSCAPE-Bookmark-file-1>...', {
    filename: 'export.html',
    enqueue_ai: false,
    default_category: '科技',
  })

  assert.equal(requestedUrl, '/api/items/import/bookmarks')
  assert.equal(requestedMethod, 'POST')
  assert.equal(requestedBody.filename, 'export.html')
  assert.equal(requestedBody.default_category, '科技')
  assert.equal(res.imported_count, 5)
})
