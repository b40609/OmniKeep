/**
 * Showing a saved page. It is whatever the source site sent, so it never becomes a page of
 * OmniKeep's own: it goes into a frame with a unique origin and scripts off, where nothing
 * in it can read the stored access key or call the API.
 */

/**
 * The frame's `sandbox` value. No `allow-scripts`, no `allow-same-origin`, no `allow-forms`.
 * Links may open a new tab, and that tab is an ordinary one, so the linked site works.
 */
export const SNAPSHOT_SANDBOX = 'allow-popups allow-popups-to-escape-sandbox'

/** The frame's `srcdoc`: the saved page, with its links opening in a new tab instead of inside the frame. */
export function snapshotSrcdoc(html: string): string {
  // The first <base> with a target sets it; the page's own <base href> still resolves its addresses.
  return `<base target="_blank">${html}`
}
