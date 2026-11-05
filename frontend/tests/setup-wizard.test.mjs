import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import ts from 'typescript'
import { parse, compileScript } from '@vue/compiler-sfc'
import { createRenderer, h, nextTick, reactive } from 'vue'

const moduleUrl = (code) => `data:text/javascript;base64,${Buffer.from(code).toString('base64')}`
const transpile = (source) => ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
}).outputText

const setupSource = transpile(await readFile(new URL('../src/lib/setup.ts', import.meta.url), 'utf8'))
const setup = await import(moduleUrl(setupSource))

// The shape GET /api/ai/catalog returns (app/provider_catalog.py), trimmed to what the wizard reads.
const CARDS = [
  { id: 'agnes', label: 'Agnes', kind: 'openai', base_url: 'https://apihub.agnes-ai.com/v1', model: 'agnes-3.0-flash',
    models: ['agnes-3.0-flash'], key_mode: 'required', key_url: 'https://platform.agnes-ai.com/settings/apiKeys',
    editable_url: false, cost: '免費', limits: '每分鐘約 10 次', notes: '', training_note: '', verified: '2026-11-05' },
  { id: 'gemini', label: 'Google Gemini', kind: 'gemini', base_url: '', model: 'gemini-2.5-flash', models: [],
    key_mode: 'required', key_url: 'https://aistudio.google.com/apikey', editable_url: false, cost: '免費層',
    limits: '', notes: '', training_note: '免費層的內容會被拿去改進產品。', verified: '2026-11-05' },
  { id: 'ollama', label: '本機 Ollama', kind: 'ollama', base_url: 'http://127.0.0.1:11434', model: 'qwen3:8b', models: [],
    key_mode: 'none', key_url: '', editable_url: true, cost: '0', limits: '', notes: '', training_note: '', verified: '2026-11-05' },
  { id: 'cloudflare', label: 'Cloudflare', kind: 'openai',
    base_url: 'https://api.cloudflare.com/client/v4/accounts/<帳號 ID>/ai/v1', model: '@cf/openai/gpt-oss-120b', models: [],
    key_mode: 'required', key_url: 'https://dash.cloudflare.com/profile/api-tokens', editable_url: true, cost: '免費層',
    limits: '', notes: '', training_note: '', verified: '2026-11-05' },
  { id: 'custom', label: '自訂 OpenAI 相容端點', kind: 'openai', base_url: '', model: '', models: [],
    key_mode: 'optional', key_url: '', editable_url: true, cost: '', limits: '', notes: '', training_note: '', verified: '2026-11-05' },
]
const card = (id) => setup.cardById(CARDS, id)

// ── Pure logic ────────────────────────────────────────────────────

test('a card becomes a connection draft: address, key and model, trimmed', () => {
  const draft = setup.connectionDraft(card('agnes'), {
    baseUrl: ' https://apihub.agnes-ai.com/v1/ ', apiKey: ' sk-typed ', model: ' agnes-3.0-flash ',
  })
  assert.deepEqual(draft, { card: 'agnes', base_url: 'https://apihub.agnes-ai.com/v1', key: 'sk-typed', model: 'agnes-3.0-flash' })
})

test('a card that takes no key never sends one, so no old key follows it', () => {
  const draft = setup.connectionDraft(card('ollama'), { ...setup.initialForm(card('ollama')), apiKey: 'left-over' })
  assert.equal('key' in draft, false)
  assert.equal(draft.base_url, 'http://127.0.0.1:11434')
  assert.equal(setup.formProblem(card('ollama'), setup.initialForm(card('ollama'))), null)
})

test('Gemini sends its keys without an address', () => {
  const draft = setup.connectionDraft(card('gemini'), { baseUrl: 'x', apiKey: 'AIzaOne, AIzaTwo', model: 'gemini-2.5-flash' })
  assert.deepEqual(draft, { card: 'gemini', key: 'AIzaOne,AIzaTwo', model: 'gemini-2.5-flash' })
  assert.equal(setup.formProblem(card('gemini'), { baseUrl: '', apiKey: 'AIzaOne, AIzaTwo', model: 'm' }), null)
})

test('the form explains what is missing before a test is allowed', () => {
  const agnes = card('agnes')
  assert.match(setup.formProblem(agnes, setup.initialForm(agnes)), /金鑰/)
  assert.match(setup.formProblem(agnes, { ...setup.initialForm(agnes), apiKey: 'sk a' }), /空白/)
  assert.match(setup.formProblem(agnes, { ...setup.initialForm(agnes), apiKey: 'sk-a', model: ' ' }), /模型/)
  const cf = card('cloudflare')
  assert.match(setup.formProblem(cf, { ...setup.initialForm(cf), apiKey: 't' }), /帳號 ID/)
  const custom = card('custom')
  assert.match(setup.formProblem(custom, setup.initialForm(custom)), /API 位址/)
  assert.match(setup.formProblem(custom, { baseUrl: 'ftp://x.example/v1', apiKey: '', model: 'm' }), /API 位址/)
  assert.equal(setup.formProblem(custom, { baseUrl: 'http://192.168.1.5:1234/v1', apiKey: '', model: 'm' }), null)
})

test('sameValues compares exactly what would be saved', () => {
  const a = { A: '1', B: '2' }
  assert.equal(setup.sameValues(null, a), false)
  assert.equal(setup.sameValues({ ...a }, a), true)
  assert.equal(setup.sameValues({ A: '1', B: '3' }, a), false)
  assert.equal(setup.sameValues({ A: '1' }, a), false)
})

test('cooldowns read as short Chinese durations', () => {
  assert.equal(setup.formatCooldown(0), '')
  assert.equal(setup.formatCooldown(42), '42 秒')
  assert.equal(setup.formatCooldown(90), '2 分鐘')
})

// ── The wizard component, with the real setup.ts and a fake API ─────

const renderer = createRenderer({
  createElement: () => ({}), createText: () => ({}), createComment: () => ({}),
  insert() {}, remove() {}, setText() {}, setComment() {}, setElementText() {},
  patchProp() {}, parentNode: () => null, nextSibling: () => null,
})
let moduleId = 0

async function loadComponent(path) {
  const raw = await readFile(new URL(`../src/${path}`, import.meta.url), 'utf8')
  let outputText = transpile(compileScript(parse(raw).descriptor, { id: path }).content)
  const parsed = ts.createSourceFile('c.js', outputText, ts.ScriptTarget.ES2022, true)
  for (const statement of parsed.statements) {
    if (!ts.isImportDeclaration(statement)) continue
    const specifier = statement.moduleSpecifier.text
    let url
    if (specifier === 'vue') url = import.meta.resolve('vue')
    else if (specifier === '@/lib/setup') url = moduleUrl(setupSource)
    else {
      const mocks = []
      if (statement.importClause?.name) mocks.push('export default {}')
      const bindings = statement.importClause?.namedBindings
      const names = bindings && ts.isNamedImports(bindings) ? bindings.elements.map((b) => (b.propertyName || b.name).text) : []
      for (const name of names) {
        let value = '{}'
        if (specifier.endsWith('/api')) value = `(...args) => globalThis.__wizard.api.${name}(...args)`
        else if (name === 'useUiStore') value = '() => globalThis.__wizard.ui'
        else if (name === 'toast') value = '({ success() {}, error: (...a) => globalThis.__wizard.errors.push(a) })'
        mocks.push(`export const ${name} = ${value}`)
      }
      url = moduleUrl(mocks.join('\n'))
    }
    outputText = outputText.replace(statement.moduleSpecifier.getText(parsed), JSON.stringify(url))
  }
  return (await import(moduleUrl(`${outputText}\n// wizard ${++moduleId}`))).default
}

function context(status = { services: {}, needs_setup: true, undecryptable: [] }) {
  const store = new Map()
  globalThis.sessionStorage = { getItem: (k) => store.get(k) ?? null, setItem: (k, v) => store.set(k, v) }
  globalThis.window = new EventTarget()
  const ctx = {
    ui: reactive({ showSetupWizard: false, showSettingsModal: false, settingsVersion: 0, openSettings(tab) { ctx.opened = tab } }),
    api: {
      getServiceStatus: async () => status,
      getAiCatalog: async () => ({ verified: '2026-11-05', cards: CARDS }),
      testAiDraft: async (draft) => { ctx.tests.push(draft); return ctx.nextTest },
      createAiConnection: async (input) => { ctx.created.push(input); return {} },
    },
    tests: [], created: [], errors: [], nextTest: { ok: true, status: 200, message: 'ok', detail: '' }, store,
  }
  globalThis.__wizard = ctx
  return ctx
}

async function mountWizard() {
  const component = await loadComponent('components/modals/SetupWizard.vue')
  const vnode = h({ ...component, render: () => null })
  const container = {}
  renderer.render(vnode, container)
  await new Promise((resolve) => setTimeout(resolve, 0))
  await nextTick()
  return { state: vnode.component.setupState, unmount: () => renderer.render(null, container) }
}

const settle = () => new Promise((resolve) => setTimeout(resolve, 0))

test('opens by itself only while no provider is usable, with nothing preselected', async () => {
  let ctx = context()
  let view = await mountWizard()
  assert.equal(ctx.ui.showSetupWizard, true)
  await settle()
  assert.equal(view.state.cardId, '') // the owner chooses; no default answer
  assert.equal(view.state.cards.length, CARDS.length)
  view.unmount()

  ctx = context({ services: {}, needs_setup: false, undecryptable: [] })
  view = await mountWizard()
  assert.equal(ctx.ui.showSetupWizard, false)
  view.unmount()

  ctx = context({ services: {}, needs_setup: true, undecryptable: ['OPENAI_API_KEY'] })
  view = await mountWizard()
  assert.equal(ctx.ui.showSetupWizard, false) // the banner explains an unreadable key instead
  view.unmount()
})

test('"later" keeps it closed for this browser session', async () => {
  const ctx = context()
  let view = await mountWizard()
  view.state.later()
  assert.equal(ctx.ui.showSetupWizard, false)
  view.unmount()
  view = await mountWizard()
  assert.equal(ctx.ui.showSetupWizard, false)
  view.unmount()
})

test('saving needs a successful test of exactly the values being saved, then fills the analysis slot', async () => {
  const ctx = context()
  const view = await mountWizard()
  try {
    await settle()
    const s = view.state
    s.choose('agnes')
    s.step = 'connect'
    assert.match(s.problem, /金鑰/)
    s.form.apiKey = 'sk-wizard-typed'
    await nextTick()
    assert.equal(s.canSave, false)

    ctx.nextTest = { ok: false, status: 401, message: '金鑰被停用', detail: '' }
    await s.test()
    assert.equal(s.canSave, false)

    ctx.nextTest = { ok: true, status: 200, message: '連線成功', detail: '', models: ['agnes-3.0-flash', 'agnes-3.5-flash'] }
    await s.test()
    assert.deepEqual(ctx.tests.at(-1), {
      card: 'agnes', base_url: 'https://apihub.agnes-ai.com/v1', key: 'sk-wizard-typed', model: 'agnes-3.0-flash',
    })
    assert.equal(s.canSave, true)
    assert.deepEqual(s.modelChoices, ['agnes-3.0-flash', 'agnes-3.5-flash'])

    s.form.model = 'agnes-3.5-flash'
    await nextTick()
    assert.equal(s.canSave, false) // edited after the test
    assert.equal(s.result, null)
    await s.test()
    await s.save()
    assert.deepEqual(ctx.created, [{
      card: 'agnes', base_url: 'https://apihub.agnes-ai.com/v1', key: 'sk-wizard-typed', model: 'agnes-3.5-flash',
      slot: 'analysis',
    }])
    assert.equal(s.step, 'done')
    assert.equal(s.form.apiKey, '') // the key does not linger in the page
    assert.equal(ctx.ui.settingsVersion, 1)
  } finally { view.unmount() }
})

test('a Gemini card is tested without an address', async () => {
  const ctx = context()
  const view = await mountWizard()
  try {
    await settle()
    view.state.choose('gemini')
    view.state.form.apiKey = 'AIzaWizard'
    await view.state.test()
    assert.deepEqual(ctx.tests.at(-1), { card: 'gemini', key: 'AIzaWizard', model: 'gemini-2.5-flash' })
  } finally { view.unmount() }
})
