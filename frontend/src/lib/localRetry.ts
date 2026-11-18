/**
 * When the server says a saved key no longer works, a browser on the server's own machine can
 * usually sign in again by itself (LOCAL_AUTO_LOGIN), so try that before showing the login box.
 * Several requests fail at once when that happens; they share one attempt.
 */
export function onceAtATime(attempt: () => Promise<boolean>): () => Promise<boolean> {
  let running: Promise<boolean> | null = null
  return () => {
    running ??= attempt().catch(() => false).finally(() => { running = null })
    return running
  }
}
