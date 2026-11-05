import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import ts from 'typescript'

const source = await readFile(new URL('../src/lib/settingsLink.ts', import.meta.url), 'utf8')
const { outputText } = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
})
const { readSettingsLink } = await import(`data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`)

test('the open_settings link names the tab and the card', () => {
  assert.deepEqual(readSettingsLink('#settings=ai&card=agnes'), { tab: 'ai', card: 'agnes' })
  assert.deepEqual(readSettingsLink('#settings=telegram'), { tab: 'telegram', card: '' })
})

test('other fragments and odd values open nothing', () => {
  assert.equal(readSettingsLink(''), null)
  assert.equal(readSettingsLink('#key=abc'), null)
  assert.equal(readSettingsLink('#settings=<script>'), null)
  assert.deepEqual(readSettingsLink('#settings=ai&card=a"b'), { tab: 'ai', card: '' })
})
