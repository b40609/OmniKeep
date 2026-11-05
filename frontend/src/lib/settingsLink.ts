/**
 * `/#settings=<tab>&card=<id>`: the link the omnikeep_open_settings MCP tool hands the user,
 * so they paste a key on the right settings tab themselves instead of in an agent chat.
 * Read once at page load, before sign-in clears the fragment.
 */
export interface SettingsLink {
  tab: string
  /** AI service card to focus; kept for the card-based AI tab, ignored until it exists. */
  card: string
}

export function readSettingsLink(hash: string): SettingsLink | null {
  const fragment = new URLSearchParams(hash.replace(/^#/, ''))
  const tab = fragment.get('settings') ?? ''
  if (!/^[a-z_]{1,20}$/.test(tab)) return null
  const card = fragment.get('card') ?? ''
  return { tab, card: /^[A-Za-z0-9_-]{1,40}$/.test(card) ? card : '' }
}
