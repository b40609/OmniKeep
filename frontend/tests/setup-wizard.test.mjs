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
const guideSource = transpile(await readFile(new URL('../src/lib/telegramGuide.ts', import.meta.url), 'utf8'))
const guide = await import(moduleUrl(guideSource))

// The shape GET /api/ai/catalog returns (app/provider_catalog.py), trimmed to what the wizard reads.
const CARDS = [
  { id: 'agnes', label: 'Agnes', kind: 'openai', base_url: 'https://apihub.agnes-ai.com/v1', model: 'agnes-3.0-flash',
    models: ['agnes-3.0-flash'], key_mode: 'required', key_url: 'https://platform.agnes-ai.com/settings/apiKeys',
    editable_url: false, cost: '免費', limits: '每分鐘約 10 次', notes: '', verified: '2026-11-05' },
  { id: 'gemini', label: 'Google Gemini', kind: 'gemini', base_url: '', model: 'gemini-2.5-flash', models: [],
    key_mode: 'required', key_url: 'https://aistudio.google.com/apikey', editable_url: false, cost: '免費層',
    limits: '', notes: '', verified: '2026-11-05' },
  { id: 'ollama', label: '本機 Ollama', kind: 'ollama', base_url: 'http://127.0.0.1:11434', model: 'qwen3:8b', models: [],
    key_mode: 'none', key_url: '', editable_url: true, cost: '0', limits: '', notes: '', verified: '2026-11-05' },
  { id: 'cloudflare', label: 'Cloudflare', kind: 'openai',
    base_url: 'https://api.cloudflare.com/client/v4/accounts/<帳號 ID>/ai/v1', model: '@cf/openai/gpt-oss-120b', models: [],
    key_mode: 'required', key_url: 'https://dash.cloudflare.com/profile/api-tokens', editable_url: true, cost: '免費層',
    limits: '', notes: '', verified: '2026-11-05' },
  { id: 'custom', label: '自訂 OpenAI 相容端點', kind: 'openai', base_url: '', model: '', models: [],
    key_mode: 'optional', key_url: '', editable_url: true, cost: '', limits: '', notes: '', verified: '2026-11-05' },
  { id: 'kilo', label: 'Kilo Gateway', kind: 'openai', base_url: 'https://api.kilo.ai/api/gateway', model: 'm', models: [],
    key_mode: 'none', key_url: '', editable_url: false, cost: '免費（不用金鑰）', limits: '', notes: '',
    no_signup: true, verified: '2026-11-05' },
  { id: 'itera', label: 'Itera Compute', kind: 'openai', base_url: 'https://api.example.test/v1', model: 'm', models: [],
    key_mode: 'none', key_url: '', editable_url: false, cost: '免費（限時活動）', limits: '', notes: '',
    no_signup: true, ended: true, verified: '2026-11-05' },
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

test('the cards listed first are the ones that need no account or no key, judged from the card alone', () => {
  const starters = CARDS.filter(setup.isStarterCard).map((c) => c.id)
  assert.deepEqual(starters, ['ollama', 'kilo']) // not the paid or keyed ones, and not an offer that has ended
})

test('a pasted Telegram token gets a hint when it does not look like one; the server still decides', () => {
  assert.equal(guide.tokenProblem(''), '')
  assert.equal(guide.tokenProblem(` ${guide.TELEGRAM_TOKEN_EXAMPLE} `), '')
  assert.match(guide.tokenProblem('110201543:AAHdq TcvCH1vGWJxfSeofSAs0K5PALDsaw'), /空白/)
  assert.match(guide.tokenProblem('AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw'), /冒號/)
  assert.equal(guide.TELEGRAM_STEPS.length, 3)
  assert.match(guide.TELEGRAM_DOC_URL, /docs\/telegram_bot\.md$/)
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
  assert.equal(setup.formatCooldown(6 * 3600), '6 小時')
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
    else if (specifier === '@/lib/telegramGuide') url = moduleUrl(guideSource)
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

const FEATURES = [
  { id: 'analysis', name: '分析', level: 'basic', now: '用免註冊的服務：分析比較精簡', step: '申請金鑰', card: 'gemini' },
  { id: 'search', name: '用意思找收藏', level: 'basic', now: '每分鐘只能查 2 次' },
]

function context(status = { services: {}, needs_setup: true, undecryptable: [] }, total = 0, local = new Map()) {
  const store = new Map()
  globalThis.sessionStorage = { getItem: (k) => store.get(k) ?? null, setItem: (k, v) => store.set(k, v) }
  globalThis.localStorage = { getItem: (k) => local.get(k) ?? null, setItem: (k, v) => local.set(k, v) }
  globalThis.window = new EventTarget()
  const ctx = {
    ui: reactive({
      showSetupWizard: false, showSettingsModal: false, settingsVersion: 0,
      openSettings(tab, card, block) { ctx.opened = tab; ctx.openedBlock = block }, openAdd() { ctx.addOpened = true },
    }),
    api: {
      getServiceStatus: async () => status,
      getStats: async () => ({ inbox: total, starred: 0, archived: 0, radar: 0, total }),
      getAiFeatures: async () => ({ features: FEATURES, summary: null }),
      getAiCatalog: async () => ({ verified: '2026-11-05', cards: CARDS }),
      testAiDraft: async (draft) => { ctx.tests.push(draft); return ctx.nextTest },
      createAiConnection: async (input) => { ctx.created.push(input); return {} },
      getTelegramStatus: async () => ctx.telegram,
      saveSettings: async (values) => {
        if (ctx.refuseToken) throw new Error(ctx.refuseToken)
        ctx.saved.push(values)
        ctx.telegram = { ...ctx.telegram, configured: true }
        return {}
      },
    },
    telegram: { configured: false, bound_user_ids: [], pairing_expires_at: null }, saved: [], refuseToken: '',
    tests: [], created: [], errors: [], nextTest: { ok: true, status: 200, message: 'ok', detail: '' }, store, local,
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

  ctx = context({ services: {}, needs_setup: false, undecryptable: [] }, 3)
  view = await mountWizard()
  assert.equal(ctx.ui.showSetupWizard, false) // AI connected and links already saved: nothing to guide
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
    assert.equal(s.step, 'telegram') // the AI is connected: Telegram comes next
    assert.equal(s.aiSaved, true)
    assert.equal(s.form.apiKey, '') // the key does not linger in the page
    assert.equal(ctx.ui.settingsVersion, 1)
  } finally { view.unmount() }
})

test('the guide lists every card and hands the picker the suggested combo, with nothing preselected', async () => {
  const ctx = context()
  const recommended = [{ card: 'kilo', why: '不用註冊' }]
  ctx.api.getAiCatalog = async () => ({ verified: '2026-11-05', cards: CARDS, groups: [], recommended })
  const view = await mountWizard()
  try {
    await settle()
    const s = view.state
    assert.equal(s.cards.length, CARDS.length) // nothing hidden behind 顯示全部 any more; groups fold instead
    assert.deepEqual(s.recommended, recommended)
    assert.equal(s.cardId, '')
    s.choose('kilo')
    assert.equal(s.cardId, 'kilo')
  } finally { view.unmount() }
})

test('the AI step can be skipped; the Telegram step saves the token, then waits for the pairing', async () => {
  const ctx = context()
  const view = await mountWizard()
  try {
    await settle()
    const s = view.state
    s.step = 'telegram' // 先不接 AI
    await settle()
    assert.equal(s.aiSaved, false)
    assert.deepEqual(s.telegram, { configured: false, bound_user_ids: [], pairing_expires_at: null })

    s.token = 'not-a-token'
    await nextTick()
    assert.match(s.tokenHint, /冒號/) // a hint only: saving is still allowed
    ctx.refuseToken = 'Telegram 不接受這個權杖'
    await s.saveToken()
    assert.equal(s.tokenError, 'Telegram 不接受這個權杖')
    assert.deepEqual(ctx.saved, [])

    ctx.refuseToken = ''
    s.token = ` ${guide.TELEGRAM_TOKEN_EXAMPLE} `
    await s.saveToken()
    assert.deepEqual(ctx.saved, [{ TELEGRAM_BOT_TOKEN: guide.TELEGRAM_TOKEN_EXAMPLE }])
    assert.equal(s.token, '') // the token does not linger in the page
    assert.equal(s.telegram.configured, true)
    assert.equal(s.telegramBound, false)

    s.onPaired([4242]) // what the pairing component reports once the link was used
    await nextTick()
    assert.equal(s.telegramBound, true)

    s.step = 'done'
    s.addFirstLink()
    assert.equal(ctx.ui.showSetupWizard, false)
    assert.equal(ctx.addOpened, true)
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

test('setup decision: no AI starts at choosing one; an empty library with AI starts at the welcome, once', () => {
  const base = { needsSetup: false, undecryptable: 0, total: 0, welcomed: false, later: false, settingsOpen: false }
  assert.equal(setup.guideStart(base), 'welcome')
  assert.equal(setup.guideStart({ ...base, needsSetup: true }), 'choose')
  assert.equal(setup.guideStart({ ...base, welcomed: true }), null)
  assert.equal(setup.guideStart({ ...base, total: 5 }), null)
  assert.equal(setup.guideStart({ ...base, total: null }), null) // unknown: do not guess
  assert.equal(setup.guideStart({ ...base, later: true }), null)
  assert.equal(setup.guideStart({ ...base, settingsOpen: true }), null)
  assert.equal(setup.guideStart({ ...base, needsSetup: true, undecryptable: 1 }), null)
})

test('a new install with the no-signup AI connected opens at the welcome, then Telegram, then the first link', async () => {
  const local = new Map()
  const ctx = context({ services: {}, needs_setup: false, undecryptable: [] }, 0, local)
  let view = await mountWizard()
  try {
    assert.equal(ctx.ui.showSetupWizard, true)
    await settle()
    const s = view.state
    assert.equal(s.step, 'welcome')
    assert.equal(s.welcomeMode, true)
    assert.deepEqual(s.STEPS.map((x) => x.id), ['welcome', 'telegram', 'done'])
    assert.equal(s.features.length, FEATURES.length) // what works now, and how well
    assert.equal(s.stepDone(0), false)
    s.step = 'telegram'
    await settle()
    assert.equal(s.stepDone(0), true) // the AI is connected already: a tick, not a skipped step
    assert.equal(s.stepDone(1), false)
    s.step = 'done'
    s.addFirstLink()
    assert.equal(ctx.ui.showSetupWizard, false)
    assert.equal(ctx.addOpened, true)
    await nextTick()
    assert.equal(local.get('omnikeep-welcomed'), '1')
  } finally { view.unmount() }

  // Seen once: the next visit to the still-empty library stays quiet.
  context({ services: {}, needs_setup: false, undecryptable: [] }, 0, local)
  view = await mountWizard()
  assert.equal(globalThis.__wizard.ui.showSetupWizard, false)
  view.unmount()
})

test('the welcome points to the upgrade steps in 設定 › AI', async () => {
  const ctx = context({ services: {}, needs_setup: false, undecryptable: [] }, 0)
  const view = await mountWizard()
  try {
    await settle()
    view.state.openUpgrades()
    assert.equal(ctx.ui.showSetupWizard, false)
    assert.equal(ctx.opened, 'ai')
    assert.equal(ctx.openedBlock, 'features')
    await nextTick()
    assert.equal(ctx.local.get('omnikeep-welcomed'), '1')
  } finally { view.unmount() }
})

test('cards are listed under their kind of free, in the catalog order, and none is dropped', () => {
  const groups = [
    { id: 'keyless', title: '不用註冊，馬上能用', how: 'a' },
    { id: 'recurring', title: '註冊就有，額度會自動補回', how: 'b' },
    { id: 'local', title: '在自己電腦上跑', how: 'c' },
    { id: 'paid', title: '付費或自訂', how: 'd' },
  ]
  const cards = [
    { id: 'agnes', group: 'recurring' }, { id: 'kilo', group: 'keyless' }, { id: 'ollama', group: 'local' },
    { id: 'mystery', group: 'not-a-group' }, { id: 'old' },
  ]
  const listed = setup.groupCards(cards, groups)
  assert.deepEqual(listed.map((g) => g.group.id), ['keyless', 'recurring', 'local', 'paid']) // empty groups left out
  assert.deepEqual(listed.at(-1).cards.map((c) => c.id), ['mystery', 'old'])
  assert.equal(listed.flatMap((g) => g.cards).length, cards.length)
  assert.deepEqual(setup.groupCards(cards, []).map((g) => g.cards.length), [cards.length]) // an older server sends no groups
})

test('a card says what it can do beyond an analysis, from its caps only', () => {
  assert.deepEqual(setup.cardUses({ caps: { video: true, embeddings: false } }), ['能讀 YouTube 影片'])
  assert.deepEqual(setup.cardUses({ caps: { embeddings: true } }), ['能做搜尋向量'])
  assert.deepEqual(setup.cardUses({}), [])
})

test('the suggested combo keeps its order, drops cards that are gone or ended, and marks connected ones', () => {
  const cards = [{ id: 'gemini' }, { id: 'groq' }, { id: 'flm' }, { id: 'inception', ended: true }]
  const recs = [
    { card: 'gemini', why: 'a' }, { card: 'gone', why: 'b' }, { card: 'inception', why: 'c' },
    { card: 'groq', why: 'd' }, { card: 'flm', why: 'e' },
  ]
  const steps = setup.recommendedSteps(cards, recs, ['flm'])
  assert.deepEqual(steps.map((s) => [s.card.id, s.why, s.done]), [['gemini', 'a', false], ['groq', 'd', false], ['flm', 'e', true]])
  assert.deepEqual(setup.recommendedSteps(cards, []), []) // an older server sends no combo
})
