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
const preset = (id) => setup.presetById(id)

// ── Pure logic ────────────────────────────────────────────────────

test('every preset is complete and ids are unique', () => {
  const ids = setup.SETUP_PRESETS.map((p) => p.id)
  assert.equal(new Set(ids).size, ids.length)
  for (const p of setup.SETUP_PRESETS) {
    assert.ok(p.label && p.description)
    assert.ok(['openai_compatible', 'gemini'].includes(p.provider))
    if (p.provider === 'openai_compatible' && p.baseUrl) assert.match(p.baseUrl, /^https?:\/\/.+\/v1$/)
    if (p.keyUrl) assert.match(p.keyUrl, /^https:\/\//)
  }
})

test('an OpenAI-compatible choice saves address, key and model, trimming the address', () => {
  const values = setup.setupValues(preset('openrouter'), {
    baseUrl: ' https://openrouter.ai/api/v1/ ', apiKey: ' sk-or-typed ', model: ' openai/gpt-4o-mini ',
  })
  assert.deepEqual(values, {
    PRIMARY_LLM_PROVIDER: 'openai_compatible',
    OPENAI_BASE_URL: 'https://openrouter.ai/api/v1',
    OPENAI_API_KEY: 'sk-or-typed',
    PRIMARY_MODEL: 'openai/gpt-4o-mini',
  })
  assert.equal(setup.checkServiceFor(preset('openrouter')), 'llm')
})

test('a local Ollama choice always sends an empty key, so no old key follows it', () => {
  const values = setup.setupValues(preset('ollama'), { ...setup.initialForm(preset('ollama')), apiKey: 'left-over' })
  assert.equal(values.OPENAI_API_KEY, '')
  assert.equal(values.OPENAI_BASE_URL, 'http://127.0.0.1:11434/v1')
  assert.equal(setup.formProblem(preset('ollama'), setup.initialForm(preset('ollama'))), null)
})

test('a Gemini choice saves only Gemini settings and is checked as Gemini', () => {
  const values = setup.setupValues(preset('gemini'), { baseUrl: '', apiKey: 'AIzaOne, AIzaTwo', model: 'gemini-2.5-flash' })
  assert.deepEqual(values, { PRIMARY_LLM_PROVIDER: 'gemini', GEMINI_API_KEYS: 'AIzaOne, AIzaTwo', GEMINI_MODEL: 'gemini-2.5-flash' })
  assert.equal(setup.checkServiceFor(preset('gemini')), 'gemini')
  assert.equal(setup.formProblem(preset('gemini'), { baseUrl: '', apiKey: 'AIzaOne, AIzaTwo', model: 'm' }), null)
})

test('the form explains what is missing before a test is allowed', () => {
  const openai = preset('openai')
  assert.match(setup.formProblem(openai, setup.initialForm(openai)), /金鑰/)
  assert.match(setup.formProblem(openai, { ...setup.initialForm(openai), apiKey: 'sk a' }), /空白/)
  assert.match(setup.formProblem(openai, { ...setup.initialForm(openai), apiKey: 'sk-a', model: ' ' }), /模型/)
  const custom = preset('custom')
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
      checkConnection: async (service, values) => { ctx.checks.push([service, values]); return ctx.nextCheck },
      saveSettings: async (values) => { ctx.saved.push(values); return {} },
    },
    checks: [], saved: [], errors: [], nextCheck: { ok: true, status: 200, message: 'ok', detail: '' }, store,
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

test('opens by itself only while no provider is usable', async () => {
  let ctx = context()
  let view = await mountWizard()
  assert.equal(ctx.ui.showSetupWizard, true)
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

test('saving needs a successful test of exactly the values being saved', async () => {
  const ctx = context()
  const view = await mountWizard()
  try {
    const s = view.state
    s.choose('openai')
    s.step = 'connect'
    assert.match(s.problem, /金鑰/)
    s.form.apiKey = 'sk-wizard-typed'
    await nextTick()
    assert.equal(s.canSave, false)

    ctx.nextCheck = { ok: false, status: 401, message: '金鑰無效', detail: '' }
    await s.test()
    assert.equal(s.canSave, false)

    ctx.nextCheck = { ok: true, status: 200, message: '連線成功', detail: '' }
    await s.test()
    assert.deepEqual(ctx.checks.at(-1), ['llm', {
      PRIMARY_LLM_PROVIDER: 'openai_compatible', OPENAI_BASE_URL: 'https://api.openai.com/v1',
      OPENAI_API_KEY: 'sk-wizard-typed', PRIMARY_MODEL: 'gpt-4o-mini',
    }])
    assert.equal(s.canSave, true)

    s.form.model = 'gpt-4o'
    await nextTick()
    assert.equal(s.canSave, false) // edited after the test
    assert.equal(s.result, null)
    await s.test()
    await s.save()
    assert.deepEqual(ctx.saved, [{
      PRIMARY_LLM_PROVIDER: 'openai_compatible', OPENAI_BASE_URL: 'https://api.openai.com/v1',
      OPENAI_API_KEY: 'sk-wizard-typed', PRIMARY_MODEL: 'gpt-4o',
    }])
    assert.equal(s.step, 'done')
    assert.equal(s.form.apiKey, '') // the key does not linger in the page
    assert.equal(ctx.ui.settingsVersion, 1)
  } finally { view.unmount() }
})

test('a Gemini choice is tested with the Gemini check', async () => {
  const ctx = context()
  const view = await mountWizard()
  try {
    view.state.choose('gemini')
    view.state.form.apiKey = 'AIzaWizard'
    await view.state.test()
    assert.equal(ctx.checks.at(-1)[0], 'gemini')
  } finally { view.unmount() }
})
