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
