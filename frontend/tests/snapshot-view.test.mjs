import assert from 'node:assert/strict'
import { readFile, readdir } from 'node:fs/promises'
import test from 'node:test'
import ts from 'typescript'

async function load(path) {
  const source = await readFile(new URL(`../src/${path}`, import.meta.url), 'utf8')
  const { outputText } = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
  })
  return import(`data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`)
}
const read = (path) => readFile(new URL(`../src/${path}`, import.meta.url), 'utf8')

const { SNAPSHOT_SANDBOX, snapshotSrcdoc } = await load('lib/snapshot.ts')

test('the snapshot frame runs no scripts and is not same-origin', () => {
  const tokens = SNAPSHOT_SANDBOX.split(/\s+/)
  for (const token of ['allow-scripts', 'allow-same-origin', 'allow-forms', 'allow-top-navigation',
    'allow-top-navigation-by-user-activation', 'allow-modals', 'allow-downloads']) {
    assert.ok(!tokens.includes(token), token)
  }
  // Links still work: they open an ordinary new tab.
  assert.deepEqual(tokens.sort(), ['allow-popups', 'allow-popups-to-escape-sandbox'])
})

test('the saved page goes into the frame unchanged, with links opening in a new tab', () => {
  const saved = '<!DOCTYPE html><html><head><base href="https://site.example/"></head><body><a href="/x">x</a></body></html>'
  const srcdoc = snapshotSrcdoc(saved)
  assert.ok(srcdoc.startsWith('<base target="_blank">'))
  assert.ok(srcdoc.endsWith(saved))
  assert.equal(snapshotSrcdoc(''), '<base target="_blank">')
})

test('the dialog shows a snapshot only through the sandboxed frame', async () => {
  const dialog = await read('components/modals/SnapshotDialog.vue')
  const frame = dialog.match(/<iframe[^>]*>/s)?.[0] ?? ''
  assert.match(frame, /:sandbox="SNAPSHOT_SANDBOX"/)
  assert.match(frame, /:srcdoc="srcdoc"/)
  assert.match(frame, /referrerpolicy="no-referrer"/)
  assert.doesNotMatch(frame, /\ssrc=|:src=/)
  assert.equal(dialog.match(/<iframe/g).length, 1)
  assert.doesNotMatch(dialog, /v-html|innerHTML/)
})

test('snapshot HTML is never opened as a page of this origin', async () => {
  // A blob: or data: page made by this app has its origin, and with it the stored access key.
  const offenders = []
  async function walk(dir) {
    for (const entry of await readdir(dir, { withFileTypes: true })) {
      const url = new URL(entry.name + (entry.isDirectory() ? '/' : ''), dir)
      if (entry.isDirectory()) await walk(url)
      else if (/\.(vue|ts)$/.test(entry.name)) {
        const source = await readFile(url, 'utf8')
        if (/fetchSnapshotHtml|snapshotView/.test(source)
          && /createObjectURL|window\.open|location\.href\s*=|document\.write|v-html|innerHTML/.test(source)) offenders.push(entry.name)
      }
    }
  }
  await walk(new URL('../src/', import.meta.url))
  assert.deepEqual(offenders, [])
  assert.doesNotMatch(await read('lib/api.ts'), /openSnapshotInNewTab/)
})

test('opening a snapshot fetches it with the key and hands it to the dialog', async () => {
  const mutations = await read('composables/useMutations.ts')
  assert.match(mutations, /api\.fetchSnapshotHtml\(item\.id\)/)
  assert.match(mutations, /ui\.snapshotView = \{ title: item\.title_l1, url: item\.url, html \}/)
})
