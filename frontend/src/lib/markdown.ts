import { marked } from 'marked'
import DOMPurify from 'dompurify'
import Prism from 'prismjs'
import 'prismjs/components/prism-javascript'
import 'prismjs/components/prism-typescript'
import 'prismjs/components/prism-python'
import 'prismjs/components/prism-bash'
import 'prismjs/components/prism-json'
import 'prismjs/components/prism-yaml'
import 'prismjs/components/prism-sql'
import 'prismjs/components/prism-markdown'
import 'prismjs/components/prism-css'

export interface TocItem {
  id: string
  text: string
  level: number
}

/** Extract TOC (Table of Contents) from markdown H2-H4 headings */
export function extractToc(markdownText: string | null | undefined): TocItem[] {
  if (!markdownText) return []
  const lines = markdownText.split('\n')
  const items: TocItem[] = []
  for (const line of lines) {
    const match = line.match(/^(#{2,4})\s+(.+)$/)
    if (match) {
      const level = match[1].length
      const rawText = match[2].trim()
      const cleanText = rawText.replace(/\[([^\]]+)\]\([^)]+\)/g, '$1').replace(/[*_`]/g, '')
      const id = cleanText
        .toLowerCase()
        .replace(/[^\w\u4e00-\u9fa5]+/g, '-')
        .replace(/^-+|-+$/g, '')
      if (cleanText) {
        items.push({ id, text: cleanText, level })
      }
    }
  }
  return items
}

function highlightCode(code: string, rawLang: string): string {
  const lang = (rawLang || '').toLowerCase().trim()
  const langAlias: Record<string, string> = {
    js: 'javascript',
    ts: 'typescript',
    py: 'python',
    sh: 'bash',
    shell: 'bash',
    yml: 'yaml',
  }
  const targetLang = langAlias[lang] || lang
  const grammar = Prism.languages[targetLang]
  if (grammar) {
    try {
      return Prism.highlight(code, grammar, targetLang)
    } catch {
      // fallback
    }
  }
  return code
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
}

/* Code blocks get a language label, syntax highlighting + copy button */
function codeRenderer(code: string, lang: string): string {
  if (lang.toLowerCase() === 'flow') {
    // Drawn later by renderFlowsIn (lib/flowchart.ts); the source waits hidden in the block.
    const src = code.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    return `<div class="flow-block"><pre class="flow-src">${src}</pre></div>`
  }
  if (lang.toLowerCase() === 'mermaid') {
    // Drawn later by renderMermaidIn (lib/mermaid.ts); the source waits hidden in the block.
    const src = code.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    return `<div class="mermaid-block"><pre class="mermaid-src">${src}</pre></div>`
  }
  const highlighted = highlightCode(code, lang)
  const escaped = code
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
  const label = (lang || 'text').toUpperCase()
  return `<div class="code-block group relative my-3 overflow-hidden rounded-xl border border-border/80 bg-muted/40 shadow-xs" data-lang="${label}">
  <div class="flex items-center justify-between border-b border-border/60 bg-muted/70 px-4 py-2">
    <span class="text-2xs font-mono font-medium tracking-wider text-muted-foreground">${label}</span>
    <button type="button" class="code-copy flex items-center gap-1 rounded-md px-2 py-1 text-2xs font-medium text-muted-foreground transition-colors hover:bg-accent hover:text-foreground" aria-label="複製程式碼">
      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>
      <span class="code-copy-label">複製</span>
    </button>
  </div>
  <pre class="overflow-x-auto p-4 text-xs font-mono leading-relaxed"><code class="language-${lang}">${highlighted}</code></pre>
  <textarea class="code-raw hidden" aria-hidden="true">${escaped}</textarea>
</div>`
}

marked.use({
  renderer: {
    heading({ text, depth }: { text: string; depth: number }) {
      const cleanText = text.replace(/<[^>]+>/g, '').trim()
      const slug = cleanText
        .toLowerCase()
        .replace(/[^\w\u4e00-\u9fa5]+/g, '-')
        .replace(/^-+|-+$/g, '')
      return `<h${depth} id="${slug}" class="scroll-mt-20 group flex items-center gap-1.5">
        <span>${text}</span>
        <a href="#${slug}" class="opacity-0 group-hover:opacity-100 text-muted-foreground/60 hover:text-primary text-xs font-mono transition-opacity ml-1" title="錨點連結">#</a>
      </h${depth}>`
    },
    code({ text, lang }: { text: string; lang?: string }) {
      return codeRenderer(text || '', (lang || '').trim())
    },
  },
})

/** Render markdown → sanitized HTML with enhanced code blocks. */
export function renderMarkdown(text: string | null | undefined): string {
  if (!text) return ''
  try {
    const html = (marked.parse(text, { async: false }) as string)
      // Wide tables scroll sideways inside their own box instead of squeezing on a phone.
      .replace(/<table>/g, '<div class="table-scroll"><table>')
      .replace(/<\/table>/g, '</table></div>')
    return DOMPurify.sanitize(html, {
      ADD_ATTR: ['target', 'rel', 'id'],
      FORBID_TAGS: ['style', 'iframe', 'form', 'input'],
    })
  } catch {
    return DOMPurify.sanitize(text)
  }
}

/** Attach click handler for .code-copy buttons inside a rendered container. */
export function useCodeCopy(container: HTMLElement | null): () => void {
  if (!container) return () => {}
  const onClick = (e: Event) => {
    const target = (e.target as HTMLElement).closest?.('.code-copy') as HTMLElement | null
    if (!target) return
    const raw = target.closest('.code-block')?.querySelector('.code-raw') as HTMLTextAreaElement | null
    if (!raw) return
    navigator.clipboard
      .writeText(raw.value)
      .then(() => {
        const label = target.querySelector('.code-copy-label')
        if (label) label.textContent = '已複製'
        setTimeout(() => {
          if (label) label.textContent = '複製'
        }, 1600)
      })
      .catch(() => {})
  }
  container.addEventListener('click', onClick)
  return () => container.removeEventListener('click', onClick)
}
