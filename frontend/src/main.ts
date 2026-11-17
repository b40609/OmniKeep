import { createApp } from 'vue'
import { createPinia } from 'pinia'
import '@fontsource-variable/inter'
import '@fontsource-variable/jetbrains-mono'
import './assets/main.css'
import App from './App.vue'

// Remove the previous API cache, which predates mandatory authentication.
if ('caches' in window) {
  caches.delete('omnikeep-api-v1').catch(() => {})
}

const app = createApp(App)
app.use(createPinia())
app.mount('#app')

// PWA service worker — production only, scope '/' allowed via FastAPI header.
if (import.meta.env.PROD && 'serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker
      .register('/static/dist/sw.js', { scope: '/' })
      .catch((err) => console.warn('[OmniKeep PWA] SW registration failed:', err))
    // A newer worker took over a page an older worker served (e.g. one that still held the old precached
    // shell): reload once so the page is the new build, instead of asking the user to reload twice.
    const hadController = !!navigator.serviceWorker.controller
    let reloaded = false
    navigator.serviceWorker.addEventListener('controllerchange', () => {
      if (!hadController || reloaded) return
      reloaded = true
      window.location.reload()
    })
  })
}
