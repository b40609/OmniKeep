import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import vm from 'node:vm'

const source = await readFile(new URL('../public/push-sw.js', import.meta.url), 'utf8')

/** Run push-sw.js against a fake service worker global and return its handlers. */
function loadWorker({ windows = [] } = {}) {
  const handlers = {}
  const shown = []
  const opened = []
  const self = {
    location: { origin: 'https://desktop.tailnet-name.ts.net' },
    addEventListener: (type, fn) => { handlers[type] = fn },
    registration: { showNotification: async (title, options) => shown.push({ title, options }) },
    clients: {
      matchAll: async () => windows,
      openWindow: async (url) => opened.push(url),
    },
  }
  vm.runInNewContext(source, { self, URL })
  return { handlers, shown, opened }
}

function pushEvent(data) {
  const pending = []
  return {
    data: data === undefined ? null : {
      json: () => (typeof data === 'string' ? JSON.parse(data) : data),
      text: () => (typeof data === 'string' ? data : JSON.stringify(data)),
    },
    waitUntil: (p) => pending.push(p),
    settle: () => Promise.all(pending),
  }
}

test('every push shows a notification (Safari revokes permission otherwise)', async () => {
  const { handlers, shown } = loadWorker()
  const event = pushEvent({ title: '📰 晨間戰報', body: '• 第一則', url: '/', tag: 'radar-digest' })
  handlers.push(event)
  await event.settle()
  // Objects built inside the vm context have foreign prototypes; compare as plain data.
  assert.deepEqual(JSON.parse(JSON.stringify(shown)), [
    { title: '📰 晨間戰報', options: { body: '• 第一則', tag: 'radar-digest', data: { url: '/' } } },
  ])

  const empty = pushEvent(undefined)
  handlers.push(empty)
  await empty.settle()
  assert.equal(shown[1].title, 'OmniKeep')

  const text = pushEvent('not json')
  handlers.push(text)
  await text.settle()
  assert.equal(shown[2].options.body, 'not json')
})

test('click targets are forced back onto this origin', async () => {
  const { handlers, shown } = loadWorker()
  for (const url of ['https://evil.example/', '//evil.example/', '/?view=deck']) {
    const event = pushEvent({ title: 't', url })
    handlers.push(event)
    await event.settle()
  }
  assert.deepEqual(shown.map((s) => s.options.data.url), ['/', '/', '/?view=deck'])
})

test('clicking hands the link to an open OmniKeep window, otherwise opens one at it', async () => {
  let focused = 0
  const posted = []
  const appWindow = (url) => ({ url, focus: async () => { focused++ }, postMessage: (m) => posted.push(m) })
  const open = loadWorker({ windows: [appWindow('https://desktop.tailnet-name.ts.net/')] })
  let closed = false
  const click = (h, url) => {
    const pending = []
    h.notificationclick({ notification: { close: () => { closed = true }, data: { url } }, waitUntil: (p) => pending.push(p) })
    return Promise.all(pending)
  }
  await click(open.handlers, '/?open=proposals')
  assert.equal(closed, true)
  assert.equal(focused, 1)
  assert.deepEqual(open.opened, [])
  // Same message type as OPEN_LINK_MESSAGE in src/lib/push.ts, which App.vue listens for.
  assert.deepEqual(JSON.parse(JSON.stringify(posted)), [
    { type: 'omnikeep-open-link', url: 'https://desktop.tailnet-name.ts.net/?open=proposals' },
  ])

  const none = loadWorker({ windows: [appWindow('https://other.example/')] })
  await click(none.handlers, '/?open=proposals')
  assert.deepEqual(none.opened, ['https://desktop.tailnet-name.ts.net/?open=proposals'])
  assert.equal(focused, 1)
  assert.equal(posted.length, 1)
})
