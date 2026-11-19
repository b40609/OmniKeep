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

const { displayCategory } = await load('../src/lib/format.ts')

test('displayCategory maps Inbox and empty values to 收件匣 and preserves other names', () => {
  assert.equal(displayCategory('Inbox'), '收件匣')
  assert.equal(displayCategory('  Inbox  '), '收件匣')
  assert.equal(displayCategory(''), '收件匣')
  assert.equal(displayCategory(null), '收件匣')
  assert.equal(displayCategory(undefined), '收件匣')
  assert.equal(displayCategory('AI 與開發'), 'AI 與開發')
  assert.equal(displayCategory('開發工具', '其他'), '開發工具')
  assert.equal(displayCategory('', '未分類'), '未分類')
})
