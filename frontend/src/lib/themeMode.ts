/**
 * Which theme a browser starts in. No runtime imports: the node tests load this
 * file on its own, and index.html repeats `startingTheme` inline before first paint.
 */

export type ThemeMode = 'neutral' | 'dark' | 'oled' | 'light' | 'system'

export const THEME_MODES: ThemeMode[] = ['neutral', 'dark', 'oled', 'light', 'system']
export const DEFAULT_THEME: ThemeMode = 'neutral'

/** Current key. The older `omnikeep-theme` key is only read once, to carry a choice over. */
export const THEME_KEY = 'omnikeep-theme-v2'
export const LEGACY_THEME_KEY = 'omnikeep-theme'

/**
 * `saved` is the current key, `legacy` the key used before the neutral theme existed.
 * The old key was written with its default ("dark") on first load, so a stored "dark"
 * cannot be told apart from never choosing: it moves to the new default. "oled",
 * "light" and "system" could only get there by the user picking them, and are kept.
 */
export function startingTheme(saved: string | null | undefined, legacy: string | null | undefined): ThemeMode {
  if (THEME_MODES.includes(saved as ThemeMode)) return saved as ThemeMode
  if (legacy === 'oled' || legacy === 'light' || legacy === 'system') return legacy
  return DEFAULT_THEME
}

/** Classes on <html>: every dark theme carries `dark`, so `dark:` utilities keep working. */
export function themeClasses(mode: ThemeMode, systemDark: boolean): { dark: boolean; oled: boolean; neutral: boolean } {
  return {
    dark: mode === 'neutral' || mode === 'dark' || mode === 'oled' || (mode === 'system' && systemDark),
    oled: mode === 'oled',
    neutral: mode === 'neutral',
  }
}

/** Page colour behind the app, for the browser's own chrome (`<meta name="theme-color">`). */
export function themeColor(mode: ThemeMode, systemDark: boolean): string {
  if (mode === 'neutral') return '#0f0f0f'
  if (mode === 'oled') return '#000000'
  return themeClasses(mode, systemDark).dark ? '#111216' : '#f4f5f7'
}
