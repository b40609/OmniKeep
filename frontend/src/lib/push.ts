/**
 * Browser-side Web Push helpers. Kept free of app imports so tests can run
 * them directly under node.
 */

/** VAPID public key (base64url) → the BufferSource PushManager.subscribe expects. */
export function urlBase64ToUint8Array(value: string): Uint8Array {
  const base64 = (value + '='.repeat((4 - (value.length % 4)) % 4)).replace(/-/g, '+').replace(/_/g, '/')
  const raw = atob(base64)
  return Uint8Array.from(raw, (c) => c.charCodeAt(0))
}

export function sameKey(a: ArrayBuffer | null | undefined, b: Uint8Array): boolean {
  if (!a) return false
  const left = new Uint8Array(a)
  return left.length === b.length && left.every((byte, i) => byte === b[i])
}

export interface PushEnvironment {
  supported: boolean
  /** iPhone/iPad Safari only exposes Push to Home Screen web apps (iOS 16.4+). */
  iosNeedsInstall: boolean
}

export function pushEnvironment(nav: Navigator = navigator, win: Window = window): PushEnvironment {
  const supported = 'serviceWorker' in nav && 'PushManager' in win && 'Notification' in win
  const ios = /iPad|iPhone|iPod/.test(nav.userAgent) || (nav.platform === 'MacIntel' && nav.maxTouchPoints > 1)
  const standalone =
    !!win.matchMedia?.('(display-mode: standalone)').matches ||
    (nav as Navigator & { standalone?: boolean }).standalone === true
  return { supported, iosNeedsInstall: ios && !standalone }
}
