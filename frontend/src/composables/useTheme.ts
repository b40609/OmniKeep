import { computed, watch } from 'vue'
import { useLocalStorage, usePreferredDark } from '@vueuse/core'
import { LEGACY_THEME_KEY, THEME_KEY, startingTheme, themeClasses, themeColor, type ThemeMode } from '@/lib/themeMode'

export type { ThemeMode }
export type AccentColor = 'blue' | 'violet' | 'emerald' | 'amber' | 'rose' | 'zinc'

export interface AccentOption {
  id: AccentColor
  label: string
  color: string
}

export const ACCENT_OPTIONS: AccentOption[] = [
  { id: 'blue', label: '藍色', color: '#0065d1' },
  { id: 'violet', label: '紫色', color: '#4f5bc4' },
  { id: 'emerald', label: '綠色', color: '#047857' },
  { id: 'amber', label: '琥珀橘', color: '#f59e0b' },
  { id: 'rose', label: '洋紅', color: '#f43f5e' },
  { id: 'zinc', label: '石墨', color: '#71717a' },
]

export const THEME_LABELS: Record<ThemeMode, string> = {
  neutral: '中性深色',
  dark: '深藍灰',
  oled: 'OLED 純黑',
  light: '淺色',
  system: '跟隨系統',
}

function readStored(key: string): string | null {
  try {
    return localStorage.getItem(key)
  } catch {
    return null
  }
}

// The neutral theme is the default; a theme picked before it existed is carried over once.
const theme = useLocalStorage<ThemeMode>(THEME_KEY, startingTheme(readStored(THEME_KEY), readStored(LEGACY_THEME_KEY)))
const accent = useLocalStorage<AccentColor>('omnikeep-accent', 'blue')
const systemDark = usePreferredDark()

export function isDark(): boolean {
  return themeClasses(theme.value, systemDark.value).dark
}

/** Sync <html> class + theme-color meta + data-accent with the resolved theme. */
function applyTheme() {
  const classes = themeClasses(theme.value, systemDark.value)
  const el = document.documentElement
  el.classList.toggle('dark', classes.dark)
  el.classList.toggle('oled', classes.oled)
  el.classList.toggle('neutral', classes.neutral)
  el.setAttribute('data-accent', accent.value)

  const meta = document.querySelector<HTMLMetaElement>('meta[name="theme-color"]')
  if (meta) meta.content = themeColor(theme.value, systemDark.value)
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
    labels: THEME_LABELS,
    resolved: computed<'dark' | 'light'>(() => (isDark() ? 'dark' : 'light')),
    isOled: computed(() => theme.value === 'oled'),
    toggle() {
      const cycle: ThemeMode[] = ['neutral', 'dark', 'oled', 'light']
      theme.value = cycle[(cycle.indexOf(theme.value) + 1) % cycle.length]
    },
    set(mode: ThemeMode) {
      theme.value = mode
    },
    setAccent(color: AccentColor) {
      accent.value = color
    },
  }
}
