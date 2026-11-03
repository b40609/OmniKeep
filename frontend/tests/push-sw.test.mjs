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

test('clicking focuses an open OmniKeep window, otherwise opens one', async () => {
  let focused = 0
  const open = loadWorker({ windows: [{ url: 'https://desktop.tailnet-name.ts.net/', focus: async () => { focused++ } }] })
  let closed = false
  const click = (h) => {
    const pending = []
    h.notificationclick({ notification: { close: () => { closed = true }, data: { url: '/' } }, waitUntil: (p) => pending.push(p) })
    return Promise.all(pending)
  }
  await click(open.handlers)
  assert.equal(closed, true)
  assert.equal(focused, 1)
  assert.deepEqual(open.opened, [])

  const none = loadWorker({ windows: [{ url: 'https://other.example/', focus: async () => { focused++ } }] })
  await click(none.handlers)
  assert.deepEqual(none.opened, ['https://desktop.tailnet-name.ts.net/'])
  assert.equal(focused, 1)
})
