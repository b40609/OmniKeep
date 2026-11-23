import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import ts from 'typescript'

async function load(path) {
  const source = await readFile(new URL(`../src/${path}`, import.meta.url), 'utf8')
  const { outputText } = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
  })
  return import(`data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`)
}

const evalUi = await load('lib/evalUi.ts')
const api = await load('lib/api.ts')
globalThis.window = new EventTarget()

test('resolveBadgeUi distinguishes static skill pass, executable review, and risk flagged', () => {
  const pass = evalUi.resolveBadgeUi('skill_scan_pass')
  assert.equal(pass.tone, 'green')
  assert.match(pass.label, /靜態掃描通過/)

  const exec = evalUi.resolveBadgeUi('executable_needs_review')
  assert.equal(exec.tone, 'amber')
  assert.match(exec.label, /可執行/)

  const risk = evalUi.resolveBadgeUi('risk_flagged')
  assert.equal(risk.tone, 'red')
  assert.match(risk.label, /風險/)

  // Unknown defaults cautiously to executable_needs_review, never green pass.
  assert.equal(evalUi.resolveBadgeUi(''), exec)
})

test('suggestedTriggerWhen prefers existing trigger, then scenario, then user note', () => {
  assert.equal(evalUi.suggestedTriggerWhen({ trigger_when: '自訂條件' }), '自訂條件')
  assert.equal(
    evalUi.suggestedTriggerWhen({ l1: { scenarios: ['大批 PDF 解析太慢'] }, user_note: '其他' }),
    '大批 PDF 解析太慢',
  )
  assert.match(evalUi.suggestedTriggerWhen({ user_note: '想替換搜尋步驟' }), /想替換搜尋步驟/)
})

test('evaluation API client helpers hit expected endpoints with Authorization header', async () => {
  api.setApiKey('eval-key')
  const calls = []
  globalThis.fetch = async (url, init) => {
    calls.push({
      url,
      method: init?.method || 'GET',
      headers: init?.headers || {},
      body: init?.body ? JSON.parse(init.body) : null,
    })
    return new Response(JSON.stringify({ success: true, evaluations: [], counts: {} }), { status: 200 })
  }

  await api.listEvaluations('needs_decision', 20)
  await api.getEvaluation('eval_123')
  await api.triggerItemEvaluation('item_1', { user_note: 'check speed', sync: true })
  await api.decideEvaluation('eval_123', { decision: 'on_demand', trigger_when: 'heavy pdf' })

  assert.equal(calls[0].url, '/api/evaluations?status=needs_decision&limit=20')
  assert.equal(calls[0].headers.Authorization, 'Bearer eval-key')
  assert.equal(calls[1].url, '/api/evaluations/eval_123')
  assert.equal(calls[2].url, '/api/items/item_1/evaluate')
  assert.equal(calls[2].method, 'POST')
  assert.deepEqual(calls[2].body, { user_note: 'check speed', sync: true })
  assert.equal(calls[3].url, '/api/evaluations/eval_123/decide')
  assert.deepEqual(calls[3].body, { decision: 'on_demand', trigger_when: 'heavy pdf' })
})

test('PWA manifest declares share_target for Android installation', async () => {
  const raw = await readFile(new URL('../../static/manifest.json', import.meta.url), 'utf8')
  const manifest = JSON.parse(raw)
  assert.equal(manifest.share_target?.method, 'GET')
  assert.equal(manifest.share_target?.params?.url, 'url')
})
