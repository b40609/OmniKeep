import { defineConfig, minimal2023Preset } from '@vite-pwa/assets-generator/config'

// Regenerates the PWA icons next to public/favicon.svg: npm run generate-pwa-assets
// Maskable and Apple tiles are full-bleed: fill the padding with the icon's own blue
// (sharp's default is white). Padding 0.1 instead of 0.3 keeps the glyph about half
// the tile width, still inside the maskable safe zone (a circle of 80% diameter).
const tile = { padding: 0.1, resizeOptions: { background: '#007aff', fit: 'contain' } } as const

export default defineConfig({
  headLinkOptions: { preset: '2023' },
  preset: {
    ...minimal2023Preset,
    maskable: { ...minimal2023Preset.maskable, ...tile },
    apple: { ...minimal2023Preset.apple, ...tile },
  },
  images: ['public/favicon.svg'],
})
