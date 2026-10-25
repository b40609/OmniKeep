import { computed, watch } from 'vue'
import { useLocalStorage, usePreferredDark } from '@vueuse/core'

export type ThemeMode = 'dark' | 'light' | 'system'

const theme = useLocalStorage<ThemeMode>('omnikeep-theme', 'dark')
const systemDark = usePreferredDark()

export function isDark(): boolean {
  return theme.value === 'dark' || (theme.value === 'system' && systemDark.value)
}

/** Sync <html> class + theme-color meta with the resolved theme. */
function applyTheme() {
  const dark = isDark()
  document.documentElement.classList.toggle('dark', dark)
  const meta = document.querySelector<HTMLMetaElement>('meta[name="theme-color"]')
  if (meta) meta.content = dark ? '#09090b' : '#fafafa'
}

/** Initialize on app boot (idempotent). */
export function initTheme() {
  applyTheme()
  watch(() => [theme.value, systemDark.value], applyTheme)
}

export function useTheme() {
  return {
    mode: theme,
    resolved: computed<'dark' | 'light'>(() => (isDark() ? 'dark' : 'light')),
    toggle() {
      theme.value = isDark() ? 'light' : 'dark'
    },
    set(mode: ThemeMode) {
      theme.value = mode
    },
  }
}
