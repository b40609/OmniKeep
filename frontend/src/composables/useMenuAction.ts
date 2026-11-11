/**
 * Run a menu item's action after the menu has closed.
 *
 * A dropdown menu hands focus back to its button as it closes. A dialog or panel
 * opened from the item's own select handler is already on screen by then, sees
 * focus land outside itself and closes again. So the item only records what to
 * do (`defer`), and the menu's `close-auto-focus` event runs it (`flush`) in place
 * of the focus hand-back.
 */
export function useMenuAction() {
  let pending: (() => void) | null = null
  return {
    defer(action: () => void) {
      pending = action
    },
    flush(event: Event) {
      if (!pending) return
      const run = pending
      pending = null
      event.preventDefault()
      run()
    },
  }
}
