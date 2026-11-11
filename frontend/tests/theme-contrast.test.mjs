import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const css = await readFile(new URL('../src/assets/main.css', import.meta.url), 'utf8')
const blocks = [...css.matchAll(/([^{}]+)\{([^{}]*)\}/g)].map(([, selector, body]) => ({
  selector,
  tokens: Object.fromEntries([...body.matchAll(/--([\w-]+):\s*([^;]+);/g)].map(([, key, value]) => [key, value.trim()])),
}))
const color = value => value.startsWith('#')
  ? [1, 3, 5].map(start => parseInt(value.slice(start, start + 2), 16)).concat(1)
  : value.match(/[\d.]+/g).map(Number)
const over = (front, back) => front.slice(0, 3).map((value, index) => value * (front[3] ?? 1) + back[index] * (1 - (front[3] ?? 1))).concat(1)
const luminance = rgb => rgb.slice(0, 3).map(value => {
  const s = value / 255
  return s <= 0.04045 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4
}).reduce((sum, value, index) => sum + value * [0.2126, 0.7152, 0.0722][index], 0)
const contrast = (a, b) => (Math.max(luminance(a), luminance(b)) + 0.05) / (Math.min(luminance(a), luminance(b)) + 0.05)
function readable(foreground, background, label) {
  const ratio = contrast(foreground, background)
  assert.ok(ratio >= 4.5, `${label}: ${ratio.toFixed(2)}:1, expected >= 4.5:1`)
}

for (const mode of ['light', 'dark', 'oled']) {
  const surface = blocks.find(block => block.tokens.card && (
    mode === 'light' ? block.selector.trim().endsWith(':root') : block.selector.includes(`:root.${mode}`)
  )).tokens
  const card = color(surface.card)
  const background = color(surface.background)
  test(`${mode}: body and metadata text meet 4.5:1 on workspace surfaces`, () => {
    for (const name of ['foreground', 'muted-foreground', 'subtle-foreground']) {
      for (const base of [card, background, over(color(surface.muted), card)]) {
        readable(color(surface[name]), base, `${name} on ${mode}`)
      }
    }
  })
  for (const accent of ['blue', 'violet', 'emerald', 'amber', 'rose', 'zinc']) {
    const tokens = blocks.find(block => block.selector.includes(`[data-accent="${accent}"]`) && (block.selector.includes('.dark') === (mode !== 'light'))).tokens
    test(`${mode}/${accent}: primary buttons and selected labels meet 4.5:1`, () => {
      readable(color(tokens['primary-foreground']), color(tokens.primary), 'button')
      readable(color(tokens['primary-foreground']), color(tokens['primary-hover']), 'hovered button')
      readable(color(tokens['primary-soft-foreground']), over(color(tokens['primary-soft']), card), 'selected label')
    })
  }
}

// The cover wall's own tokens: page shell, cover backing, filled controls, read titles.
const light = blocks.find(block => block.tokens.card && block.selector.trim().endsWith(':root')).tokens
for (const mode of ['light', 'dark', 'oled', 'neutral']) {
  const own = mode === 'light' ? {} : blocks.find(block => block.tokens.card && block.selector.includes(`:root.${mode}`)).tokens
  // A theme inherits what it does not redefine; `--shell` defaults to that theme's card.
  const token = name => {
    const value = own[name] ?? light[name]
    return color(value.startsWith('var(') ? own[value.slice(6, -1)] ?? light[value.slice(6, -1)] : value)
  }
  test(`${mode}: wall text meets 4.5:1 on the shell, the cover backing and filled controls`, () => {
    for (const surface of ['shell', 'surface-1', 'surface-2', 'surface-3']) {
      readable(token('foreground'), token(surface), `title on ${surface}`)
      readable(token('muted-foreground'), token(surface), `meta on ${surface}`)
    }
    for (const surface of ['shell', 'surface-1']) readable(token('done-foreground'), token(surface), `read title on ${surface}`)
    readable(token('background'), token('foreground'), 'selected kind tab')
  })
}

test('neutral dark is the flat default: one accent, readable selection, no glass', async () => {
  const surface = blocks.find(block => block.tokens.card && block.selector.includes(':root.neutral')).tokens
  const accent = blocks.find(block => block.selector.includes(':root.neutral[data-accent="blue"]')).tokens
  assert.equal(surface.background, '#0f0f0f')
  assert.equal(accent.primary, '#60a5fa')
  readable(color(accent['primary-foreground']), color(accent.primary), 'primary button')
  readable(color(accent['primary-foreground']), color(accent['primary-hover']), 'hovered primary button')
  readable(color(accent['primary-soft-foreground']), color(accent['primary-soft']), 'selected label')
  readable(color(surface['selection-foreground']), color(surface.selection), 'selected text')
  assert.ok(contrast(color(accent.ring), color(surface.background)) >= 3, 'focus ring against the page')
  assert.match(css, /\.neutral \*,[^{]*\{[^}]*backdrop-filter: none !important/)
  // Starts in the neutral theme before the app loads, so there is no flash of another one.
  const html = await readFile(new URL('../index.html', import.meta.url), 'utf8')
  assert.match(html, /<html[^>]*class="dark neutral"/)
  assert.match(html, /name="theme-color" content="#0f0f0f"/)
})
