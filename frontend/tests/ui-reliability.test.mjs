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
    else {
      const mocks = []
      if (statement.importClause?.name) mocks.push('export default {}')
      const bindings = statement.importClause?.namedBindings
      const names = bindings && ts.isNamedImports(bindings)
        ? bindings.elements.map(binding => (binding.propertyName || binding.name).text)
        : ['getItems', 'getItemsPage', 'searchSemantic', 'getItem', 'getStats', 'getCategories']
      for (const name of names) {
        let value = '() => undefined'
        if (specifier.endsWith('/api')) value = `(...args) => globalThis.__uiTest.api.${name}(...args)`
        else if (name === 'useUiStore') value = '() => globalThis.__uiTest.ui'
        else if (name === 'useItemsStore') value = '() => globalThis.__uiTest.items'
        else if (name === 'useRadarStore') value = '() => ({ ensureLoaded() {} })'
        else if (name === 'useMutations') value = '() => globalThis.__uiTest.mutations'
        else if (name === 'useSignal') value = '() => ({ tuneItem() {} })'
        else if (name === 'useTheme') value = '() => ({ mode: "light", accent: "blue", accents: [], set() {}, setAccent() {} })'
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
function reset() {
  globalThis.window = new EventTarget()
  globalThis.HTMLElement = class {}
  globalThis.document = { activeElement: null }
  globalThis.__uiTest = {
    ui: reactive({ activeItem: null, sidebarOpen: true, detailTab: 'analysis' }),
    items: reactive({ items: [], get visibleItems() { return this.items }, triageView: 'inbox', categories: [], stats: {}, loadItems() {} }),
    mutations: { quickIngest: async () => true, toggleStar() {}, toggleRead() {}, updateCategory() {} },
    api: {},
  }
  return globalThis.__uiTest
}

test('quick ingest preserves drafts on failure, prevents duplicates, and clears only on success', async () => {
  const ctx = reset()
  const pending = deferred()
  let calls = 0
  ctx.mutations.quickIngest = () => { calls++; return pending.promise }
  const view = mount((await loadSource('components/layout/AppHeader.vue')).default)
  try {
    view.state.quickUrl = '  https://example.test/article  '
    const submit = view.state.submitQuick()
    await view.state.submitQuick()
    assert.equal(calls, 1)
    pending.resolve(false)
    await submit
    assert.equal(view.state.quickUrl, '  https://example.test/article  ')
    assert.match(view.state.quickError, /內容已保留/)
    assert.equal(view.state.submitting, false)
  } finally { view.unmount() }
  ctx.mutations.quickIngest = async () => true
  const retry = mount((await loadSource('components/layout/AppHeader.vue')).default)
  try {
    retry.state.quickUrl = '保存的筆記'
    await retry.state.submitQuick()
    assert.equal(retry.state.quickUrl, '')
    assert.equal(retry.state.quickError, '')
  } finally { retry.unmount() }
})

test('quick ingest keeps the draft if its dependency rejects', async () => {
  const ctx = reset()
  ctx.mutations.quickIngest = async () => { throw new Error('offline') }
  const view = mount((await loadSource('components/layout/AppHeader.vue')).default)
  try {
    view.state.quickUrl = '離線筆記'
    await view.state.submitQuick()
    assert.equal(view.state.quickUrl, '離線筆記')
    assert.equal(view.state.submitting, false)
    assert.match(view.state.quickError, /重試/)
  } finally { view.unmount() }
})

test('mobile search expands before focusing the search input', async () => {
  reset()
  const view = mount((await loadSource('components/layout/AppHeader.vue')).default)
  let focused = false
  try {
    view.state.searchInput = { focus() { focused = true } }
    await view.state.focusSearchInput()
    assert.equal(view.state.showMobileSearch, true)
    assert.equal(focused, true)
  } finally { view.unmount() }
})

test('empty states distinguish first use, search, cleared inbox and load failure', async () => {
  const ctx = reset()
  Object.assign(ctx.items, { error: null, searchQuery: '', currentCategory: '全部', stats: { total: 0 } })
  const view = mount((await loadSource('components/items/ItemList.vue')).default)
  try {
    assert.equal(view.state.firstUse, true)
    assert.equal(view.state.emptyState.action, '新增筆記')
    ctx.items.searchQuery = '沒有結果的搜尋'
    assert.equal(view.state.firstUse, false)
    assert.equal(view.state.emptyState.action, '清除搜尋條件')
    view.state.recoverEmpty()
    assert.equal(ctx.items.searchQuery, '')
    assert.equal(ctx.ui.showNoteModal, undefined)
    ctx.items.stats.total = 5
    assert.equal(view.state.emptyState.title, '收件匣已清空')
    ctx.items.error = '連線中斷'
    assert.equal(view.state.emptyState.action, '重新載入')
    assert.equal(view.state.firstUse, false)
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
  let quick = 0, search = 0
  const view = mount({ setup() { useKeyboard(() => ({ focusQuickInput: () => quick++, focusSearchInput: () => search++ })); return {} } })
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
    key('n'); key('/')
    assert.equal(quick, 1)
    assert.equal(search, 1)
    key('n', { isComposing: true })
    assert.equal(quick, 1)
    ctx.items.items = [{ id: 9 }]
    document.activeElement = { tagName: 'BUTTON', closest: selector => selector === 'button, a' }
    key('Enter')
    assert.equal(ctx.ui.activeItem, null)
    key('j')
    assert.equal(ctx.ui.activeItem.id, 9)
    document.activeElement = null
    key('N')
    assert.equal(ctx.ui.showNoteModal, true)
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
