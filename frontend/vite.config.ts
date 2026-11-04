import { readFileSync } from 'node:fs'
import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import tailwindcss from '@tailwindcss/vite'
import { VitePWA } from 'vite-plugin-pwa'

// The repo-root VERSION file is the only place the version is written (the backend reads it too).
const appVersion = readFileSync(new URL('../VERSION', import.meta.url), 'utf8').trim()

// Served under FastAPI at /static/dist/ — all asset URLs must carry that base.
export default defineConfig({
  base: '/static/dist/',
  define: {
    __APP_VERSION__: JSON.stringify(appVersion),
  },
  plugins: [
    vue(),
    tailwindcss(),
    VitePWA({
      strategies: 'generateSW',
      registerType: 'autoUpdate',
      manifest: false,
      injectRegister: null,
      workbox: {
        globPatterns: ['index.html', '*.svg'],
        navigateFallback: '/static/dist/index.html',
        // Direct .html navigations hit the network; only extension-less
        // routes (e.g. "/") fall back to the SPA shell.
        navigateFallbackDenylist: [/\.html$/],
        cleanupOutdatedCaches: true,
        // Push/notificationclick handlers (public/push-sw.js), resolved next to sw.js.
        importScripts: ['push-sw.js'],
        runtimeCaching: [
          { urlPattern: /\/static\/dist\/assets\/.*/, handler: 'CacheFirst',
            options: { cacheName: 'omnikeep-assets-v2', expiration: { maxEntries: 80 } } },
          {
            urlPattern: /\/api\/.*/i,
            handler: 'NetworkOnly',
          },
        ],
      },
    }),
  ],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': { target: 'http://127.0.0.1:5000', changeOrigin: true },
      '/static': { target: 'http://127.0.0.1:5000', changeOrigin: true },
      '/mcp': { target: 'http://127.0.0.1:5000', changeOrigin: true },
    },
  },
  build: {
    outDir: '../static/dist',
    // Outside the Vite root, so Vite would leave files from older builds behind; the
    // '*.svg' precache glob then lists one the server no longer serves, and a single
    // precache 404 stops the service worker from installing.
    emptyOutDir: true,
    target: 'es2022',
  },
})
