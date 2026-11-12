import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import ts from 'typescript'

async function load(path) {
  const source = await readFile(new URL(path, import.meta.url), 'utf8')
  const { outputText } = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
  })
  return import(`data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`)
}

const { buildRows, groupRows, keyAction, matchesEntry } = await load('../src/lib/omnibox.ts')

const ENTRIES = [
  { id: 'add', group: 'action', label: '新增', hint: 'N', keywords: ['連結', '筆記', '匯入'] },
  { id: 'view-starred', group: 'filter', label: '加星', hint: '3 則' },
  { id: 'view-inbox', group: 'filter', label: '收件匣', keywords: ['未封存'] },
  { id: 'kind-video', group: 'filter', label: '影片', hint: '類型' },
  { id: 'cat-1', group: 'filter', label: 'Rust', hint: '分類　12 則' },
  { id: 'settings', group: 'action', label: '設定' },
  { id: 'theme', group: 'action', label: '切換主題', quiet: true },
  { id: 'cat-9', group: 'filter', label: '冷門', quiet: true },
]
const ids = rows => rows.map(row => row.id)

test('an empty box lists the filters, then the actions; quiet ones wait until something is typed', () => {
  const rows = buildRows('', 'search', ENTRIES)
  assert.deepEqual(ids(rows), ['view-starred', 'view-inbox', 'kind-video', 'cat-1', 'add', 'settings'])
  assert.deepEqual(groupRows(rows).map(s => [s.label, s.rows.length]), [['篩選', 4], ['動作', 2]])
  assert.deepEqual(buildRows('   ', 'search', ENTRIES).length, 6)
  assert.deepEqual(ids(buildRows('主題', 'search', ENTRIES)), ['search', 'ask', 'theme'])
  assert.deepEqual(ids(buildRows('冷門', 'search', ENTRIES)), ['search', 'ask', 'cat-9'])
})

test('typing puts search first and asking second, then what matches', () => {
  const rows = buildRows(' rust ', 'search', ENTRIES)
  assert.deepEqual(ids(rows), ['search', 'ask', 'cat-1'])
  assert.deepEqual(rows[0], { kind: 'search', id: 'search', text: 'rust' })
  assert.deepEqual(rows[1], { kind: 'ask', id: 'ask', text: 'rust' })
  // A question is still a search by default: nothing guesses from the wording.
  assert.equal(buildRows('Rust 的所有權是什麼？', 'search', ENTRIES)[0].kind, 'search')
  // Sections keep each row's place in the flat list the arrow keys walk.
  const sections = groupRows(buildRows('筆記', 'search', ENTRIES))
  assert.deepEqual(sections.map(s => s.label), ['', '動作'])
  assert.deepEqual(sections[1].rows.map(r => [r.row.id, r.index]), [['add', 2]])
})

test('entries are found by label, hint and older names', () => {
  const find = q => ids(buildRows(q, 'search', ENTRIES)).slice(2)
  assert.deepEqual(find('未封存'), ['view-inbox'])
  assert.deepEqual(find('類型'), ['kind-video'])
  assert.deepEqual(find('分類'), ['cat-1'])
  assert.deepEqual(find('匯入'), ['add'])
  assert.deepEqual(find('沒有這個'), [])
  assert.equal(matchesEntry(ENTRIES[4], 'RUST'), true)
  assert.equal(matchesEntry(ENTRIES[4], ''), true)
})

test('ask mode lists the question first and the way back to search, and nothing while empty', () => {
  assert.deepEqual(buildRows('', 'ask', ENTRIES), [])
  assert.deepEqual(ids(buildRows('設定怎麼改', 'ask', ENTRIES)), ['ask', 'search'])
})

test('arrow keys wrap, Enter runs the highlighted row, Esc closes', () => {
  const rows = buildRows('rust', 'search', ENTRIES)
  const state = (index, extra = {}) => ({ rows, index, mode: 'search', text: 'rust', ...extra })
  assert.deepEqual(keyAction({ key: 'ArrowDown' }, state(0)), { type: 'move', index: 1 })
  assert.deepEqual(keyAction({ key: 'ArrowDown' }, state(2)), { type: 'move', index: 0 })
  assert.deepEqual(keyAction({ key: 'ArrowUp' }, state(0)), { type: 'move', index: 2 })
  assert.deepEqual(keyAction({ key: 'Enter' }, state(0)), { type: 'run', index: 0 })
  assert.deepEqual(keyAction({ key: 'Enter' }, state(2)), { type: 'run', index: 2 })
  assert.deepEqual(keyAction({ key: 'Escape' }, state(1)), { type: 'close' })
  assert.equal(keyAction({ key: 'a' }, state(0)), null)
  // Nothing listed: the keys are left to the browser.
  const empty = { rows: [], index: 0, mode: 'ask', text: '' }
  assert.equal(keyAction({ key: 'ArrowDown' }, empty), null)
  assert.equal(keyAction({ key: 'Enter' }, empty), null)
})

test('asking is always explicit: Tab picks the row, Ctrl/Cmd+Enter sends, plain Enter searches', () => {
  const rows = buildRows('rust 是什麼', 'search', ENTRIES)
  const state = { rows, index: 0, mode: 'search', text: 'rust 是什麼' }
  assert.deepEqual(keyAction({ key: 'Enter' }, state), { type: 'run', index: 0 })
  assert.equal(rows[0].kind, 'search')
  assert.deepEqual(keyAction({ key: 'Tab' }, state), { type: 'move', index: 1 })
  assert.equal(rows[1].kind, 'ask')
  assert.deepEqual(keyAction({ key: 'Enter', ctrlKey: true }, state), { type: 'ask' })
  assert.deepEqual(keyAction({ key: 'Enter', metaKey: true }, state), { type: 'ask' })
  // Tab is the browser's again once the row is picked, with Shift, or with nothing typed.
  assert.equal(keyAction({ key: 'Tab' }, { ...state, index: 1 }), null)
  assert.equal(keyAction({ key: 'Tab', shiftKey: true }, state), null)
  assert.equal(keyAction({ key: 'Tab' }, { rows: buildRows('', 'search', ENTRIES), index: 0, mode: 'search', text: '' }), null)
  assert.equal(keyAction({ key: 'Enter', ctrlKey: true }, { rows: [], index: 0, mode: 'search', text: '  ' }), null)
})

test('in ask mode Enter asks, and Backspace on an empty box goes back to search', () => {
  const rows = buildRows('問題', 'ask', ENTRIES)
  assert.deepEqual(keyAction({ key: 'Enter' }, { rows, index: 0, mode: 'ask', text: '問題' }), { type: 'run', index: 0 })
  assert.equal(rows[0].kind, 'ask')
  assert.equal(keyAction({ key: 'Tab' }, { rows, index: 0, mode: 'ask', text: '問題' }), null)
  assert.equal(keyAction({ key: 'Backspace' }, { rows, index: 0, mode: 'ask', text: '問題' }), null)
  assert.deepEqual(keyAction({ key: 'Backspace' }, { rows: [], index: 0, mode: 'ask', text: '' }), { type: 'leave-ask' })
  assert.equal(keyAction({ key: 'Backspace' }, { rows: [], index: 0, mode: 'search', text: '' }), null)
})
