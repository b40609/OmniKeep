import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import vm from 'node:vm'
import ts from 'typescript'

async function load(path) {
  const source = await readFile(new URL(path, import.meta.url), 'utf8')
  const { outputText } = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
  })
  return import(`data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`)
}

const clip = await load('../src/lib/bookmarklet.ts')
const api = await load('../src/lib/api.ts')
globalThis.window = new EventTarget()

const ORIGIN = 'https://desktop.tailnet-name.ts.net'

/** Click the bookmarklet on a fake page; return the URL it opens OmniKeep at. */
function clipPage({ href = 'https://example.com/post?id=7#top', title, meta = {} }) {
  const opened = []
  const document = {
    querySelector(selector) {
      if (selector === 'title') return title === undefined ? null : { textContent: title }
      const key = selector.match(/\[(?:name|property)='([^']+)'\]/)?.[1]
      return key in meta ? { getAttribute: () => meta[key] } : null
    },
  }
  const window = { location: { href }, open: (url, target, features) => opened.push({ url, target, features }) }
  const code = clip.bookmarkletHref(ORIGIN)
  assert.ok(code.startsWith('javascript:'))
  vm.runInNewContext(code.slice('javascript:'.length), { window, document, encodeURIComponent })
  assert.equal(opened.length, 1)
  return opened[0]
}

test('the bookmarklet carries the page title and description through to OmniKeep', () => {
  const { url, target, features } = clipPage({
    title: '  C++ & Rust #1 — 記憶體安全  ',
    meta: { description: 'a=b&c "quoted" 100% 中文', 'og:title': 'ignored when <title> exists' },
  })
  assert.equal(new URL(url).origin, ORIGIN)
  assert.equal(target, '_blank')
  assert.match(features, /width=520/)
  assert.deepEqual(clip.readClipRequest(new URL(url).search), {
    url: 'https://example.com/post?id=7#top',
    title: 'C++ & Rust #1 — 記憶體安全',
    description: 'a=b&c "quoted" 100% 中文',
    autoClose: true,
  })
})

test('Open Graph tags stand in when the page has no <title> or description', () => {
  const { url } = clipPage({ meta: { 'og:title': 'OG 標題', 'og:description': 'OG 描述' } })
  const request = clip.readClipRequest(new URL(url).search)
  assert.equal(request.title, 'OG 標題')
  assert.equal(request.description, 'OG 描述')

  const bare = clip.readClipRequest(new URL(clipPage({}).url).search)
  assert.equal(bare.title, '')
  assert.equal(bare.description, '')
})

test('readClipRequest needs a url and accepts older links without title or description', () => {
  assert.equal(clip.readClipRequest('?open=proposals'), null)
  assert.deepEqual(clip.readClipRequest('?url=https%3A%2F%2Fexample.com%2F&auto_close'), {
    url: 'https://example.com/', title: '', description: '', autoClose: true,
  })
  assert.equal(clip.readClipRequest('?url=https%3A%2F%2Fexample.com%2F').autoClose, false)
})

test('ingest sends the page hints only when the bookmarklet supplied them', async () => {
  api.setApiKey('clip-token')
  const bodies = []
  globalThis.fetch = async (url, init) => {
    bodies.push({ url, body: JSON.parse(init.body) })
    return new Response(JSON.stringify({ success: true }))
  }
  await api.ingest('https://example.com/', { pageTitle: '瀏覽器標題', pageDescription: '瀏覽器描述' })
  await api.ingest('https://example.com/', { pageTitle: '', pageDescription: '' })
  assert.equal(bodies[0].url, '/api/ingest')
  assert.deepEqual(bodies[0].body, {
    content: 'https://example.com/', category: null, async_mode: false,
    page_title: '瀏覽器標題', page_description: '瀏覽器描述',
  })
  assert.deepEqual(bodies[1].body, { content: 'https://example.com/', category: null, async_mode: false })
})
