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

const api = await load('../src/lib/api.ts')
const push = await load('../src/lib/push.ts')
globalThis.window = new EventTarget()

function captureFetch(responseBody, status = 200) {
  const calls = []
  globalThis.fetch = async (url, init) => {
    calls.push({ url, method: init?.method || 'GET', headers: init?.headers || {}, body: init?.body ? JSON.parse(init.body) : null })
    return new Response(JSON.stringify(responseBody), { status })
  }
  return calls
}

test('getPushConfig reads the server VAPID key with Bearer auth', async () => {
  api.setApiKey('push-token')
  const calls = captureFetch({ configured: true, public_key: 'BPub', subscriptions: 2 })
  const cfg = await api.getPushConfig()
  assert.equal(calls[0].url, '/api/push/config')
  assert.equal(calls[0].method, 'GET')
  assert.equal(calls[0].headers.Authorization, 'Bearer push-token')
  assert.deepEqual(cfg, { configured: true, public_key: 'BPub', subscriptions: 2 })
})

test('subscribePush sends only endpoint and keys from PushSubscription.toJSON()', async () => {
  api.setApiKey('push-token')
  const calls = captureFetch({ success: true })
  await api.subscribePush({ endpoint: 'https://fcm.googleapis.com/fcm/send/x', expirationTime: null, keys: { p256dh: 'P', auth: 'A' } })
  assert.equal(calls[0].url, '/api/push/subscribe')
  assert.equal(calls[0].method, 'POST')
  assert.deepEqual(calls[0].body, { endpoint: 'https://fcm.googleapis.com/fcm/send/x', keys: { p256dh: 'P', auth: 'A' } })
})

test('unsubscribePush and sendTestPush hit their endpoints', async () => {
  api.setApiKey('push-token')
  let calls = captureFetch({ success: true, removed: true })
  const removed = await api.unsubscribePush('https://fcm.googleapis.com/fcm/send/x')
  assert.equal(calls[0].url, '/api/push/unsubscribe')
  assert.equal(calls[0].method, 'POST')
  assert.deepEqual(calls[0].body, { endpoint: 'https://fcm.googleapis.com/fcm/send/x' })
  assert.equal(removed.removed, true)

  calls = captureFetch({ success: true, sent: 1, removed: 0, failed: 0 })
  const res = await api.sendTestPush()
  assert.equal(calls[0].url, '/api/push/test')
  assert.equal(calls[0].method, 'POST')
  assert.equal(res.sent, 1)
})

test('a server without VAPID keys surfaces its 503 detail', async () => {
  api.setApiKey('push-token')
  captureFetch({ detail: 'Web Push is not configured (VAPID keys missing)' }, 503)
  await assert.rejects(api.sendTestPush(), /not configured/)
})

test('urlBase64ToUint8Array decodes unpadded base64url VAPID keys', () => {
  const bytes = Uint8Array.from({ length: 65 }, (_, i) => (i * 37 + 4) % 256)
  const b64url = Buffer.from(bytes).toString('base64url')
  assert.ok(!b64url.includes('=') && !b64url.includes('+') && !b64url.includes('/'))
  assert.deepEqual(push.urlBase64ToUint8Array(b64url), bytes)
})

test('sameKey compares a subscription key buffer with the server key', () => {
  const key = Uint8Array.from([4, 1, 2, 3])
  assert.equal(push.sameKey(Uint8Array.from([4, 1, 2, 3]).buffer, key), true)
  assert.equal(push.sameKey(Uint8Array.from([4, 1, 2, 9]).buffer, key), false)
  assert.equal(push.sameKey(null, key), false)
})

function fakeEnv({ ua, platform = 'Win32', touch = 0, standalone = false, push = true }) {
  const nav = { userAgent: ua, platform, maxTouchPoints: touch, ...(push ? { serviceWorker: {} } : {}) }
  const win = {
    matchMedia: (q) => ({ matches: q === '(display-mode: standalone)' && standalone }),
    ...(push ? { PushManager: function () {}, Notification: function () {} } : {}),
  }
  return [nav, win]
}

test('pushEnvironment asks iPhone and iPad Safari users to add to Home Screen first', () => {
  const iphone = 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Version/18.0 Mobile/15E148 Safari/604.1'
  assert.deepEqual(push.pushEnvironment(...fakeEnv({ ua: iphone, push: false })), { supported: false, iosNeedsInstall: true })
  assert.deepEqual(push.pushEnvironment(...fakeEnv({ ua: iphone, standalone: true })), { supported: true, iosNeedsInstall: false })
  // iPadOS reports a Mac user agent; touch points give it away.
  const ipad = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 Version/18.0 Safari/605.1.15'
  assert.equal(push.pushEnvironment(...fakeEnv({ ua: ipad, platform: 'MacIntel', touch: 5 })).iosNeedsInstall, true)
  assert.equal(push.pushEnvironment(...fakeEnv({ ua: ipad, platform: 'MacIntel', touch: 0 })).iosNeedsInstall, false)
  const chrome = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/141.0 Safari/537.36'
  assert.deepEqual(push.pushEnvironment(...fakeEnv({ ua: chrome })), { supported: true, iosNeedsInstall: false })
})
