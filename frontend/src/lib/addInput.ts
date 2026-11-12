/**
 * What the 新增 panel will do with what was typed, pasted or dropped: save links,
 * save a note, or hand a bookmark file to the import. The panel shows the answer
 * under the box before anything is sent. No runtime imports: the node tests load this file.
 */

/** Bookmark files the import reads (ImportDialog). */
export const IMPORT_EXTENSIONS = ['.html', '.htm', '.json', '.csv']

export function isImportFile(name: string): boolean {
  const lower = name.toLowerCase()
  return IMPORT_EXTENSIONS.some((ext) => lower.endsWith(ext))
}

/** An address in running text: it ends at a space, a quote or full-width punctuation. */
const LINK = /https?:\/\/[^\s<>"（）「」『』【】《》。，、；：！？]+/gi
/** Punctuation that ends a sentence around an address rather than the address itself. */
const TRAILING = /[.,;:!?]+$/
/** What may stand between addresses without making the text more than a list of them. */
const SEPARATORS = /[\s.,;:!?。，、；：！？「」『』（）()[\]]+/g

/** An address as written in running text, without the punctuation that follows it. */
function trimLink(raw: string): string {
  let link = raw
  for (;;) {
    const before = link
    link = link.replace(TRAILING, '')
    // A closing bracket belongs to the address only when it closes one opened inside it.
    for (const [open, close] of [['(', ')'], ['[', ']']]) {
      if (link.endsWith(close) && count(link, close) > count(link, open)) link = link.slice(0, -1)
    }
    if (link === before) return link
  }
}

function count(text: string, piece: string): number {
  return text.split(piece).length - 1
}

/** True for a whole http(s) address with a host. */
export function isLink(token: string): boolean {
  if (!/^https?:\/\//i.test(token)) return false
  try {
    return !!new URL(token).hostname
  } catch {
    return false
  }
}

/** Every http(s) address in the text, in order, each once. */
export function findLinks(text: string): string[] {
  const found: string[] = []
  for (const match of text.match(LINK) ?? []) {
    const link = trimLink(match)
    if (isLink(link) && !found.includes(link)) found.push(link)
  }
  return found
}

export type AddPlan =
  | { kind: 'empty' }
  /** Each address is saved as its own item. */
  | { kind: 'links'; urls: string[] }
  /** The text is saved as one note; `urls` are the addresses inside it, if any. */
  | { kind: 'note'; urls: string[] }
  | { kind: 'file'; name: string }
  | { kind: 'unsupported'; name: string }

export interface AddChoice {
  /** Text with addresses in it: save only the addresses. */
  linksOnly?: boolean
  /** Nothing but addresses: keep them as one note instead. */
  asNote?: boolean
}

/**
 * A file wins over text. Text that is nothing but addresses (one per line or
 * separated by spaces) is links; anything else is a note, even with addresses in it.
 */
export function planAdd(text: string, file: { name: string } | null = null, choice: AddChoice = {}): AddPlan {
  if (file) return isImportFile(file.name) ? { kind: 'file', name: file.name } : { kind: 'unsupported', name: file.name }
  if (!text.trim()) return { kind: 'empty' }
  const urls = findLinks(text)
  const onlyLinks = urls.length > 0 && !text.replace(LINK, '').replace(SEPARATORS, '')
  if (onlyLinks) return choice.asNote ? { kind: 'note', urls } : { kind: 'links', urls }
  return choice.linksOnly && urls.length ? { kind: 'links', urls } : { kind: 'note', urls }
}

/** The line under the box: what sending will do. */
export function describePlan(plan: AddPlan): string {
  switch (plan.kind) {
    case 'links': return plan.urls.length > 1 ? `會收藏 ${plan.urls.length} 個連結，在背景依序讀取` : '會收藏 1 個連結'
    case 'note': return '會存成筆記'
    case 'file': return `會匯入 ${plan.name}`
    case 'unsupported': return `不能匯入 ${plan.name}，請選 .html、.json 或 .csv 的書籤檔`
    default: return ''
  }
}

/** The send button names the action itself. */
export function submitLabel(plan: AddPlan): string {
  switch (plan.kind) {
    case 'links': return '收藏連結'
    case 'file': return '匯入'
    case 'note': return '儲存筆記'
    default: return '新增'
  }
}

/**
 * Why sending failed, in words for the panel: the server's own message without its
 * closing full stop, except the one it words for developers.
 */
export function explainFailure(message: string | null | undefined): string {
  const text = (message || '').trim().replace(/[。.]+$/, '')
  if (!text) return '原因不明'
  if (/non-public url/i.test(text)) return '這個網址不是公開的網頁，讀不到'
  return text
}

/** Is this pasted text something a paste on the page should open the panel for? */
export function isPastedLinks(text: string): boolean {
  return planAdd(text).kind === 'links'
}
