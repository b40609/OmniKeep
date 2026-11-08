/**
 * Phone sign-in with a one-time code (app/pairing.py). An iPhone home-screen app keeps its own
 * storage apart from Safari, so the code is both scanned (Safari) and typed (home-screen app).
 */

/** Same letters as app/pairing.py ALPHABET: no 0/O or 1/I/L. */
const CODE = /^[2-9A-HJKMNP-Z]{8}$/

/** A pairing code without spaces, dashes or case, or '' when the text is not one (e.g. an API key). */
export function asPairingCode(text: string): string {
  const compact = text.toUpperCase().replace(/[^0-9A-Z]/g, '')
  return CODE.test(compact) ? compact : ''
}

/** ABCD-EFGH: easier to read off a screen and type. */
export function formatPairingCode(code: string): string {
  return code.length === 8 ? `${code.slice(0, 4)}-${code.slice(4)}` : code
}

/** The link in the QR code: the fragment never reaches the server or a proxy log. */
export function pairingLink(base: string, code: string): string {
  return `${base.trim().replace(/\/+$/, '')}/#pair=${code}`
}

function isLoopback(hostname: string): boolean {
  return hostname === 'localhost' || hostname === '::1' || hostname === '[::1]' || hostname.startsWith('127.')
}

/** Addresses to offer: the server's Tailscale name first, then this page's own unless it is loopback. */
export function phoneAddresses(fromServer: string[], here: { origin: string; hostname: string }): string[] {
  const list = [...fromServer]
  if (!isLoopback(here.hostname)) list.push(here.origin)
  return [...new Set(list.map((u) => u.replace(/\/+$/, '')))]
}
