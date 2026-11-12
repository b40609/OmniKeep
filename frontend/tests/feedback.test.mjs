import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import ts from 'typescript'

async function load(path) {
  const source = await readFile(new URL(`../src/${path}`, import.meta.url), 'utf8')
  const { outputText } = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
  })
  return import(`data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`)
}

test('feedback link opens a new issue that carries the version and a no-secrets warning', async () => {
  const { feedbackUrl } = await load('lib/feedback.ts')
  const url = new URL(feedbackUrl('1.5.0'))
  assert.equal(url.origin + url.pathname, 'https://github.com/b40609/OmniKeep/issues/new')
  assert.match(url.searchParams.get('body'), /OmniKeep 1\.5\.0/)
  assert.match(url.searchParams.get('body'), /不要貼/)
})
