/** 設定 → 系統 → 這台電腦免登入 (LOCAL_AUTO_LOGIN). */
export const LOCAL_LOGIN_KEY = 'LOCAL_AUTO_LOGIN'

interface LocalLoginField {
  value?: unknown
  env_available?: boolean
  env_value?: unknown
}

/**
 * True when saving these changes switches it off while it is on now. After that this computer
 * needs the access key too, so the owner is shown the key before the change is saved.
 */
export function turnsLocalLoginOff(
  field: LocalLoginField | undefined,
  values: Record<string, unknown>,
  reset: string[],
): boolean {
  if (!field || field.value !== true) return false
  // Going back to .env switches it off only when .env says false; the built-in default is on.
  if (reset.includes(LOCAL_LOGIN_KEY)) return field.env_available === true && field.env_value === false
  return values[LOCAL_LOGIN_KEY] === false
}
