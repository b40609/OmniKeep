import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import ts from 'typescript'

const source = await readFile(new URL('../src/lib/updateCheck.ts', import.meta.url), 'utf8')
const js = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } }).outputText
const { entryOf } = await import('data:text/javascript,' + encodeURIComponent(js))

test('the entry script is read from a built page shell', () => {
  const html = '<script>window.x=1</script>\n<script type="module" crossorigin src="/static/dist/assets/index-D2BTyoee.js"></script>\n<link rel="modulepreload" href="/static/dist/assets/vendor-abc.js">'
  assert.equal(entryOf(html), '/static/dist/assets/index-D2BTyoee.js')
})

test('a shell without a built entry gives nothing to compare', () => {
  assert.equal(entryOf('<script type="module" src="/src/main.ts"></script>'), '')
})
