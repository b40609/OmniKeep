import DOMPurify from 'dompurify'

/* Flowcharts in the deep analysis. The analysis prompt (app/pipeline.py) asks for a mermaid block
   only when the source describes a real multi-step flow, so most items have none: mermaid is
   imported the first time a block shows up, never in the main bundle.
   An invalid diagram must never reach the page. mermaid.render() can return an error SVG instead
   of throwing (Open WebUI #18340), so the source is parsed first, the SVG is checked for an
   error-icon element, and any failure shows the steps as a plain list instead. */

type Mermaid = typeof import('mermaid').default
let loader: Promise<Mermaid> | null = null
let initialisedDark: boolean | null = null
let seq = 0

function isDark(): boolean {
  const root = document.documentElement
  return root.classList.contains('dark') || root.classList.contains('oled')
}

async function load(): Promise<Mermaid> {
  loader ??= import('mermaid').then((m) => m.default)
  const mermaid = await loader
  const dark = isDark()
  if (initialisedDark !== dark) {
    mermaid.initialize({
      startOnLoad: false,
      securityLevel: 'strict',
      theme: dark ? 'dark' : 'neutral',
      fontFamily: 'inherit',
      // Plain SVG text: labels in <foreignObject> would be stripped by the SVG sanitising below.
      // mermaid 11 reads the top-level key; the flowchart one is the older spelling.
      htmlLabels: false,
      // Natural size: a long chart scrolls sideways (.mermaid-block) instead of shrinking its text.
      // Colours come from the theme tokens in main.css (.mermaid-block); these only set geometry.
      themeVariables: { fontSize: '14px' },
      flowchart: { htmlLabels: false, useMaxWidth: false, curve: 'basis', nodeSpacing: 32, rankSpacing: 36, padding: 12 },
      sequence: { useMaxWidth: false },
    })
    initialisedDark = dark
  }
  return mermaid
}

const escapeHtml = (s: string) =>
  s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')

/** The diagram's steps as text: node labels in the order they first appear, or the messages of a
 *  sequence diagram. Used when the diagram cannot be drawn. */
export function mermaidSteps(code: string): string[] {
  const lines = code.split('\n').map((l) => l.trim()).filter(Boolean)
  if (/^sequenceDiagram/.test(lines[0] || '')) {
    return lines
      .map((l) => l.match(/^([^-:]+?)\s*-{1,2}>{1,2}[+-]?\s*([^:]+?)\s*:\s*(.+)$/))
      .filter((m): m is RegExpMatchArray => !!m)
      .map((m) => `${m[1].trim()} → ${m[2].trim()}：${m[3].trim()}`)
  }
  const steps: string[] = []
  const seen = new Set<string>()
  for (const m of code.matchAll(/\b([A-Za-z][\w]*)\s*[[({]+"?([^"\])}]+)"?[\])}]+/g)) {
    if (seen.has(m[1])) continue
    seen.add(m[1])
    steps.push(m[2].trim())
  }
  return steps
}

function fallbackHtml(code: string): string {
  const steps = mermaidSteps(code)
  if (!steps.length) return ''
  return `<ol class="mermaid-fallback">${steps.map((s) => `<li>${escapeHtml(s)}</li>`).join('')}</ol>`
}

/** Draw every not-yet-drawn mermaid block inside a rendered markdown container. */
export async function renderMermaidIn(container: HTMLElement | null): Promise<void> {
  const blocks = container ? Array.from(container.querySelectorAll<HTMLElement>('.mermaid-block:not([data-done])')) : []
  if (!blocks.length) return
  // Claim the blocks and take their source before the first await: a second call made while
  // mermaid is loading must not draw them again over this one's result.
  const jobs = blocks.map((block) => {
    block.dataset.done = '1'
    return { block, code: block.querySelector('.mermaid-src')?.textContent || '' }
  })
  let mermaid: Mermaid | null = null
  try {
    mermaid = await load()
  } catch {
    mermaid = null
  }
  for (const { block, code } of jobs) {
    try {
      if (!mermaid) throw new Error('mermaid not loaded')
      await mermaid.parse(code)
      const { svg } = await mermaid.render(`mmd-${++seq}`, code)
      // Every mermaid SVG carries an .error-icon rule in its <style>, so look for the element,
      // not the text.
      const doc = new DOMParser().parseFromString(svg, 'image/svg+xml')
      if (doc.querySelector('parsererror, .error-icon, [aria-roledescription="error"]')) throw new Error('error diagram')
      block.innerHTML = DOMPurify.sanitize(svg, { USE_PROFILES: { svg: true, svgFilters: true }, ADD_TAGS: ['style'] })
      block.classList.add('mermaid-ok')
    } catch {
      block.innerHTML = fallbackHtml(code)
      block.classList.add('mermaid-failed')
    } finally {
      document.getElementById(`dmmd-${seq}`)?.remove() // mermaid's scratch node, left behind on error
    }
  }
}
