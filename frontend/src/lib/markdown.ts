import { marked } from 'marked'
import DOMPurify from 'dompurify'

/* Code blocks get a language label + copy button, wired via event delegation
   (see useCodeCopy) so v-html content needs no Vue compilation. */
function codeRenderer(code: string, lang: string): string {
  const escaped = code
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
  const label = (lang || 'text').toUpperCase()
  return `<div class="code-block group relative" data-lang="${label}">
  <div class="flex items-center justify-between border-b border-border px-4 py-2">
    <span class="text-2xs font-mono tracking-wider text-subtle-foreground">${label}</span>
    <button type="button" class="code-copy flex items-center gap-1 rounded-md px-1.5 py-1 text-2xs font-medium text-muted-foreground transition-colors hover:bg-accent hover:text-foreground" aria-label="複製程式碼">
      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>
      <span class="code-copy-label">複製</span>
    </button>
  </div>
  <pre><code class="language-${lang}">${escaped}</code></pre>
  <textarea class="code-raw hidden" aria-hidden="true">${escaped}</textarea>
</div>`
}

marked.use({
  renderer: {
    code({ text, lang }: { text: string; lang?: string }) {
      return codeRenderer(text || '', (lang || '').trim())
    },
  },
})

/** Render markdown → sanitized HTML with enhanced code blocks. */
export function renderMarkdown(text: string | null | undefined): string {
  if (!text) return ''
  try {
    const html = marked.parse(text, { async: false }) as string
    return DOMPurify.sanitize(html, {
      ADD_ATTR: ['target', 'rel'],
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
