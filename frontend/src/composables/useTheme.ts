import { computed, watch } from 'vue'
import { useLocalStorage, usePreferredDark } from '@vueuse/core'

export type ThemeMode = 'dark' | 'oled' | 'light' | 'system'
export type AccentColor = 'blue' | 'violet' | 'emerald' | 'amber' | 'rose' | 'zinc'

export interface AccentOption {
  id: AccentColor
  label: string
  color: string
}

export const ACCENT_OPTIONS: AccentOption[] = [
  { id: 'blue', label: 'iOS 藍', color: '#0a84ff' },
  { id: 'violet', label: 'Linear 紫', color: '#5e6ad2' },
  { id: 'emerald', label: '極客綠', color: '#10b981' },
  { id: 'amber', label: '琥珀橘', color: '#f59e0b' },
  { id: 'rose', label: '洋紅', color: '#f43f5e' },
  { id: 'zinc', label: '極簡灰', color: '#71717a' },
]

const theme = useLocalStorage<ThemeMode>('omnikeep-theme', 'dark')
const accent = useLocalStorage<AccentColor>('omnikeep-accent', 'blue')
const systemDark = usePreferredDark()

export function isDark(): boolean {
  return (
    theme.value === 'dark' ||
    theme.value === 'oled' ||
    (theme.value === 'system' && systemDark.value)
  )
}

/** Sync <html> class + theme-color meta + data-accent with the resolved theme. */
function applyTheme() {
  const dark = isDark()
  const el = document.documentElement
  el.classList.toggle('dark', dark)
  el.classList.toggle('oled', theme.value === 'oled')
  el.setAttribute('data-accent', accent.value)

  const meta = document.querySelector<HTMLMetaElement>('meta[name="theme-color"]')
  if (meta) {
    if (theme.value === 'oled') meta.content = '#000000'
    else if (dark) meta.content = '#111216'
    else meta.content = '#f2f2f7'
  }
}

/** Initialize on app boot (idempotent). */
export function initTheme() {
  applyTheme()
  watch(() => [theme.value, accent.value, systemDark.value], applyTheme)
}

export function useTheme() {
  return {
    mode: theme,
    accent,
    accents: ACCENT_OPTIONS,
    resolved: computed<'dark' | 'light'>(() => (isDark() ? 'dark' : 'light')),
    isOled: computed(() => theme.value === 'oled'),
    toggle() {
      if (theme.value === 'dark') theme.value = 'oled'
      else if (theme.value === 'oled') theme.value = 'light'
      else theme.value = 'dark'
    },
    set(mode: ThemeMode) {
      theme.value = mode
    },
    setAccent(color: AccentColor) {
      accent.value = color
    },
  }
}
