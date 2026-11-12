import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import ts from 'typescript'
import { parse, compileScript } from '@vue/compiler-sfc'
import { createRenderer, h, reactive, nextTick } from 'vue'
import { createPinia, setActivePinia } from 'pinia'

// Run real Vue setup/lifecycle logic without a browser or network requests.
const renderer = createRenderer({
  createElement: () => ({}), createText: () => ({}), createComment: () => ({}),
  insert() {}, remove() {}, setText() {}, setComment() {}, setElementText() {},
  patchProp() {}, parentNode: () => null, nextSibling: () => null,
})
const moduleUrl = code => `data:text/javascript;base64,${Buffer.from(code).toString('base64')}`
let moduleId = 0

// Rule modules with no runtime imports are loaded for real, so components run the actual rules.
const REAL = { '@/lib/addInput': 'lib/addInput.ts', '@/lib/omnibox': 'lib/omnibox.ts', '@/lib/wall': 'lib/wall.ts', '@/lib/experiments': 'lib/experiments.ts' }
const realUrls = {}
async function realModule(specifier) {
  if (!realUrls[specifier]) {
    const source = await readFile(new URL(`../src/${REAL[specifier]}`, import.meta.url), 'utf8')
    realUrls[specifier] = moduleUrl(ts.transpileModule(source, {
      compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
    }).outputText)
  }
  return realUrls[specifier]
}

async function loadSource(path) {
  let source = await readFile(new URL(`../src/${path}`, import.meta.url), 'utf8')
  if (path.endsWith('.vue')) source = compileScript(parse(source).descriptor, { id: path }).content
  let { outputText } = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
  })
  const parsed = ts.createSourceFile('test.js', outputText, ts.ScriptTarget.ES2022, true)
  for (const statement of parsed.statements) {
    if (!ts.isImportDeclaration(statement)) continue
    const specifier = statement.moduleSpecifier.text
    let url
    if (['vue', 'pinia'].includes(specifier)) url = import.meta.resolve(specifier)
    else if (REAL[specifier]) url = await realModule(specifier)
    else {
      const mocks = []
      if (statement.importClause?.name) mocks.push('export default {}')
      const bindings = statement.importClause?.namedBindings
      const names = bindings && ts.isNamedImports(bindings)
        ? bindings.elements.map(binding => (binding.propertyName || binding.name).text)
        : ['getItems', 'getItemsPage', 'searchSemantic', 'getItem', 'getStats', 'getCategories', 'ingest']
      for (const name of names) {
        let value = '() => undefined'
        if (specifier.endsWith('/api')) value = `(...args) => globalThis.__uiTest.api.${name}(...args)`
        else if (name === 'useUiStore') value = '() => globalThis.__uiTest.ui'
        else if (name === 'useItemsStore') value = '() => globalThis.__uiTest.items'
        else if (name === 'useRadarStore') value = '() => ({ ensureLoaded() {} })'
        else if (name === 'useExperimentsStore') value = '() => globalThis.__uiTest.experiments'
        else if (name === 'blockedShortcut') value = '(...args) => globalThis.__uiTest.blockedShortcut(...args)'
        else if (name === 'useMutations') value = '() => globalThis.__uiTest.mutations'
        else if (name === 'useSignal') value = '() => ({ tuneItem() {} })'
        else if (name === 'useTheme') value = '() => ({ mode: { value: "light" }, labels: { light: "淺色" }, accent: "blue", accents: [], set() {}, setAccent() {}, toggle() {} })'
        else if (name === 'toast') value = 'Object.assign(() => undefined, { success() {}, error() {}, info() {}, loading() {} })'
        else if (name === 'useDebounceFn') value = 'fn => fn'
        mocks.push(`export const ${name} = ${value}`)
      }
      url = moduleUrl(mocks.join('\n'))
    }
    outputText = outputText.replace(statement.moduleSpecifier.getText(parsed), JSON.stringify(url))
  }
  return import(moduleUrl(`${outputText}\n// test module ${++moduleId}`))
}

function mount(component, props = {}) {
  const vnode = h({ ...component, render: () => null }, props)
  const container = {}
  renderer.render(vnode, container)
  return { state: vnode.component.setupState, unmount: () => renderer.render(null, container) }
}
function deferred() {
  let resolve, reject
  const promise = new Promise((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}
// The real rule for which shortcuts an experimental feature owns (it has no imports to mock).
const { blockedShortcut } = await import(moduleUrl(ts.transpileModule(
  await readFile(new URL('../src/lib/experiments.ts', import.meta.url), 'utf8'),
  { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } },
).outputText))

function reset() {
  globalThis.window = new EventTarget()
  globalThis.HTMLElement = class {}
  globalThis.document = { activeElement: null }
  globalThis.__uiTest = {
    ui: reactive({
      activeItem: null, sidebarOpen: true, detailTab: 'analysis', addDraft: '', pendingQuestion: '',
      openAdd(text = '') { this.addDraft = text; this.showAddModal = true },
      ask(question) { this.pendingQuestion = question; this.showBrainModal = true },
      openImport(tab, file = null) { this.importTab = tab; this.importFile = file; this.showImportModal = true },
      openSettings(tab) { this.settingsTab = tab; this.showSettingsModal = true },
    }),
    items: reactive({
      items: [], get visibleItems() { return this.items }, triageView: 'inbox', categories: [], stats: {},
      searchQuery: '', searchMode: 'keyword', kindFilter: 'all', currentCategory: '全部', viewMode: 'list', loads: 0,
      loadItems() { this.loads++ }, refreshAll: async () => {},
    }),
    mutations: { toggleStar() {}, toggleRead() {}, updateCategory() {} },
    api: {},
    // Every experimental feature on, unless a test switches one off.
    experiments: reactive({ flags: { radar: true, watch: true, daily: true } }),
    blockedShortcut,
  }
  return globalThis.__uiTest
}

async function openAdd(ctx, text = '') {
  const view = mount((await loadSource('components/modals/AddDialog.vue')).default)
  ctx.ui.openAdd(text)
  await nextTick()
  return view
}

test('新增 keeps what was typed when sending fails, says why, sends once, and clears only on success', async () => {
  const ctx = reset()
  const pending = deferred()
  const sent = []
  ctx.api.ingest = (content, opts) => { sent.push([content, opts]); return pending.promise }
  const view = await openAdd(ctx)
  try {
    view.state.text = '  https://example.test/article  '
    assert.equal(view.state.outcome, '會收藏 1 個連結')
    const first = view.state.submit()
    await view.state.submit()                       // a second press while the first is on its way
    assert.equal(sent.length, 1)
    assert.deepEqual(sent[0], ['https://example.test/article', { async: false }])
    assert.equal(ctx.ui.isIngesting, true)
    pending.reject(new Error('這個網址連不上。'))
    await first
    assert.equal(view.state.text, 'https://example.test/article')
    assert.equal(view.state.error, '連結沒有收藏成功：這個網址連不上。內容還在，可以再試一次。')
    assert.equal(ctx.ui.showAddModal, true)
    assert.equal(ctx.ui.isIngesting, false)
    assert.equal(view.state.submitting, false)
    // The server answering "not saved" is a failure too.
    ctx.api.ingest = async () => ({ success: false, detail: '讀不到內容' })
    await view.state.submit()
    assert.match(view.state.error, /讀不到內容/)
    assert.equal(view.state.text, 'https://example.test/article')
    ctx.api.ingest = async () => ({ success: true, item: { id: 5, title_l1: '文章' } })
    await view.state.submit()
    assert.equal(view.state.text, '')
    assert.equal(view.state.error, '')
    assert.equal(ctx.ui.showAddModal, false)
    assert.equal(ctx.ui.activeItem.id, 5)
  } finally { view.unmount() }
})

test('新增 saves other text as a note, with the chosen category, even when it holds an address', async () => {
  const ctx = reset()
  const sent = []
  ctx.api.ingest = async (content, opts) => { sent.push([content, opts]); return { success: true } }
  const view = await openAdd(ctx)
  try {
    view.state.text = '這篇值得再看 https://example.test/post'
    await nextTick()
    assert.equal(view.state.plan.kind, 'note')
    assert.equal(view.state.outcome, '會存成筆記')
    view.state.linksOnly = true                     // the switch next to the line
    assert.equal(view.state.outcome, '會收藏 1 個連結')
    view.state.linksOnly = false
    view.state.category = '研究'
    await view.state.submit()
    assert.deepEqual(sent, [['這篇值得再看 https://example.test/post', { category: '研究', asNote: true }]])
    assert.equal(ctx.ui.showAddModal, false)
    // The draft is gone after a save, and the default is to let the AI pick the category.
    ctx.ui.openAdd()
    await nextTick()
    assert.equal(view.state.text, '')
    view.state.text = '第二則'
    view.state.category = 'auto'
    await view.state.submit()
    assert.deepEqual(sent[1], ['第二則', { category: null, asNote: true }])
  } finally { view.unmount() }
})

test('新增 queues several links and keeps only the ones that did not go through', async () => {
  const ctx = reset()
  const sent = []
  ctx.api.ingest = async (content, opts) => {
    sent.push([content, opts])
    if (content.includes('bad')) throw new Error('不允許的網址')
    return { success: true }
  }
  const view = await openAdd(ctx)
  try {
    view.state.text = 'https://a.example/1\nhttps://bad.example/2\nhttps://c.example/3'
    assert.equal(view.state.outcome, '會收藏 3 個連結，在背景依序讀取')
    await view.state.submit()
    assert.deepEqual(sent.map(([url, opts]) => [url, opts.async]), [
      ['https://a.example/1', true], ['https://bad.example/2', true], ['https://c.example/3', true],
    ])
    assert.equal(view.state.text, 'https://bad.example/2')
    assert.match(view.state.error, /1 個連結沒有送出（另外 2 個已排入）：不允許的網址/)
    assert.equal(ctx.ui.showAddModal, true)
  } finally { view.unmount() }
})

test('新增 hands a bookmark file to the import and refuses other files before sending', async () => {
  const ctx = reset()
  let sent = 0
  ctx.api.ingest = async () => { sent++; return { success: true } }
  const view = await openAdd(ctx)
  try {
    view.state.takeFiles([{ name: 'photo.png' }])
    assert.equal(view.state.plan.kind, 'unsupported')
    assert.equal(view.state.canSubmit, false)
    await view.state.submit()
    assert.equal(ctx.ui.showImportModal, undefined)
    view.state.takeFiles([{ name: 'bookmarks.html' }])
    assert.equal(view.state.outcome, '會匯入 bookmarks.html')
    await view.state.submit()
    assert.equal(ctx.ui.showAddModal, false)
    assert.equal(ctx.ui.showImportModal, true)
    assert.equal(ctx.ui.importTab, 'file')
    assert.equal(ctx.ui.importFile.name, 'bookmarks.html')
    assert.equal(sent, 0)
  } finally { view.unmount() }
})

test('a link pasted on the page opens 新增 with it and sends nothing; other pastes are left alone', async () => {
  const ctx = reset()
  let sent = 0
  ctx.api.ingest = async () => { sent++; return { success: true } }
  const view = mount((await loadSource('components/modals/AddDialog.vue')).default)
  const paste = text => {
    const event = new Event('paste', { cancelable: true })
    event.clipboardData = { getData: () => text }
    window.dispatchEvent(event)
    return event
  }
  try {
    assert.equal(paste('只是一段文字').defaultPrevented, false)
    assert.equal(ctx.ui.showAddModal, undefined)
    document.activeElement = { tagName: 'INPUT' }
    assert.equal(paste('https://example.test/a').defaultPrevented, false)   // typing somewhere: the field gets it
    assert.equal(ctx.ui.showAddModal, undefined)
    document.activeElement = null
    assert.equal(paste(' https://example.test/a\nhttps://example.test/b ').defaultPrevented, true)
    assert.equal(ctx.ui.showAddModal, true)
    await nextTick()
    assert.equal(view.state.text, 'https://example.test/a\nhttps://example.test/b')
    assert.equal(view.state.outcome, '會收藏 2 個連結，在背景依序讀取')
    assert.equal(sent, 0)
  } finally { view.unmount() }
})

test('the search box searches as you type; asking happens only when chosen and is never searched for', async () => {
  const ctx = reset()
  const view = mount((await loadSource('components/layout/SearchBox.vue')).default)
  const key = (value, extra = {}) => {
    const event = { key: value, prevented: false, preventDefault() { this.prevented = true }, ...extra }
    view.state.onKeydown(event)
    return event
  }
  try {
    view.state.open = true
    assert.deepEqual(view.state.sections.map(s => s.label), ['篩選', '動作'])
    view.state.text = 'rust 的所有權是什麼'
    await nextTick()
    assert.equal(ctx.items.searchQuery, 'rust 的所有權是什麼')
    assert.equal(ctx.items.loads, 1)                                  // the live search, as before
    assert.deepEqual(view.state.rows.slice(0, 2).map(r => r.kind), ['search', 'ask'])
    assert.equal(view.state.active, 0)
    key('Enter', { isComposing: true })                               // choosing a candidate in an input method
    assert.equal(ctx.items.loads, 1)
    key('Enter')                                                      // Enter is the search
    assert.equal(ctx.items.loads, 2)
    assert.equal(ctx.ui.showBrainModal, undefined)
    assert.equal(view.state.open, false)
    assert.equal(key('Tab').prevented, true)                          // Tab picks 提問
    assert.equal(view.state.rows[view.state.active].kind, 'ask')
    key('Enter')
    assert.equal(ctx.ui.pendingQuestion, 'rust 的所有權是什麼')
    assert.equal(ctx.ui.showBrainModal, true)
    assert.equal(view.state.text, '')
    assert.equal(ctx.items.searchQuery, '')                           // the list is no longer narrowed by the question
    assert.equal(ctx.items.loads, 3)
  } finally { view.unmount() }
})

test('ask mode is visible state: typing there searches nothing, Ctrl+Enter and Enter ask, Esc drops it', async () => {
  const ctx = reset()
  const view = mount((await loadSource('components/layout/SearchBox.vue')).default)
  const key = (value, extra = {}) => view.state.onKeydown({ key: value, preventDefault() {}, ...extra })
  try {
    await view.state.focus('ask')
    assert.equal(view.state.mode, 'ask')
    assert.deepEqual(view.state.rows, [])                              // nothing listed until there is a question
    view.state.text = '最近收藏了什麼'
    await nextTick()
    assert.equal(ctx.items.searchQuery, '')
    assert.equal(ctx.items.loads, 0)
    assert.deepEqual(view.state.rows.map(r => r.kind), ['ask', 'search'])
    key('Escape')
    assert.equal(view.state.mode, 'search')
    assert.equal(view.state.text, '')
    assert.equal(ctx.ui.showBrainModal, undefined)

    // From search mode, Ctrl/Cmd+Enter asks without picking the row first.
    view.state.text = '怎麼設定備份'
    await nextTick()
    key('Enter', { ctrlKey: true })
    assert.equal(ctx.ui.pendingQuestion, '怎麼設定備份')
    assert.equal(ctx.items.searchQuery, '')

    // Switching to ask mode with a search in the box turns it into the question.
    view.state.text = 'vue'
    await nextTick()
    const before = ctx.items.loads
    view.state.toggleAsk()
    assert.equal(view.state.mode, 'ask')
    assert.equal(view.state.text, 'vue')
    assert.equal(ctx.items.searchQuery, '')
    assert.equal(ctx.items.loads, before + 1)
    key('Backspace')                                                   // not empty: an ordinary Backspace
    assert.equal(view.state.mode, 'ask')
    view.state.text = ''
    await nextTick()
    key('Backspace')
    assert.equal(view.state.mode, 'search')
  } finally { view.unmount() }
})

test('a filter or an action picked in the search box runs, and the words typed to find it are not kept as a search', async () => {
  const ctx = reset()
  ctx.items.categories = [{ id: 1, name: 'Rust', item_count: 4 }, { id: 2, name: 'Inbox' }, { id: 3, name: '監看', item_count: 2 }, { id: 4, name: '空的' }]
  ctx.experiments.flags = { radar: false, watch: false, daily: false }
  const view = mount((await loadSource('components/layout/SearchBox.vue')).default)
  const pick = id => view.state.run(view.state.rows.find(row => row.id === id))
  try {
    const listed = view.state.rows.map(row => row.id)
    for (const id of ['view-inbox', 'view-starred', 'view-archived', 'view-all', 'kind-project', 'kind-video', 'cat-1', 'add', 'settings', 'view-mode', 'shortcuts'])
      assert.ok(listed.includes(id), id)
    // Features that are switched off, and the categories they own, are not offered.
    for (const id of ['view-radar', 'radar-deck', 'radar-settings', 'watch', 'daily', 'cat-2', 'cat-3']) assert.ok(!listed.includes(id), id)
    // An empty category and the less common actions wait until something is typed.
    for (const id of ['cat-4', 'theme', 'notifications']) assert.ok(!listed.includes(id), id)
    ctx.experiments.flags = { radar: true, watch: true, daily: true }
    for (const id of ['view-radar', 'radar-deck', 'radar-settings', 'watch', 'daily', 'cat-3']) assert.ok(view.state.rows.some(row => row.id === id), id)

    pick('view-starred')
    assert.equal(ctx.items.triageView, 'starred')
    pick('kind-video')
    assert.equal(ctx.items.kindFilter, 'video')
    assert.equal(view.state.rows.find(row => row.id === 'kind-video').entry.on, true)
    pick('kind-video')                                                 // picking an applied filter takes it off
    assert.equal(ctx.items.kindFilter, 'all')
    pick('cat-1')
    assert.equal(ctx.items.currentCategory, 'Rust')
    pick('view-mode')
    assert.equal(ctx.items.viewMode, 'cards')

    view.state.text = '快捷'
    await nextTick()
    assert.equal(ctx.items.searchQuery, '快捷')
    assert.deepEqual(view.state.rows.map(row => row.id), ['search', 'ask', 'shortcuts'])
    pick('shortcuts')
    assert.equal(ctx.ui.showShortcutsModal, true)
    view.state.text = '空'
    await nextTick()
    assert.deepEqual(view.state.rows.map(row => row.id), ['search', 'ask', 'cat-4'])
    view.state.text = ''
    await nextTick()
    assert.equal(view.state.text, '')
    assert.equal(ctx.items.searchQuery, '')
    pick('add')
    assert.equal(ctx.ui.showAddModal, true)
  } finally { view.unmount() }
})

test('on a narrow screen the search row opens before the box is focused, for searching or asking', async () => {
  reset()
  const view = mount((await loadSource('components/layout/AppHeader.vue')).default)
  const focused = []
  try {
    view.state.searchBox = { focus: mode => focused.push(mode) }
    await view.state.focusSearchInput()
    assert.equal(view.state.showMobileSearch, true)
    view.state.showMobileSearch = false
    await view.state.focusAsk()
    assert.equal(view.state.showMobileSearch, true)
    assert.deepEqual(focused, ['search', 'ask'])
  } finally { view.unmount() }
})

test('empty states distinguish first use, search, cleared inbox and load failure', async () => {
  const ctx = reset()
  Object.assign(ctx.items, { error: null, searchQuery: '', currentCategory: '全部', stats: { total: 0 } })
  const view = mount((await loadSource('components/items/ItemList.vue')).default)
  try {
    assert.equal(view.state.firstUse, true)
    assert.equal(view.state.emptyState.action, '新增')
    ctx.items.searchQuery = '沒有結果的搜尋'
    assert.equal(view.state.firstUse, false)
    assert.equal(view.state.emptyState.action, '清除搜尋條件')
    view.state.recoverEmpty()
    assert.equal(ctx.items.searchQuery, '')
    assert.equal(ctx.ui.showAddModal, undefined)
    ctx.items.stats.total = 5
    assert.equal(view.state.emptyState.title, '收件匣已清空')
    ctx.items.error = '連線中斷'
    assert.equal(view.state.emptyState.action, '重新載入')
    assert.equal(view.state.firstUse, false)
    // With nothing saved yet, the one action is the 新增 panel.
    Object.assign(ctx.items, { error: null, stats: { total: 0 } })
    view.state.recoverEmpty()
    assert.equal(ctx.ui.showAddModal, true)
  } finally { view.unmount() }
})

test('cancelled, vertical, multi-touch and button gestures never commit; real swipes commit once', async () => {
  const ctx = reset()
  const actions = []
  ctx.mutations.toggleStar = item => actions.push(['star', item.id])
  ctx.mutations.toggleRead = item => actions.push(['archive', item.id])
  const view = mount((await loadSource('components/items/SwipeableRow.vue')).default, { item: { id: 7 } })
  const touch = (x, y = 0, target = false, count = 1) => ({
    touches: Array.from({ length: count }, () => ({ clientX: x, clientY: y })),
    target: { closest: () => target }, preventDefault() {},
  })
  try {
    view.state.onTouchStart(touch(0))
    view.state.onTouchMove(touch(120))
    view.state.onTouchCancel()
    view.state.onTouchEnd()
    view.state.onTouchStart(touch(0))
    view.state.onTouchMove(touch(5, 120))
    view.state.onTouchEnd()
    view.state.onTouchStart(touch(0))
    view.state.onTouchMove(touch(120, 0, false, 2))
    view.state.onTouchEnd()
    view.state.onTouchStart(touch(0, 0, true))
    view.state.onTouchMove(touch(120))
    view.state.onTouchEnd()
    assert.deepEqual(actions, [])
    view.state.onTouchStart(touch(0))
    view.state.onTouchMove(touch(120))
    view.state.onTouchEnd()
    view.state.onTouchEnd()
    view.state.onTouchStart(touch(0))
    view.state.onTouchMove(touch(-120))
    view.state.onTouchEnd()
    assert.deepEqual(actions, [['star', 7], ['archive', 7]])
    assert.equal(view.state.dx, 0)
  } finally { view.unmount() }
})

test('list requests keep the newest result and ignore stale errors', async () => {
  const ctx = reset()
  setActivePinia(createPinia())
  const store = (await loadSource('stores/items.ts')).useItemsStore()
  const first = deferred(), second = deferred()
  const responses = [first, second]
  ctx.api.getItemsPage = () => responses.shift().promise
  store.searchQuery = '舊條件'
  const a = store.loadItems()
  store.searchQuery = '新條件'
  const b = store.loadItems()
  second.resolve({ items: [{ id: 2 }], total: 1 })
  await b
  first.reject(new Error('stale request'))
  await a
  assert.deepEqual(store.items, [{ id: 2 }])
  assert.equal(store.loading, false)
  assert.equal(store.error, null)
})

test('list failure preserves previous items and a retry clears the error', async () => {
  const ctx = reset()
  setActivePinia(createPinia())
  const store = (await loadSource('stores/items.ts')).useItemsStore()
  store.items = [{ id: 3 }]
  ctx.api.getItemsPage = async () => { throw new Error('offline') }
  await store.loadItems()
  assert.deepEqual(store.items, [{ id: 3 }])
  assert.match(store.error, /重試/)
  assert.equal(store.loading, false)
  ctx.api.getItemsPage = async () => ({ items: [{ id: 4 }], total: 1 })
  await store.loadItems()
  assert.deepEqual(store.items, [{ id: 4 }])
  assert.equal(store.error, null)
})

test('reader ignores stale detail responses and offers a retry after failure', async () => {
  const ctx = reset()
  const a = deferred(), b = deferred()
  ctx.api.getItem = id => id === 1 ? a.promise : b.promise
  ctx.ui.activeItem = { id: 1 }
  const view = mount((await loadSource('components/reader/ReaderPane.vue')).default)
  try {
    ctx.ui.activeItem = { id: 2 }
    await nextTick()
    b.resolve({ id: 2, title_l1: '最新文章' })
    await b.promise
    await nextTick()
    a.resolve({ id: 1, title_l1: '過期文章' })
    await a.promise
    await nextTick()
    assert.equal(ctx.ui.activeItem.id, 2)
    assert.equal(view.state.fetchingFull, false)
    ctx.api.getItem = async () => { throw new Error('offline') }
    await view.state.loadFull(2)
    assert.match(view.state.detailError, /載入失敗/)
    assert.equal(ctx.ui.activeItem.title_l1, '最新文章')
    ctx.api.getItem = async () => ({ id: 2, title_l1: '重新取得的文章' })
    await view.state.loadFull(2)
    assert.equal(view.state.detailError, '')
    assert.equal(ctx.ui.activeItem.title_l1, '重新取得的文章')
  } finally { view.unmount() }
})

test('keyboard shortcuts preserve browser actions and native button activation', async () => {
  const ctx = reset()
  const { useKeyboard } = await loadSource('composables/useKeyboard.ts')
  let search = 0, ask = 0
  const view = mount({ setup() { useKeyboard(() => ({ focusSearchInput: () => search++, focusAsk: () => ask++ })); return {} } })
  const key = (value, extra = {}) => {
    const event = new Event('keydown', { cancelable: true })
    Object.assign(event, { key: value, ctrlKey: false, metaKey: false, altKey: false, ...extra })
    window.dispatchEvent(event)
    return event
  }
  try {
    assert.equal(key('r', { ctrlKey: true }).defaultPrevented, false)
    assert.equal(ctx.ui.showRadarModal, undefined)
    assert.equal(key('b', { metaKey: true }).defaultPrevented, true)
    assert.equal(ctx.ui.sidebarOpen, false)
    key('/')
    assert.equal(search, 1)
    assert.equal(key('k', { ctrlKey: true }).defaultPrevented, true)   // the same box
    assert.equal(key('K', { metaKey: true }).defaultPrevented, true)
    assert.equal(search, 3)
    key('b'); key('B')                                                 // asking is that box in ask mode
    assert.equal(ask, 2)
    assert.equal(ctx.ui.showBrainModal, undefined)
    key('n', { isComposing: true })
    assert.equal(ctx.ui.showAddModal, undefined)
    key('n')
    assert.equal(ctx.ui.showAddModal, true)
    ctx.ui.showAddModal = false
    key('i')                                                           // importing has no key of its own any more
    assert.equal(ctx.ui.showImportModal, undefined)
    ctx.items.items = [{ id: 9 }]
    document.activeElement = { tagName: 'BUTTON', closest: selector => selector === 'button, a' }
    key('Enter')
    assert.equal(ctx.ui.activeItem, null)
    key('j')
    assert.equal(ctx.ui.activeItem.id, 9)
    document.activeElement = null
    key('N')
    assert.equal(ctx.ui.showAddModal, true)
    // Under a dialog Ctrl/Cmd+K is left to the browser: the box is not reachable there.
    assert.equal(key('k', { ctrlKey: true }).defaultPrevented, false)
    assert.equal(search, 3)
    // From another field it still goes to the search box.
    ctx.ui.showAddModal = false
    document.activeElement = { tagName: 'TEXTAREA' }
    key('k', { ctrlKey: true })
    assert.equal(search, 4)
  } finally { view.unmount() }
})

test('shortcuts of an experimental feature work only while it is switched on', async () => {
  const ctx = reset()
  const { useKeyboard } = await loadSource('composables/useKeyboard.ts')
  const view = mount({ setup() { useKeyboard(() => null); return {} } })
  const key = value => {
    const event = new Event('keydown', { cancelable: true })
    Object.assign(event, { key: value, ctrlKey: false, metaKey: false, altKey: false })
    window.dispatchEvent(event)
    return event
  }
  try {
    ctx.experiments.flags = { radar: false, watch: false, daily: false }
    for (const k of ['r', 'R', 'd', 'D']) assert.equal(key(k).defaultPrevented, false, k)
    assert.equal(ctx.ui.showRadarModal, undefined)
    assert.equal(ctx.ui.showDeckModal, undefined)
    assert.equal(ctx.ui.showDailyDeckModal, undefined)
    // Everything else still works.
    key('N')
    assert.equal(ctx.ui.showAddModal, true)
    ctx.ui.showAddModal = false

    ctx.experiments.flags = { radar: false, watch: false, daily: true }
    key('D')
    assert.equal(ctx.ui.showDailyDeckModal, true)
    ctx.ui.showDailyDeckModal = false
    key('d')
    assert.equal(ctx.ui.showDeckModal, undefined)

    ctx.experiments.flags = { radar: true, watch: false, daily: false }
    key('d')
    assert.equal(ctx.ui.showDeckModal, true)
    ctx.ui.showDeckModal = false
    key('r')
    assert.equal(ctx.ui.showRadarModal, true)
  } finally { view.unmount() }
})

test('while the settings page is open only Esc does anything, and it asks the page to close', async () => {
  const ctx = reset()
  const { useKeyboard } = await loadSource('composables/useKeyboard.ts')
  let reached = 0
  const view = mount({ setup() { useKeyboard(() => ({ focusSearchInput: () => reached++, focusAsk: () => reached++ })); return {} } })
  const key = (value, extra = {}) => {
    const event = new Event('keydown', { cancelable: true })
    Object.assign(event, { key: value, ctrlKey: false, metaKey: false, altKey: false, ...extra })
    window.dispatchEvent(event)
  }
  try {
    ctx.ui.showSettingsModal = true
    ctx.ui.settingsCloseRequests = 0
    ctx.items.items = [{ id: 1 }]
    document.querySelector = () => null
    key('N'); key('j'); key('b'); key('/'); key('k', { ctrlKey: true })
    assert.equal(ctx.ui.showAddModal, undefined)
    assert.equal(ctx.ui.activeItem, null)
    assert.equal(reached, 0)
    key('Escape')
    assert.equal(ctx.ui.settingsCloseRequests, 1)
    // A confirmation or a menu open on top of the page gets the Esc instead.
    document.querySelector = () => ({})
    key('Escape')
    assert.equal(ctx.ui.settingsCloseRequests, 1)
  } finally { view.unmount() }
})

test('in the cover wall J/K move a cursor, Enter opens it, and E/S act on it', async () => {
  const ctx = reset()
  const acted = []
  ctx.mutations.toggleRead = item => acted.push(['archive', item.id])
  ctx.mutations.toggleStar = item => acted.push(['star', item.id])
  Object.assign(ctx.items, { viewMode: 'cards', items: [{ id: 1 }, { id: 2 }, { id: 3 }] })
  const { useKeyboard } = await loadSource('composables/useKeyboard.ts')
  const view = mount({ setup() { useKeyboard(() => null); return {} } })
  const key = value => {
    const event = new Event('keydown', { cancelable: true })
    Object.assign(event, { key: value, ctrlKey: false, metaKey: false, altKey: false })
    window.dispatchEvent(event)
  }
  try {
    key('e')
    assert.deepEqual(acted, [])              // nothing selected yet
    key('j'); key('j')
    assert.equal(ctx.ui.cursorId, 2)
    assert.equal(ctx.ui.activeItem, null)    // moving does not open (or log a view)
    key('k')
    assert.equal(ctx.ui.cursorId, 1)
    key('k')
    assert.equal(ctx.ui.cursorId, 1)         // stops at the first item
    key('s'); key('e')
    assert.deepEqual(acted, [['star', 1], ['archive', 1]])
    key('Enter')
    assert.equal(ctx.ui.activeItem.id, 1)
    key('j')                                 // with the reader open, J reads the next item
    assert.equal(ctx.ui.activeItem.id, 2)
    assert.equal(ctx.ui.cursorId, 2)
    key('Escape')
    assert.equal(ctx.ui.activeItem, null)
    assert.equal(ctx.ui.cursorId, 2)         // closing keeps the place
  } finally { view.unmount() }
})

test('a menu item runs after its menu has closed, once, and plain closes are left alone', async () => {
  const { useMenuAction } = await loadSource('composables/useMenuAction.ts')
  const menu = useMenuAction()
  const event = () => ({ prevented: 0, preventDefault() { this.prevented++ } })
  let opened = 0
  const dismissed = event()
  menu.flush(dismissed)                      // Esc with nothing chosen: focus goes back to the button
  assert.equal(dismissed.prevented, 0)
  menu.defer(() => opened++)
  assert.equal(opened, 0)                    // not while the menu is still closing
  const chosen = event()
  menu.flush(chosen)
  assert.equal(opened, 1)
  assert.equal(chosen.prevented, 1)          // the dialog keeps focus instead of the menu button
  menu.flush(event())
  assert.equal(opened, 1)
})

test('scrolling loads the next page once, appends without repeats, and stops at the total', async () => {
  const ctx = reset()
  setActivePinia(createPinia())
  const { useItemsStore, PAGE_SIZE } = await loadSource('stores/items.ts')
  const store = useItemsStore()
  const page = (from, count) => Array.from({ length: count }, (_, i) => ({ id: from + i }))
  const asked = []
  const second = deferred()
  ctx.api.getItemsPage = filters => {
    asked.push({ offset: filters.offset ?? 0, limit: filters.limit })
    if (!filters.offset) return Promise.resolve({ items: page(1, PAGE_SIZE), total: PAGE_SIZE + 3 })
    return second.promise
  }
  await store.loadItems()
  assert.equal(store.items.length, PAGE_SIZE)
  assert.equal(store.total, PAGE_SIZE + 3)
  assert.equal(store.hasMore, true)
  const more = store.loadMore()
  await store.loadMore()                         // a second call while one is running does nothing
  assert.equal(asked.length, 2)
  assert.deepEqual(asked[1], { offset: PAGE_SIZE, limit: PAGE_SIZE })
  assert.equal(store.loadingMore, true)
  // Something was saved meanwhile: the page starts with an item that is already listed.
  second.resolve({ items: page(PAGE_SIZE, 4), total: PAGE_SIZE + 3 })
  await more
  assert.equal(store.items.length, PAGE_SIZE + 3)
  assert.equal(new Set(store.items.map(item => item.id)).size, PAGE_SIZE + 3)
  assert.equal(store.loadingMore, false)
  assert.equal(store.hasMore, false)
  await store.loadMore()
  assert.equal(asked.length, 2)                  // nothing left to ask for
})

test('a failed page keeps what is loaded and can be retried; a new list drops a page still in flight', async () => {
  const ctx = reset()
  setActivePinia(createPinia())
  const { useItemsStore, PAGE_SIZE } = await loadSource('stores/items.ts')
  const store = useItemsStore()
  const first = { items: Array.from({ length: PAGE_SIZE }, (_, i) => ({ id: i + 1 })), total: PAGE_SIZE * 3 }
  let fail = true
  const slow = deferred()
  ctx.api.getItemsPage = filters => {
    if (!filters.offset) return Promise.resolve(filters.kind ? { items: [{ id: 900 }], total: 1 } : first)
    if (fail) return Promise.reject(new Error('offline'))
    return slow.promise
  }
  await store.loadItems()
  await store.loadMore()
  assert.match(store.moreError, /載入失敗/)
  assert.equal(store.items.length, PAGE_SIZE)
  assert.equal(store.hasMore, true)
  fail = false
  const retry = store.loadMore()
  assert.equal(store.moreError, null)
  // Picking a kind tab asks the server for that kind from the first page...
  store.kindFilter = 'video'
  await nextTick()
  await new Promise(resolve => setTimeout(resolve, 0))
  assert.deepEqual(store.items, [{ id: 900 }])
  assert.equal(store.total, 1)
  // ...and the page of the old list that was still on its way is not appended to it.
  slow.resolve({ items: [{ id: 500 }], total: PAGE_SIZE * 3 })
  await retry
  assert.deepEqual(store.items, [{ id: 900 }])
  assert.equal(store.loadingMore, false)
})

test('the list asks the server for the kind and the order instead of filtering what is loaded', async () => {
  const ctx = reset()
  setActivePinia(createPinia())
  const store = (await loadSource('stores/items.ts')).useItemsStore()
  const asked = []
  ctx.api.getItemsPage = async filters => { asked.push(filters); return { items: [], total: 0 } }
  await store.loadItems()
  assert.equal(asked[0].kind, undefined)
  assert.equal(asked[0].sort, 'newest')
  assert.equal(asked[0].read, 'false')            // the inbox view
  store.kindFilter = 'project'
  await nextTick()
  store.sortOrder = 'oldest'
  await nextTick()
  await new Promise(resolve => setTimeout(resolve, 0))
  assert.equal(asked.at(-1).kind, 'project')
  assert.equal(asked.at(-1).sort, 'oldest')
  assert.equal(asked.at(-1).offset, 0)
})

test('an archived item leaves the inbox in place, and undo puts it back where it was', async () => {
  const ctx = reset()
  setActivePinia(createPinia())
  const store = (await loadSource('stores/items.ts')).useItemsStore()
  ctx.api.getItemsPage = async () => ({ items: [{ id: 1 }, { id: 2, is_read: 0 }, { id: 3 }], total: 40 })
  await store.loadItems()
  const item = store.items[1]
  store.reconcile(item)
  assert.equal(store.items.length, 3)             // still unarchived: stays
  item.is_read = 1
  store.reconcile(item)
  assert.deepEqual(store.items.map(i => i.id), [1, 3])
  assert.equal(store.total, 39)
  store.reconcile(item, 1)                        // still archived: an undo position alone changes nothing
  assert.deepEqual(store.items.map(i => i.id), [1, 3])
  item.is_read = 0
  store.reconcile(item, 1)
  assert.deepEqual(store.items.map(i => i.id), [1, 2, 3])
  assert.equal(store.total, 40)
  // Starring does not move anything in the inbox, but unstarring empties the starred view.
  store.triageView = 'starred'
  item.is_starred = 0
  store.reconcile(item)
  assert.deepEqual(store.items.map(i => i.id), [1, 3])
})
