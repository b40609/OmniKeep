/* Web Push handlers, loaded into the Workbox service worker via importScripts.
 * Every push must show a notification: Safari revokes push permission for
 * sites that receive pushes without displaying one. */

self.addEventListener('push', (event) => {
  let data = {}
  try {
    data = event.data ? event.data.json() : {}
  } catch {
    data = { body: event.data ? event.data.text() : '' }
  }
  const url = typeof data.url === 'string' && data.url.startsWith('/') && !data.url.startsWith('//') ? data.url : '/'
  event.waitUntil(
    self.registration.showNotification(data.title || 'OmniKeep', {
      body: data.body || '',
      tag: data.tag || undefined,
      data: { url },
    }),
  )
})

self.addEventListener('notificationclick', (event) => {
  event.notification.close()
  const target = new URL(event.notification.data?.url || '/', self.location.origin).href
  event.waitUntil(
    (async () => {
      const windows = await self.clients.matchAll({ type: 'window', includeUncontrolled: true })
      const existing = windows.find((client) => new URL(client.url).origin === self.location.origin)
      if (existing) return existing.focus()
      return self.clients.openWindow(target)
    })(),
  )
})
