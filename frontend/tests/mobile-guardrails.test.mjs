import assert from 'node:assert/strict'
import { readdir, readFile } from 'node:fs/promises'
import path from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

const FRONTEND_DIR = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const SRC_DIR = path.join(FRONTEND_DIR, 'src')

async function walk(dir) {
  const entries = await readdir(dir, { withFileTypes: true })
  const files = []
  for (const e of entries) {
    const full = path.join(dir, e.name)
    if (e.isDirectory()) files.push(...(await walk(full)))
    else if (/\.(vue|css|ts)$/.test(e.name)) files.push(full)
  }
  return files
}

test('no 100vh, h-screen, or background-attachment:fixed traps in frontend source', async () => {
  const files = await walk(SRC_DIR)
  const violations = []
  for (const file of files) {
    const rel = path.relative(FRONTEND_DIR, file).replace(/\\/g, '/')
    const lines = (await readFile(file, 'utf8')).split(/\r?\n/)
    lines.forEach((line, idx) => {
      if (/\b(?:100vh|h-screen)\b/.test(line) && !line.trim().startsWith('//') && !line.trim().startsWith('/*') && !line.trim().startsWith('*')) {
        violations.push(`${rel}:${idx + 1}: avoid raw 100vh / h-screen on iOS WebKit; use 100dvh or fixed inset-0`)
      }
      if (/background-attachment:\s*fixed|\bbg-fixed\b/.test(line)) {
        violations.push(`${rel}:${idx + 1}: background-attachment:fixed locks up iOS WebKit scrolling`)
      }
    })
  }
  assert.deepEqual(violations, [])
})

test('all touchstart listeners are passive and full-pane vertical scrollers carry .mobile-scroll', async () => {
  const files = await walk(SRC_DIR)
  const violations = []
  for (const file of files) {
    const rel = path.relative(FRONTEND_DIR, file).replace(/\\/g, '/')
    if (!rel.endsWith('.vue')) continue
    const lines = (await readFile(file, 'utf8')).split(/\r?\n/)
    lines.forEach((line, idx) => {
      if (/@touchstart(?!\.passive)/.test(line)) {
        violations.push(`${rel}:${idx + 1}: @touchstart must use .passive to avoid blocking iOS compositor scrolling`)
      }
      if (/\boverflow-y-auto\b/.test(line) && !/\bmobile-scroll\b/.test(line) && !/\bmax-h-/.test(line)) {
        violations.push(`${rel}:${idx + 1}: full-pane overflow-y-auto must include .mobile-scroll to prevent iOS scroll-chaining freezes`)
      }
      if (/env\(safe-area-inset-top\)/.test(line) && !/--safe-top/.test(line)) {
        violations.push(`${rel}:${idx + 1}: use var(--safe-top) or .safe-top instead of raw env(safe-area-inset-top)`)
      }
    })
  }
  assert.deepEqual(violations, [])
})

test('mobile inputs enforce >= 16px font-size to prevent iOS Safari auto-zoom', async () => {
  const mainCss = await readFile(path.join(SRC_DIR, 'assets/main.css'), 'utf8')
  assert.match(mainCss, /@media\s*\(max-width:\s*767px\)[\s\S]*?font-size:\s*max\(16px,\s*1(?:rem|em)\)\s*!important/)
})

test('Dialog preserves Reka UI modal and unmountOnHide defaults so backdrop overlay renders', async () => {
  const dialogVue = await readFile(path.join(SRC_DIR, 'components/ui/dialog/Dialog.vue'), 'utf8')
  assert.match(dialogVue, /modal:\s*true/)
  assert.match(dialogVue, /unmountOnHide:\s*true/)
})

test('mobile list rows hide inline action buttons and touch devices suppress keyboard cursor outline', async () => {
  const wallCss = await readFile(path.join(SRC_DIR, 'assets/wall.css'), 'utf8')
  assert.match(wallCss, /\.item-actions\.list-row__acts\s*\{\s*display:\s*none;/)
  assert.match(wallCss, /@media\s*\(hover:\s*none\)\s*\{\s*\.cover-card\.is-cursor\s*\{\s*outline:\s*none;/)
})

test('no sub-12px arbitrary font sizes in mobile UI components', async () => {
  const files = await walk(SRC_DIR)
  const violations = []
  for (const file of files) {
    const rel = path.relative(FRONTEND_DIR, file).replace(/\\/g, '/')
    if (!rel.endsWith('.vue')) continue
    const lines = (await readFile(file, 'utf8')).split(/\r?\n/)
    lines.forEach((line, idx) => {
      if (/\btext-\[1[01]px\]/.test(line)) {
        violations.push(`${rel}:${idx + 1}: avoid sub-12px font size (${line.trim()})`)
      }
    })
  }
  assert.deepEqual(violations, [])
})
