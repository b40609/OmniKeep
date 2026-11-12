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

const { planAdd, describePlan, submitLabel, findLinks, isLink, isImportFile, isPastedLinks, explainFailure } = await load('../src/lib/addInput.ts')

test('text that is nothing but addresses is links: one per line or separated by spaces', () => {
  assert.deepEqual(planAdd('https://example.com/a'), { kind: 'links', urls: ['https://example.com/a'] })
  assert.deepEqual(planAdd('  https://example.com/a\nhttp://example.org/b?x=1#y  \n\n'), {
    kind: 'links', urls: ['https://example.com/a', 'http://example.org/b?x=1#y'],
  })
  assert.deepEqual(planAdd('https://a.example/1 https://b.example/2\thttps://c.example/3').urls.length, 3)
  // The same address twice is saved once.
  assert.deepEqual(planAdd('https://a.example/1\nhttps://a.example/1').urls, ['https://a.example/1'])
  // A comma or a full stop after an address is not part of it.
  assert.deepEqual(planAdd('https://a.example/1, https://b.example/2。'), {
    kind: 'links', urls: ['https://a.example/1', 'https://b.example/2'],
  })
})

test('anything else is a note, and a note with addresses in it stays a note unless told otherwise', () => {
  assert.deepEqual(planAdd('今天想到的事'), { kind: 'note', urls: [] })
  assert.deepEqual(planAdd('example.com 沒有協定，不當成連結'), { kind: 'note', urls: [] })
  assert.deepEqual(planAdd('ftp://example.com/file'), { kind: 'note', urls: [] })
  const mixed = '這篇不錯 https://example.com/post（還有 https://example.org/x）。'
  assert.deepEqual(planAdd(mixed), { kind: 'note', urls: ['https://example.com/post', 'https://example.org/x'] })
  assert.deepEqual(planAdd(mixed, null, { linksOnly: true }), { kind: 'links', urls: ['https://example.com/post', 'https://example.org/x'] })
  // 只收藏連結 does nothing when there is no address to save.
  assert.deepEqual(planAdd('只有文字', null, { linksOnly: true }), { kind: 'note', urls: [] })
  // Addresses alone can still be kept as one note.
  assert.deepEqual(planAdd('https://a.example/1\nhttps://b.example/2', null, { asNote: true }), {
    kind: 'note', urls: ['https://a.example/1', 'https://b.example/2'],
  })
})

test('nothing typed is nothing to send', () => {
  for (const blank of ['', '   ', '\n\t\n']) assert.deepEqual(planAdd(blank), { kind: 'empty' })
})

test('a bookmark file wins over the text; other files are refused before sending', () => {
  for (const name of ['bookmarks.html', 'Bookmarks.HTM', 'raindrop.json', 'pocket.CSV']) {
    assert.equal(isImportFile(name), true, name)
    assert.deepEqual(planAdd('https://example.com', { name }), { kind: 'file', name })
  }
  for (const name of ['photo.png', 'notes.txt', 'html', 'archive.html.zip']) {
    assert.equal(isImportFile(name), false, name)
    assert.deepEqual(planAdd('', { name }), { kind: 'unsupported', name })
  }
})

test('addresses are found whole: brackets that belong stay, sentence punctuation goes', () => {
  assert.deepEqual(findLinks('見 https://en.wikipedia.org/wiki/Rust_(programming_language)。'), ['https://en.wikipedia.org/wiki/Rust_(programming_language)'])
  assert.deepEqual(findLinks('(https://example.com/a)'), ['https://example.com/a'])
  assert.deepEqual(findLinks('「https://example.com/a」、https://example.com/b!'), ['https://example.com/a', 'https://example.com/b'])
  assert.deepEqual(findLinks('沒有連結'), [])
  assert.equal(isLink('https://example.com'), true)
  assert.equal(isLink('https://'), false)
  assert.equal(isLink('javascript:alert(1)'), false)
  assert.equal(isLink('example.com'), false)
})

test('the line under the box and the button say what sending will do', () => {
  assert.equal(describePlan(planAdd('https://example.com')), '會收藏 1 個連結')
  assert.equal(describePlan(planAdd('https://a.example https://b.example')), '會收藏 2 個連結，在背景依序讀取')
  assert.equal(describePlan(planAdd('一段筆記 https://example.com')), '會存成筆記')
  assert.equal(describePlan(planAdd('', { name: 'bookmarks.html' })), '會匯入 bookmarks.html')
  assert.match(describePlan(planAdd('', { name: 'photo.png' })), /不能匯入 photo\.png/)
  assert.equal(describePlan(planAdd('')), '')
  assert.equal(submitLabel(planAdd('https://example.com')), '收藏連結')
  assert.equal(submitLabel(planAdd('筆記')), '儲存筆記')
  assert.equal(submitLabel(planAdd('', { name: 'b.html' })), '匯入')
  assert.equal(submitLabel(planAdd('')), '新增')
})

test('a failure is explained in the panel\'s own words', () => {
  assert.equal(explainFailure('AI 分析失敗：金鑰無效。'), 'AI 分析失敗：金鑰無效')
  assert.equal(explainFailure('Invalid or non-public URL'), '這個網址不是公開的網頁，讀不到')
  assert.equal(explainFailure(''), '原因不明')
  assert.equal(explainFailure(undefined), '原因不明')
})

test('a paste on the page opens the panel only for addresses', () => {
  assert.equal(isPastedLinks('https://example.com/a\nhttps://example.com/b'), true)
  assert.equal(isPastedLinks('一段文字 https://example.com/a'), false)
  assert.equal(isPastedLinks('一段文字'), false)
  assert.equal(isPastedLinks(''), false)
})
