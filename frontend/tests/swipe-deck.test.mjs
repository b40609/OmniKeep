import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import ts from 'typescript'

const source = await readFile(new URL('../src/lib/api.ts', import.meta.url), 'utf8')
const { outputText } = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
})
const api = await import(`data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`)
globalThis.window = new EventTarget()

function captureFetch(responseBody, status = 200) {
  const calls = []
  globalThis.fetch = async (url, init) => {
    calls.push({ url, method: init?.method || 'GET', headers: init?.headers || {}, body: init?.body ? JSON.parse(init.body) : null })
    return new Response(JSON.stringify(responseBody), { status })
  }
  return calls
}

test('getSwipeDeck reads the deck with Bearer auth and a default limit of 50', async () => {
  api.setApiKey('deck-token')
  const calls = captureFetch({ count: 1, items: [{ id: 'abc123def456', title_l1: 'T', reasons: ['🎯 興趣 LLM'], is_exploration: false }] })

  const deck = await api.getSwipeDeck()
  assert.equal(calls[0].url, '/api/behavior/deck?limit=50')
  assert.equal(calls[0].method, 'GET')
  assert.equal(calls[0].headers.Authorization, 'Bearer deck-token')
  assert.equal(deck.count, 1)
  assert.deepEqual(deck.items[0].reasons, ['🎯 興趣 LLM'])

  await api.getSwipeDeck(5)
  assert.equal(calls[1].url, '/api/behavior/deck?limit=5')
})

// Telegram /deck buttons: 👍 swipe_up, ⭐ swipe_star, 💤 snooze, 👎 swipe_down (app/bot/telegram_bot.py).
for (const action of ['swipe_up', 'swipe_down', 'swipe_star', 'snooze']) {
  test(`recordSwipe posts ${action} as a behavior event from the PWA`, async () => {
    api.setApiKey('deck-token')
    const calls = captureFetch({ success: true, id: 7, event_type: action, duplicate: false })

    const res = await api.recordSwipe('abc123def456', action)
    assert.equal(calls.length, 1)
    assert.equal(calls[0].url, '/api/behavior/event')
    assert.equal(calls[0].method, 'POST')
    assert.equal(calls[0].headers.Authorization, 'Bearer deck-token')
    assert.deepEqual(calls[0].body, { event_type: action, item_id: 'abc123def456', source: 'pwa' })
    assert.equal(res.event_type, action)
  })
}

test('recordSwipe sends numeric ids as strings and passes duplicate decisions through', async () => {
  api.setApiKey('deck-token')
  const calls = captureFetch({ success: true, id: 3, event_type: 'swipe_up', duplicate: true })
  const res = await api.recordSwipe(42, 'swipe_up')
  assert.equal(calls[0].body.item_id, '42')
  assert.equal(res.duplicate, true)
})

test('recordSwipe surfaces the backend detail for a removed item', async () => {
  api.setApiKey('deck-token')
  captureFetch({ detail: 'Unknown item' }, 404)
  await assert.rejects(api.recordSwipe('gone00000000', 'swipe_down'), /Unknown item/)
})
