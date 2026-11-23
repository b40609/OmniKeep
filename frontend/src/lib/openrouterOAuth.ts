/**
 * Client-side helpers for the OpenRouter OAuth PKCE callback flow.
 * Kept free of Vue/Pinia imports so tests run directly under node.
 * Only non-secret draft metadata and the opaque one-time `state` live in
 * sessionStorage; `code_verifier` and the minted API key never leave the server.
 */

export const OPENROUTER_OAUTH_STORAGE_KEY = 'omnikeep_openrouter_oauth'
export const OPENROUTER_OAUTH_TTL_MS = 10 * 60 * 1000

export interface PendingOpenRouterOAuth {
  state: string
  createdAt: number
  source: 'settings' | 'wizard'
  mode: 'new' | 'edit'
  connectionId?: number
  label?: string
  model?: string
  slot?: string
  minInterval?: number | null
  maxConcurrency?: number | null
  caps?: Record<string, unknown>
}

export function callbackUrlFromLocation(loc: { origin: string; pathname: string }): string {
  const origin = (loc.origin || '').replace(/\/+$/, '')
  const pathname = loc.pathname && loc.pathname.startsWith('/') ? loc.pathname : '/'
  return `${origin}${pathname}`
}

export function savePendingOpenRouterOAuth(
  storage: Pick<Storage, 'setItem'>,
  pending: PendingOpenRouterOAuth,
): void {
  storage.setItem(OPENROUTER_OAUTH_STORAGE_KEY, JSON.stringify(pending))
}

export function takePendingOpenRouterOAuth(
  storage: Pick<Storage, 'getItem' | 'removeItem'>,
  now: number = Date.now(),
): PendingOpenRouterOAuth | null {
  let raw: string | null = null
  try {
    raw = storage.getItem(OPENROUTER_OAUTH_STORAGE_KEY)
    storage.removeItem(OPENROUTER_OAUTH_STORAGE_KEY)
  } catch {
    return null
  }
  if (!raw) return null
  try {
    const parsed = JSON.parse(raw) as Partial<PendingOpenRouterOAuth>
    if (!parsed || typeof parsed.state !== 'string' || !parsed.state.trim()) return null
    if (typeof parsed.createdAt !== 'number' || now - parsed.createdAt > OPENROUTER_OAUTH_TTL_MS) return null
    if (parsed.source !== 'settings' && parsed.source !== 'wizard') return null
    if (parsed.mode !== 'new' && parsed.mode !== 'edit') return null
    return parsed as PendingOpenRouterOAuth
  } catch {
    return null
  }
}

export function readOpenRouterCallback(search: string): { code: string; cleanedSearch: string } | null {
  const params = new URLSearchParams(search.startsWith('?') ? search.slice(1) : search)
  const code = (params.get('code') || '').trim()
  if (!code) return null
  params.delete('code')
  const rest = params.toString()
  return { code, cleanedSearch: rest ? `?${rest}` : '' }
}
