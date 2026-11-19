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

const { summarizeServiceStatus } = await load('../src/lib/serviceBanner.ts')

function ok(label) {
  return { ok: true, label }
}

function fail(label, extra = {}) {
  return { ok: false, label, ...extra }
}

test('returns null when status is absent or every service is healthy', () => {
  assert.equal(summarizeServiceStatus(null), null)
  assert.equal(
    summarizeServiceStatus({ services: { c1: ok('OpenAI') }, undecryptable: [], needs_setup: false }),
    null,
  )
})

test('lists connection names directly when 1 or 2 connections fail', () => {
  const one = summarizeServiceStatus({
    services: {
      c1: fail('OpenAI', { status: 401, hint: '金鑰已失效', action_required: true }),
      c2: ok('Gemini'),
    },
    undecryptable: [],
    needs_setup: false,
  })
  assert.equal(one.text, 'OpenAI 目前無法使用（OpenAI：金鑰已失效）。其他連線仍可備援。')
  assert.equal(one.detail, one.text)
  assert.equal(one.action, '前往處理')
  assert.equal(one.tab, 'ai')

  const two = summarizeServiceStatus({
    services: {
      c1: fail('連線 A', { message: 'timeout' }),
      c2: fail('連線 B', { status: 403, hint: '權限不足', action_required: true }),
    },
    undecryptable: [],
    needs_setup: false,
  })
  // action_required connection is promoted to lead the reason
  assert.equal(two.text, '連線 B、連線 A 目前無法使用（連線 B：權限不足）。')
  assert.equal(two.action, '前往處理')
})

test('collapses 3+ failing connections into a count while keeping full list in tooltip detail', () => {
  const many = summarizeServiceStatus({
    services: {
      c1: fail('連線 1', { status: 429, message: 'rate limited' }),
      c2: fail('連線 2', { status: 502 }),
      c3: fail('連線 3', { status: 401, hint: 'API Key 無效', action_required: true }),
      c4: ok('本機模型'),
    },
    undecryptable: [],
    needs_setup: false,
  })
  assert.equal(many.text, '有 3 條 AI 連線暫時無法使用（連線 3：API Key 無效）。其他連線仍可備援。')
  assert.ok(many.detail.includes('受影響連線：連線 3、連線 1、連線 2'))
  assert.equal(many.action, '前往處理')
})

test('prioritizes undecryptable keys and handles needs_setup', () => {
  const undec = summarizeServiceStatus({
    services: { c1: fail('OpenAI', { status: 401 }) },
    undecryptable: ['ai_connection:1'],
    needs_setup: false,
  })
  assert.match(undec.text, /有 1 個金鑰無法解密/)
  assert.equal(undec.tab, 'ai')

  const vapid = summarizeServiceStatus({
    services: {},
    undecryptable: ['VAPID_PRIVATE_KEY'],
    needs_setup: false,
  })
  assert.equal(vapid.tab, 'push-keys')

  const setup = summarizeServiceStatus({
    services: {},
    undecryptable: [],
    needs_setup: true,
  })
  assert.equal(setup.tab, 'wizard')
  assert.equal(setup.action, '開始設定')
})
