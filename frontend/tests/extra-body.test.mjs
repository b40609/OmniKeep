import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import ts from 'typescript'

const source = await readFile(new URL('../src/lib/extraBody.ts', import.meta.url), 'utf8')
const { outputText } = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
})
const lib = await import(`data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`)

// The shape of app/provider_catalog.py cards, trimmed to what the field reads.
const DS = 'deepseek-ai/deepseek-v4.1-flash'
const NV_OFF = { chat_template_kwargs: { thinking: false } }
const NVIDIA = { caps: { json_mode: true }, model_extra_body: { [DS]: NV_OFF } }
const KILO = { caps: { extra_body: { reasoning: { effort: 'low' } } } }

test('parseExtraBody accepts an object or nothing and refuses the rest', () => {
  assert.deepEqual(lib.parseExtraBody('  '), { ok: true, value: {} })
  assert.deepEqual(lib.parseExtraBody('{"top_k": 5}'), { ok: true, value: { top_k: 5 } })
  assert.equal(lib.parseExtraBody('{top_k: 5}').ok, false)
  assert.equal(lib.parseExtraBody('[1, 2]').ok, false)
  assert.equal(lib.parseExtraBody('"thinking off"').ok, false)
  const core = lib.parseExtraBody('{"model": "x", "messages": []}')
  assert.equal(core.ok, false)
  assert.match(core.error, /model、messages/)
  assert.equal(lib.parseExtraBody(JSON.stringify({ x: 'y'.repeat(3000) })).ok, false)
})

test('formatExtraBody leaves the field empty when there is nothing to send', () => {
  assert.equal(lib.formatExtraBody(undefined), '')
  assert.equal(lib.formatExtraBody({}), '')
  assert.equal(lib.formatExtraBody(NV_OFF), '{"chat_template_kwargs":{"thinking":false}}')
})

test('picking a model with a preset fills it, and leaving puts back the card default', () => {
  assert.deepEqual(lib.autoExtraBody(NVIDIA, DS), NV_OFF)
  assert.deepEqual(lib.autoExtraBody(NVIDIA, 'minimaxai/minimax-m3.1-flash'), {})
  assert.deepEqual(lib.autoExtraBody(KILO, 'kilo-auto/free'), KILO.caps.extra_body)
  const filled = lib.extraBodyAfterModelChange(NVIDIA, 'minimaxai/minimax-m3.1-flash', DS, '')
  assert.deepEqual(JSON.parse(filled), NV_OFF)
  assert.equal(lib.extraBodyAfterModelChange(NVIDIA, DS, 'minimaxai/minimax-m3.1-flash', filled), '')
})

test('text typed by hand survives a model change', () => {
  const typed = '{"top_k": 5}'
  assert.equal(lib.extraBodyAfterModelChange(NVIDIA, 'minimaxai/minimax-m3.1-flash', DS, typed), typed)
  assert.equal(lib.extraBodyAfterModelChange(NVIDIA, DS, 'other', '{broken'), '{broken')
})
