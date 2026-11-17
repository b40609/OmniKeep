/* System architecture diagrams in a GitHub project's deep analysis (prompt rule "架構圖" in
   app/pipeline.py; app/arch_block.py checks the file paths and adds the 專案 line). The model
   writes an ```arch block of plain lines, no quotes, so it survives being a JSON string:

     總結：一句白話
     附註：右上角的補充
     專案：owner/repo@commit                                       (added by the server)
     入口｜ID｜圖示｜名稱｜一行說明｜接到｜線上標籤｜完整說明｜重點；重點｜檔案、檔案
     區｜名稱｜一句說明｜進入這區的線上標籤
     元件｜ID｜圖示｜名稱｜一行說明｜小標籤｜一般/重點/關卡｜完整說明｜重點｜檔案
     旁｜ID｜圖示｜名稱｜一行說明｜接在｜去程標籤｜回程標籤｜完整說明｜重點｜檔案

   Drawn the way the owner picked on 2026-11-15 ("V1 精修"): inputs in a column at the left, each
   區 a band of cards in data-flow order, snaking down from one band to the next, helpers hanging
   under the card that calls them. A band too long for the reading column wraps onto another row and
   the snake goes on (2026-11-17); only a column too narrow for two cards a row stacks the diagram
   top to bottom at full size instead. A beam walks the flow one line at a time and rests on each card; a
   click opens the card's details beside it and, like Archify's Upstream/Downstream, lights
   everything that leads to the card and everything it leads to. A file may carry a line range
   (app/main.py:12-40); links open those lines on the commit the analysis read. Like lib/flowchart.ts it plays even under the system's
   reduce-motion setting: the owner's Windows has it on and asked for the motion. Everything is DOM text set with textContent; nothing
   from the model reaches innerHTML. */

export type ArchKind = 'ext' | 'plain' | 'key' | 'gate' | 'side'
export interface ArchNode {
  id: string; icon: string; title: string; desc: string; tag: string; kind: ArchKind
  more: string; facts: string[]; files: string[]
}
export interface ArchInput extends ArchNode { to: string; label: string }
export interface ArchSide extends ArchNode { parent: string; out: string; back: string }
export interface ArchLane { title: string; note: string; label: string; ids: string[] }
export interface Arch {
  gist: string; note: string; repo: string; sha: string
  inputs: ArchInput[]; lanes: ArchLane[]; sides: ArchSide[]; nodes: Record<string, ArchNode>
}

const SEP = /\s*[｜|]\s*/
const ID = /^[A-Za-z][\w-]{0,15}$/
const list = (s: string | undefined, sep: RegExp) => (s || '').split(sep).map((x) => x.trim()).filter(Boolean)
const KINDS = new Set(['一般', '重點', '關卡'])
const MAX_INPUTS = 3, MAX_LANES = 3, MAX_PER_LANE = 5, MAX_SIDES = 2

export function parseArch(code: string): Arch | null {
  const a: Arch = { gist: '', note: '', repo: '', sha: '', inputs: [], lanes: [], sides: [], nodes: {} }
  const ins: ArchInput[] = [], sides: ArchSide[] = []
  let lane: ArchLane | null = null
  const node = (f: string[], kind: ArchKind, at: { more: number; facts: number; files: number }): ArchNode | null => {
    const id = f[1] || ''
    if (!ID.test(id) || a.nodes[id] || !f[3]) return null
    const n: ArchNode = {
      id, icon: (f[2] || '').toLowerCase(), title: f[3], desc: f[4] || '', tag: '', kind,
      more: f[at.more] || '', facts: list(f[at.facts], /[；;]/).slice(0, 4), files: list(f[at.files], /[、,，]/).slice(0, 3),
    }
    a.nodes[id] = n
    return n
  }
  for (const raw of code.split('\n')) {
    const line = raw.trim()
    if (!line) continue
    let m = line.match(/^總結[:：]\s*(.+)$/)
    if (m) { a.gist = m[1]; continue }
    m = line.match(/^附註[:：]\s*(.+)$/)
    if (m) { a.note = m[1]; continue }
    m = line.match(/^專案[:：]\s*([\w.-]+\/[\w.-]+)(?:@([0-9a-f]{7,40}))?\s*$/)
    if (m) { a.repo = m[1]; a.sha = m[2] || ''; continue }
    const f = line.split(SEP)
    if (f[0] === '入口') {
      const n = node(f, 'ext', { more: 7, facts: 8, files: 9 })
      if (n) ins.push({ ...n, to: f[5] || '', label: f[6] || '' })
    } else if (f[0] === '區') {
      lane = { title: f[1] || '', note: f[2] || '', label: f[3] || '', ids: [] }
      a.lanes.push(lane)
    } else if (f[0] === '元件') {
      // a line that skipped the 小標籤 column has the kind where the tag goes: put the column back
      if (f.length < 10 && KINDS.has(f[5] || '') && !KINDS.has(f[6] || '')) f.splice(5, 0, '')
      const kind: ArchKind = f[6] === '重點' ? 'key' : f[6] === '關卡' ? 'gate' : 'plain'
      const n = node(f, kind, { more: 7, facts: 8, files: 9 })
      if (!n) continue
      n.tag = f[5] || ''
      if (!lane) { lane = { title: '', note: '', label: '', ids: [] }; a.lanes.push(lane) }
      lane.ids.push(n.id)
    } else if (f[0] === '旁') {
      const n = node(f, 'side', { more: 8, facts: 9, files: 10 })
      if (n) sides.push({ ...n, parent: f[5] || '', out: f[6] || '', back: f[7] || '' })
    }
  }
  // a band holds at most 5 cards: a longer one is split while there is room for another band
  const lanes: ArchLane[] = []
  for (const l of a.lanes.filter((x) => x.ids.length)) {
    for (let i = 0; i < l.ids.length; i += MAX_PER_LANE) lanes.push({ ...l, label: i ? '' : l.label, title: i ? '' : l.title, note: i ? '' : l.note, ids: l.ids.slice(i, i + MAX_PER_LANE) })
  }
  a.lanes = lanes.slice(0, MAX_LANES)
  const shown = new Set(a.lanes.flatMap((l) => l.ids))
  if (shown.size < 2) return null
  // at most one card is the highlight and one the gate
  for (const k of ['key', 'gate'] as const) {
    let seen = false
    for (const id of a.lanes.flatMap((l) => l.ids)) if (a.nodes[id].kind === k) { if (seen) a.nodes[id].kind = 'plain'; seen = true }
  }
  const first = a.lanes[0]
  for (const i of ins.slice(0, MAX_INPUTS)) a.inputs.push({ ...i, to: first.ids.includes(i.to) ? i.to : first.ids[0] })
  // a helper hangs under the card that calls it; the last card of a band (but the last band) is
  // where the line goes down to the next band, so nothing can hang there
  const ends = new Set(a.lanes.slice(0, -1).map((l) => l.ids[l.ids.length - 1]))
  for (const s of sides) {
    if (a.sides.length >= MAX_SIDES || !shown.has(s.parent) || ends.has(s.parent) || a.sides.some((x) => x.parent === s.parent)) continue
    a.sides.push(s)
  }
  return a
}

/* ---------------------------------------------------------------- icons */

// Line icons drawn on a 24 grid (constants, never model text).
const ICONS: Record<string, string> = {
  user: '<circle cx="12" cy="8" r="3.5"/><path d="M5 20c1.2-3.6 3.8-5.5 7-5.5s5.8 1.9 7 5.5"/>',
  bot: '<rect x="5" y="8" width="14" height="11" rx="3"/><path d="M12 4v4M9 13h.01M15 13h.01"/>',
  globe: '<circle cx="12" cy="12" r="8.5"/><path d="M3.5 12h17M12 3.5c2.4 2.5 3.5 5.3 3.5 8.5s-1.1 6-3.5 8.5c-2.4-2.5-3.5-5.3-3.5-8.5s1.1-6 3.5-8.5z"/>',
  chart: '<path d="M4 19h16"/><path d="M7 15l3-4 3 2 4-6"/>',
  list: '<path d="M9 7h10M9 12h10M9 17h10"/><path d="M5 7h.01M5 12h.01M5 17h.01"/>',
  check: '<path d="M12 3l7 3v5c0 4.5-3 8-7 9.5C8 19 5 15.5 5 11V6z"/><path d="M9 12l2 2 4-4"/>',
  replay: '<path d="M4 12a8 8 0 1 0 3-6.2"/><path d="M4 4v4h4"/>',
  coins: '<ellipse cx="12" cy="6" rx="7" ry="2.5"/><path d="M5 6v6c0 1.4 3.1 2.5 7 2.5s7-1.1 7-2.5V6"/><path d="M5 12v6c0 1.4 3.1 2.5 7 2.5s7-1.1 7-2.5v-6"/>',
  layers: '<path d="M12 4l8 4-8 4-8-4z"/><path d="M4 12l8 4 8-4"/><path d="M4 16l8 4 8-4"/>',
  stamp: '<path d="M9 4h6l-1 7h-4z"/><path d="M5 15h14v3H5z"/><path d="M7 21h10"/>',
  cpu: '<rect x="6" y="6" width="12" height="12" rx="2"/><path d="M10 10h4v4h-4zM9 2v4M15 2v4M9 18v4M15 18v4M2 9h4M2 15h4M18 9h4M18 15h4"/>',
  shield: '<path d="M12 3l7 3v5c0 4.5-3 8-7 9.5C8 19 5 15.5 5 11V6z"/><path d="M12 8v5M12 16h.01"/>',
  swap: '<path d="M4 8h13l-3-3M20 16H7l3 3"/>',
  db: '<ellipse cx="12" cy="6" rx="7" ry="2.5"/><path d="M5 6v12c0 1.4 3.1 2.5 7 2.5s7-1.1 7-2.5V6M5 12c0 1.4 3.1 2.5 7 2.5s7-1.1 7-2.5"/>',
  box: '<path d="M4 8l8-4 8 4v8l-8 4-8-4z"/><path d="M4 8l8 4 8-4M12 12v8"/>',
  file: '<path d="M7 3h7l5 5v13H7z"/><path d="M14 3v5h5M10 13h6M10 17h6"/>',
  code: '<path d="M9 8l-4 4 4 4M15 8l4 4-4 4"/>',
  search: '<circle cx="11" cy="11" r="6"/><path d="M20 20l-4.5-4.5"/>',
  cloud: '<path d="M7 18h10a4 4 0 0 0 .5-8 6 6 0 0 0-11.4 1.5A3.3 3.3 0 0 0 7 18z"/>',
  key: '<circle cx="8" cy="15" r="4"/><path d="M11 12l8-8M16 7l3 3"/>',
  bell: '<path d="M6 16V11a6 6 0 0 1 12 0v5l2 2H4z"/><path d="M10 20a2 2 0 0 0 4 0"/>',
  chat: '<path d="M5 5h14v10H10l-5 4z"/>',
  image: '<rect x="4" y="5" width="16" height="14" rx="2"/><circle cx="9" cy="10" r="1.5"/><path d="M20 16l-5-5-8 8"/>',
  play: '<path d="M8 5.5v13l10-6.5z"/>',
  gear: '<circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M2 12h3M19 12h3M4.9 19.1L7 17M17 7l2.1-2.1"/>',
  link: '<path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1"/><path d="M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1"/>',
  lock: '<rect x="5" y="11" width="14" height="9" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/>',
  mail: '<rect x="4" y="6" width="16" height="12" rx="2"/><path d="M4 8l8 5 8-5"/>',
  server: '<rect x="4" y="4" width="16" height="7" rx="2"/><rect x="4" y="13" width="16" height="7" rx="2"/><path d="M8 7.5h.01M8 16.5h.01"/>',
  terminal: '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="M7 10l3 2-3 2M13 15h4"/>',
  clock: '<circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/>',
  folder: '<path d="M3.5 7a2 2 0 0 1 2-2h4l2 2.5h7a2 2 0 0 1 2 2V17a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2z"/>',
  filter: '<path d="M4 5h16l-6 7.5V19l-4-2v-4.5z"/>',
  send: '<path d="M4 12l16-8-6 16-3-7z"/><path d="M11 13l9-9"/>',
  download: '<path d="M12 4v11M7 10.5l5 4.5 5-4.5M5 20h14"/>',
}
const iconFor = (name: string, kind: ArchKind) => ICONS[name] || (kind === 'ext' ? ICONS.globe : ICONS.box)

/* ---------------------------------------------------------------- layout */

type Pt = [number, number]
interface Place { x: number; y: number; w: number; h: number }
interface EdgeSpec { s: string; t: string; pts: Pt[]; label: string; at?: Pt; inBand?: boolean; side?: 'l' | 'r'; down?: boolean }
interface BandSpec extends Place { title: string; note: string; lbLeft?: number }
export interface ArchLayout {
  width: number; height: number; narrow: boolean
  places: Record<string, Place>; bands: BandSpec[]; edges: EdgeSpec[]
  route: { e: number; to: string }[]; start: string | null
}

const textW = (s: string, px: number) => [...s].reduce((w, c) => w + (c.charCodeAt(0) > 0x2e80 ? px : px * 0.56), 0)
const lines = (s: string, px: number, room: number, max: number) => (s ? Math.min(max, Math.ceil(textW(s, px) / room)) : 0)
/** A card is as tall as what it holds (padding, title, description lines, small tag), so no card carries an empty bottom. */
function cardH(n: ArchNode, w: number, narrow: boolean): number {
  const d = lines(n.desc, 12.5, w - 28, narrow ? 1 : 2), t = lines(n.title, 14, w - 28 - 24, 2)
  return 24 + 20 * t + (d ? (narrow ? 4 : 6) + d * 18 : 0) + (n.tag ? (narrow ? 20 : 22) : 0) + 2
}
const bandLabelW = (b: { title: string; note: string }) => (b.title ? textW(b.title, 12.5) + 8 : 0) + textW(b.note, 12.5)

export function layoutArch(a: Arch, width: number): ArchLayout {
  const wide = wideLayout(a, width)
  return wide || narrowLayout(a, width)
}

/** Order of the walk: the flow through the bands, with each helper visited from its caller. */
function walk(a: Arch, edges: EdgeSpec[]): { route: { e: number; to: string }[]; start: string | null } {
  const find = (s: string, t: string) => edges.findIndex((e) => e.s === s && e.t === t)
  const seq = a.lanes.flatMap((l) => l.ids)
  const route: { e: number; to: string }[] = []
  const first = a.inputs[0]
  let i = 0
  if (first) { route.push({ e: find(first.id, first.to), to: first.to }); i = seq.indexOf(first.to) }
  for (; i < seq.length; i++) {
    const id = seq[i]
    const side = a.sides.find((s) => s.parent === id)
    if (side) { route.push({ e: find(id, side.id), to: side.id }, { e: find(side.id, id), to: id }) }
    if (i + 1 < seq.length) route.push({ e: find(id, seq[i + 1]), to: seq[i + 1] })
  }
  return { route: route.filter((r) => r.e >= 0), start: first ? first.id : seq[0] }
}

interface Row { lane: number; ids: string[]; top: number; bottom: number }

/** Each band's cards in rows of at most `cols`, as even as they go. A row may end a card early so
 *  the line down to the next row never leaves a card a helper hangs under; null if it still would. */
function splitRows(a: Arch, cols: number): Row[] | null {
  const hangs = new Set(a.sides.map((s) => s.parent))
  const rows: Row[] = []
  a.lanes.forEach((l, li) => {
    const per = Math.ceil(l.ids.length / Math.ceil(l.ids.length / cols))
    for (let i = 0; i < l.ids.length;) {
      let k = Math.min(per, l.ids.length - i)
      while (k > 1 && i + k < l.ids.length && hangs.has(l.ids[i + k - 1])) k--
      rows.push({ lane: li, ids: l.ids.slice(i, i + k), top: 0, bottom: 0 })
      i += k
    }
  })
  return rows.slice(0, -1).some((r) => hangs.has(r.ids[r.ids.length - 1])) ? null : rows
}

/** Would a new line along `pts` cross or run along a line already drawn? */
function blocked(edges: EdgeSpec[], pts: Pt[]): boolean {
  const inside = (u: number, a: number, b: number) => u > Math.min(a, b) + 1 && u < Math.max(a, b) - 1
  const overlap = (a0: number, a1: number, b0: number, b1: number) => Math.min(Math.max(a0, a1), Math.max(b0, b1)) - Math.max(Math.min(a0, a1), Math.min(b0, b1)) > 1
  for (let j = 1; j < pts.length; j++) {
    const [p, q] = [pts[j - 1], pts[j]], pv = p[0] === q[0]
    for (const e of edges) {
      for (let k = 1; k < e.pts.length; k++) {
        const [a, b] = [e.pts[k - 1], e.pts[k]], av = a[0] === b[0]
        if (pv !== av) {
          const [v0, v1, h0, h1] = pv ? [p, q, a, b] : [a, b, p, q]
          if (inside(v0[0], h0[0], h1[0]) && inside(h0[1], v0[1], v1[1])) return true
        } else if (pv ? Math.abs(p[0] - a[0]) < 2 && overlap(p[1], q[1], a[1], b[1]) : Math.abs(p[1] - a[1]) < 2 && overlap(p[0], q[0], a[0], b[0])) return true
      }
    }
  }
  return false
}

function wideLayout(a: Arch, width: number): ArchLayout | null {
  const GAP = 28, PAD = 12
  // an input card is wide enough for its name and one-line description, within 148 to 200
  const IW = Math.round(Math.min(200, Math.max(148, ...a.inputs.map((i) => 24 + Math.max(textW(i.title, 14) + 24, textW(i.desc, 12.5)) + 8))))
  // ... and tall enough for a name that still needs two lines
  const IH = Math.max(60, ...a.inputs.map((i) => 20 + 20 * lines(i.title, 14, IW - 48, 2) + (i.desc ? 20 : 0)))
  const straight = a.inputs.filter((i) => i.to === a.lanes[0].ids[0]).slice(0, 2)
  const viaGap = a.inputs.filter((i) => !straight.includes(i)).slice(0, a.lanes.length > 1 ? 1 : 2)
  const inputs = [...straight, ...viaGap]
  // the gap after the input column fits the longest label on a straight line
  const lead = inputs.length ? IW + Math.min(110, Math.max(36, ...straight.map((i) => i.label ? textW(i.label, 11.5) + 20 : 0))) : 0
  let inner = width - lead - PAD * 2
  const cards = a.lanes.flatMap((l) => l.ids.map((id) => a.nodes[id]))
  // a long name (often English) may widen the cards up to 236 if the row has room
  const longest = Math.max(...cards.map((c) => textW(c.title, 14) + 28 + 24 + 4))
  const fit = (c: number) => Math.min(Math.max(c <= 3 ? 196 : 176, Math.min(236, Math.ceil(longest))), Math.floor((inner - (c - 1) * GAP) / c))
  // as many cards to a row as keep each one readable; a band longer than that wraps onto the next
  // row and the flow snakes on, so the diagram stays side by side inside the reading column
  const maxLen = Math.max(...a.lanes.map((l) => l.ids.length))
  let rows: Row[] | null = null
  for (let c = maxLen; c >= Math.min(2, maxLen) && !rows; c--) {
    const w = fit(c)
    if (w >= 160 || (c <= 2 && w >= 136)) rows = splitRows(a, c)
  }
  if (!rows) return null
  const R = rows
  const n = Math.max(...R.map((r) => r.ids.length))
  const W = fit(n)
  const gap = n > 1 ? Math.min(56, (inner - n * W) / (n - 1)) : 0
  // a short flow keeps its cards together and the diagram narrower, centred in the frame
  inner = n * W + (n - 1) * gap
  width = Math.min(width, Math.ceil(lead + PAD * 2 + inner))
  const step = W + gap
  const H = Math.max(64, ...cards.map((c) => cardH(c, W, false)))
  const colX = (c: number) => lead + PAD + c * step
  const places: Record<string, Place> = {}, bands: BandSpec[] = [], edges: EdgeSpec[] = []
  const BAND_GAP = 60, ROW_GAP = 44, TOP = 38
  let y = 4, col = 0, dir = 1, prevLen = 0
  a.lanes.forEach((l, li) => {
    const top = y
    let ry = top + TOP, bottom = ry
    for (const r of R.filter((x) => x.lane === li)) {
      const len = r.ids.length
      // each row starts under the card the row above ended on and runs back the other way; a lone
      // card runs no way, so the row after it runs whichever way fits and the line down stays straight
      let start: number
      if (r === R[0]) { start = 0; dir = 1 } else {
        dir = prevLen > 1 ? -dir : col + len - 1 <= n - 1 ? 1 : -1
        start = dir < 0 ? Math.max(col, len - 1) : Math.min(col, n - len)
      }
      r.ids.forEach((id, k) => { places[id] = { x: colX(start + dir * k), y: ry, w: W, h: H } })
      col = start + dir * (len - 1)
      prevLen = len
      r.top = ry; r.bottom = ry + H
      bottom = ry + H + 18
      for (const s of a.sides) {
        const p = places[s.parent]
        if (!p || !r.ids.includes(s.parent)) continue
        places[s.id] = { x: p.x, y: p.y + p.h + 48, w: p.w, h: Math.max(s.desc ? 76 : 56, cardH(a.nodes[s.id] || s, p.w, false)) }
        r.bottom = Math.max(r.bottom, places[s.id].y + places[s.id].h)
        bottom = Math.max(bottom, places[s.id].y + places[s.id].h + 14)
      }
      ry = r.bottom + ROW_GAP
    }
    bands.push({ x: lead, y: top, w: width - lead, h: bottom - top, title: l.title, note: l.note })
    y = bottom + BAND_GAP
  })
  const height = y - BAND_GAP
  const P = (id: string) => places[id]
  const cx = (p: Place, f = 0.5) => p.x + p.w * f
  // inside a row: card to card, left or right
  for (const r of R) {
    for (let k = 1; k < r.ids.length; k++) {
      const s = P(r.ids[k - 1]), t = P(r.ids[k]), my = s.y + s.h / 2
      edges.push({ s: r.ids[k - 1], t: r.ids[k], label: '', pts: t.x > s.x ? [[s.x + s.w, my], [t.x, my]] : [[s.x, my], [t.x + t.w, my]] })
    }
  }
  // from the last card of a row down to the first of the next, in the same band or the next one
  R.forEach((r, ri) => {
    const nx = R[ri + 1]
    if (!nx) return
    const sid = r.ids[r.ids.length - 1], tid = nx.ids[0], s = P(sid), t = P(tid)
    let tx = cx(t), gy: number, label = ''
    if (nx.lane === r.lane) gy = (r.bottom + nx.top) / 2
    else {
      gy = bands[r.lane].y + bands[r.lane].h + BAND_GAP / 2
      label = a.lanes[nx.lane].label
      // the line never crosses the next band's name: it comes down right of the name if the card
      // leaves room, otherwise near the card's left edge with the name starting just past it
      const nb = bands[nx.lane], lx0 = nb.x + 14, lx1 = lx0 + bandLabelW(nb)
      if ((nb.title || nb.note) && tx > lx0 - 12 && tx < lx1 + 12) {
        if (lx1 + 16 <= t.x + t.w - 28) tx = lx1 + 16
        else { tx = t.x + 28; nb.lbLeft = tx - nb.x + 14 }
      }
    }
    const sx = s.x === t.x ? tx : cx(s)
    const pts: Pt[] = sx === tx ? [[sx, s.y + s.h], [tx, t.y]] : [[sx, s.y + s.h], [sx, gy], [tx, gy], [tx, t.y]]
    edges.push({ s: sid, t: tid, label, pts, at: sx === tx ? [tx, gy] : [(sx + tx) / 2, gy], down: true })
  })
  // helpers: out of the caller's bottom and back in, labels beside the two lines
  for (const s of a.sides) {
    const p = P(s.parent), q = P(s.id)
    if (!p || !q) continue
    const my = (p.y + p.h + q.y) / 2
    edges.push({ s: s.parent, t: s.id, label: s.out, pts: [[cx(p, 0.36), p.y + p.h], [cx(q, 0.36), q.y]], at: [cx(p, 0.36) - 8, my], inBand: true, side: 'l' })
    edges.push({ s: s.id, t: s.parent, label: s.back, pts: [[cx(q, 0.64), q.y], [cx(p, 0.64), p.y + p.h]], at: [cx(p, 0.64) + 8, my], inBand: true, side: 'r' })
  }
  // inputs: in the column at the left; up to two run straight into the first card, one more comes
  // in from below along the gap between the bands
  const f0 = P(a.lanes[0].ids[0])
  const centers = straight.length === 2 ? [f0.y + f0.h / 2 - IH / 2 - 6, f0.y + f0.h / 2 + IH / 2 + 6] : [f0.y + f0.h / 2]
  straight.forEach((i, k) => {
    places[i.id] = { x: 0, y: centers[k] - IH / 2, w: IW, h: IH }
    edges.push({ s: i.id, t: i.to, label: i.label, pts: [[IW, centers[k]], [f0.x, centers[k]]], at: [(IW + f0.x) / 2, centers[k] - 11] })
  })
  const usedGaps = new Set<number>()
  for (const [k, i] of viaGap.entries()) {
    const t = P(i.to), b0 = bands[0]
    // it comes in along the gap under its card's row: inside the band if the band wraps on below it
    const ri = R.findIndex((r) => r.ids.includes(i.to)), nx = R[ri + 1]
    const inBand = !!nx && nx.lane === 0
    if (inBand && usedGaps.has(ri)) return null
    usedGaps.add(ri)
    const gy = inBand ? (R[ri].bottom + nx.top) / 2 : a.lanes.length > 1 ? b0.y + b0.h + BAND_GAP / 2 : b0.y + b0.h + 22 + k * 72
    // the line down to the next row leaves this card's bottom too: come in left of it
    const down = edges.find((e) => e.s === i.to && e.down)
    let vx = down ? cx(t, 0.3) : cx(t)
    if (down && down.pts[0][0] <= vx + 8) vx = Math.max(t.x + 14, down.pts[0][0] - 16)
    const helper = a.sides.find((x) => x.parent === i.to)
    // a helper hangs under the card: come up beside the card and in at its left edge instead
    // ... below the lines that come straight into the same card, so it crosses none of them
    const ex = t.x - 16, under = Math.max(-Infinity, ...edges.filter((e) => e.t === i.to && e.pts.length === 2 && e.pts[0][1] === e.pts[1][1]).map((e) => e.pts[0][1]))
    let ey = t.y + t.h * 0.72
    if (ey < under + 8) ey = (under + t.y + t.h) / 2
    const pts: Pt[] = helper ? [[IW, gy], [ex, gy], [ex, ey], [t.x, ey]] : [[IW, gy], [vx, gy], [vx, t.y + t.h]]
    // a wrapped band can put another row's line across the way in: then the diagram is stacked
    if ((helper && ey > t.y + t.h - 6) || blocked(edges, pts)) return null
    // its card sits on its line, nudged down off an input card above it while the line still leaves its side
    let iy = gy - IH / 2
    for (const o of inputs) { const q = places[o.id]; if (q && o !== i && iy < q.y + q.h + 8 && q.y < iy + IH + 8) iy = q.y + q.h + 8 }
    if (gy < iy + 14) return null
    places[i.id] = { x: 0, y: iy, w: IW, h: IH }
    edges.push({ s: i.id, t: i.to, label: i.label, pts, at: [(IW + (helper ? ex : vx)) / 2, gy] })
  }
  // input cards never land on each other
  const ip = inputs.map((i) => places[i.id]).filter(Boolean)
  for (let x = 0; x < ip.length; x++) for (let z = x + 1; z < ip.length; z++) if (ip[x].y < ip[z].y + ip[z].h + 8 && ip[z].y < ip[x].y + ip[x].h + 8) return null
  const h = Math.max(height, ...Object.values(places).map((p) => p.y + p.h))
  return { width, height: h, narrow: false, places, bands, edges, ...walk(a, edges) }
}

function narrowLayout(a: Arch, width: number): ArchLayout {
  const places: Record<string, Place> = {}, bands: BandSpec[] = [], edges: EdgeSpec[] = []
  const IH = 62, GAP = 28, TOP = 38
  const first = a.lanes[0].ids[0]
  // the first input that feeds the first card sits right above it; the others come in on rails
  const direct = a.inputs.find((i) => i.to === first) || null
  const railed = a.inputs.filter((i) => i !== direct)
  const order = [...railed, ...(direct ? [direct] : [])]
  const railW = railed.length ? 10 + railed.length * 10 : 0
  const hasSide = a.sides.length > 0
  const left = hasSide ? 24 : 12, cardW = width - railW - left - 12
  let y = 0
  order.forEach((i) => { places[i.id] = { x: 0, y, w: width - railW, h: IH }; y += IH + 14 })
  if (order.length) y += direct?.label ? 26 : 10
  a.lanes.forEach((l) => {
    const top = y
    let cy = top + TOP
    for (const id of l.ids) {
      const H = Math.max(56, cardH(a.nodes[id], cardW, true))
      places[id] = { x: left, y: cy, w: cardW, h: H }
      cy += H + GAP
      const s = a.sides.find((x) => x.parent === id)
      if (s) { places[s.id] = { x: left + 28, y: cy + 8, w: cardW - 28, h: s.desc ? 68 : 52 }; cy += places[s.id].h + 8 + GAP }
    }
    const bottom = cy - GAP + 16
    bands.push({ x: 0, y: top, w: width - railW, h: bottom - top, title: l.title, note: l.note })
    y = bottom + 44
  })
  const height = y - 44
  const P = (id: string) => places[id]
  const cx = (p: Place, f = 0.5) => p.x + p.w * f
  const spine = left + cardW - 36 // the main line runs down the right side, clear of each band's name
  const seq = a.lanes.flatMap((l) => l.ids)
  seq.forEach((id, k) => {
    const nid = seq[k + 1]
    if (!nid) return
    const s = P(id), t = P(nid)
    const lane = a.lanes.find((l) => l.ids[0] === nid)
    const gap = lane ? (s.y + s.h + t.y) / 2 : 0
    if (a.sides.some((x) => x.parent === id)) {
      // around the helper hanging under this card, along the left edge
      edges.push({ s: id, t: nid, label: lane?.label || '', pts: [[s.x, s.y + s.h / 2], [8, s.y + s.h / 2], [8, t.y + t.h / 2], [t.x, t.y + t.h / 2]], at: lane ? [16, gap] : undefined, side: 'r' })
    } else {
      edges.push({ s: id, t: nid, label: lane?.label || '', pts: [[spine, s.y + s.h], [spine, t.y]], at: lane ? [spine - 10, gap] : undefined, side: 'l' })
    }
  })
  for (const s of a.sides) {
    const p = P(s.parent), q = P(s.id), my = (p.y + p.h + q.y) / 2
    edges.push({ s: s.parent, t: s.id, label: s.out, pts: [[cx(q, 0.3), p.y + p.h], [cx(q, 0.3), q.y]], at: [cx(q, 0.3) - 8, my], inBand: true, side: 'l' })
    edges.push({ s: s.id, t: s.parent, label: s.back, pts: [[cx(q, 0.7), q.y], [cx(q, 0.7), p.y + p.h]], at: [cx(q, 0.7) + 8, my], inBand: true, side: 'r' })
  }
  if (direct) {
    const p = P(direct.id), t = P(first)
    edges.push({ s: direct.id, t: first, label: direct.label, pts: [[spine, p.y + p.h], [spine, t.y]], at: [spine - 10, p.y + p.h + 13], side: 'l' })
  }
  railed.forEach((i, k) => {
    const p = P(i.id), t = P(i.to), rx = width - railW + 10 + k * 10, my = p.y + p.h / 2, ty = t.y + 18 + k * 10
    edges.push({ s: i.id, t: i.to, label: '', pts: [[p.x + p.w, my], [rx, my], [rx, ty], [t.x + t.w, ty]] })
  })
  return { width, height, narrow: true, places, bands, edges, ...walk(a, edges) }
}

/* ---------------------------------------------------------------- drawing */

const NS = 'http://www.w3.org/2000/svg'
function svgEl<K extends keyof SVGElementTagNameMap>(tag: K, attrs: Record<string, string | number>, parent?: Element): SVGElementTagNameMap[K] {
  const e = document.createElementNS(NS, tag)
  for (const k in attrs) e.setAttribute(k, String(attrs[k]))
  parent?.append(e)
  return e
}
function el(tag: string, cls: string, text?: string): HTMLElement {
  const e = document.createElement(tag)
  e.className = cls
  if (text != null) e.textContent = text
  return e
}
function icon(name: string, kind: ArchKind): SVGSVGElement {
  const s = svgEl('svg', { viewBox: '0 0 24 24', 'aria-hidden': 'true', class: 'ac-ic' })
  s.innerHTML = iconFor(name, kind)
  return s
}
function rounded(pts: Pt[], R = 12): string {
  let d = `M${pts[0][0]} ${pts[0][1]}`
  for (let k = 1; k < pts.length; k++) {
    const [x, y] = pts[k], nx = pts[k + 1]
    if (!nx) { d += ` L${x} ${y}`; break }
    const [px, py] = pts[k - 1]
    const r = Math.min(R, Math.hypot(x - px, y - py) / 2, Math.hypot(nx[0] - x, nx[1] - y) / 2)
    const u = [Math.sign(x - px), Math.sign(y - py)], v = [Math.sign(nx[0] - x), Math.sign(nx[1] - y)]
    d += ` L${x - u[0] * r} ${y - u[1] * r} Q${x} ${y} ${x + v[0] * r} ${y + v[1] * r}`
  }
  return d
}
const ease = (t: number) => (t < 0.5 ? 2 * t * t : 1 - (-2 * t + 2) ** 2 / 2)

interface EdgeView { spec: EdgeSpec; p: SVGPathElement; ah: SVGPathElement; d: string; len: number; l?: HTMLElement }
const BEAM = [{ len: 22, w: 6, o: 0.4, glow: true }, { len: 90, w: 2, o: 0.14 }, { len: 48, w: 2, o: 0.35 }, { len: 22, w: 2.5, o: 1 }]
const DWELL = { start: 1100, plain: 1400, key: 2400, gate: 1600 }

class ArchView {
  private root: HTMLElement
  private frame: HTMLElement
  private stage!: HTMLElement
  private a: Arch
  private L!: ArchLayout
  private cards: Record<string, HTMLElement> = {}
  private edges: EdgeView[] = []
  private beam: SVGPathElement[] = []
  private beamG!: SVGGElement
  private width = 0
  private observers: { disconnect(): void }[] = []
  private timers: number[] = []
  private arriveTimers = new Map<string, number>()
  private raf = 0
  private last = 0
  private running = false
  private visible = false
  private entered = false
  private openId: string | null = null
  private pop: HTMLElement
  private phase: 'start' | 'move' | 'dwell' | 'rest' = 'start'
  private seg = 0
  private t = 0
  private lit: string | null = null
  private litEdge: EdgeView | null = null
  private offDoc: () => void

  private expand: HTMLButtonElement | null = null
  private full: boolean

  constructor(root: HTMLElement, a: Arch, full = false) {
    this.root = root
    this.full = full
    this.a = a
    root.replaceChildren()
    root.classList.add('ac-root')
    if (a.gist) root.append(el('p', 'ac-gist', a.gist))
    this.frame = el('div', 'ac-frame')
    const cap = el('div', 'ac-cap')
    const name = a.repo ? a.repo.split('/')[1] : ''
    cap.append(el('b', '', name ? `${name} 怎麼運作` : '怎麼運作'))
    if (a.note) cap.append(el('span', '', a.note))
    if (!full) {
      // a diagram too wide for the reading column is stacked; this opens it full screen, side by side
      const bt = el('button', 'ac-expand', '展開') as HTMLButtonElement
      bt.type = 'button'; bt.hidden = true
      bt.setAttribute('aria-label', '用全螢幕看完整架構圖')
      bt.prepend(expandIcon())
      bt.addEventListener('click', (ev) => { ev.stopPropagation(); openFull(a, bt) })
      cap.append(bt); this.expand = bt
    }
    this.stage = el('div', 'ac-stage')
    this.frame.append(cap, this.stage)
    root.append(this.frame, el('p', 'ac-foot', a.sides.length ? '光束走一次完整的使用流程，虛線是元件另外呼叫的程序；點卡片看細節' : '光束走一次完整的使用流程；點卡片看細節'))
    this.pop = el('div', 'ac-pop')
    this.pop.setAttribute('role', 'dialog')
    this.pop.addEventListener('click', (ev) => ev.stopPropagation())
    // Esc that closes an open card stops there, so it does not also close the reader behind it
    const onDoc = (ev: Event) => {
      if (ev.type === 'click') { this.close(); return }
      if ((ev as KeyboardEvent).key === 'Escape' && this.openId) { this.close(); ev.stopPropagation() }
    }
    document.addEventListener('click', onDoc)
    document.addEventListener('keydown', onDoc)
    this.offDoc = () => { document.removeEventListener('click', onDoc); document.removeEventListener('keydown', onDoc) }

    const ro = new ResizeObserver(() => this.relayout())
    ro.observe(this.frame)
    const io = new IntersectionObserver(([en]) => {
      this.visible = en.isIntersecting
      if (this.visible && !this.entered && this.stage.childElementCount) { this.entered = true; this.enter() }
      this.kick()
    }, { threshold: 0.25 })
    io.observe(this.frame)
    // switching theme changes the ground the labels must match
    const mo = new MutationObserver(() => this.matchGround())
    mo.observe(document.documentElement, { attributes: true, attributeFilter: ['class'] })
    this.observers.push(ro, io, mo)
    this.relayout()
  }

  // 2026-11-17 the diagram stays inside the reading column, aligned with the text (it used to step out
  // to 1120px, which pushed its title left of the text and left it off-centre); too wide → stacked + 展開

  /** Line labels hide the line under them with the colour the diagram sits on; it differs per theme and view. */
  private matchGround() {
    for (let e = this.root.parentElement; e; e = e.parentElement) {
      const c = getComputedStyle(e).backgroundColor
      if (c && c !== 'transparent' && !/^rgba\(.*,\s*0\)$/.test(c)) { this.root.style.setProperty('--ac-frame', c); return }
    }
  }

  private relayout() {
    this.matchGround()
    const cs = getComputedStyle(this.frame)
    const w = Math.floor(this.frame.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight))
    if (!w || w === this.width) return
    this.width = w
    this.close()
    this.draw(layoutArch(this.a, w))
  }

  private draw(L: ArchLayout) {
    this.L = L
    const st = this.stage
    st.replaceChildren(); this.cards = {}; this.edges = []
    st.classList.remove('ac-focus')
    st.classList.toggle('ac-narrow', L.narrow)
    // full screen: the summary and title line up with the diagram, not with the whole sheet
    if (this.full) this.root.style.maxWidth = `${L.width}px`
    // worth opening full screen only when the screen has room to lay it out side by side
    if (this.expand) this.expand.hidden = !(L.narrow && layoutArch(this.a, Math.min(window.innerWidth - 64, 1400)).narrow === false)
    st.style.width = `${L.width}px`; st.style.height = `${L.height}px`
    for (const b of L.bands) {
      const d = el('div', 'ac-band')
      Object.assign(d.style, { left: `${b.x}px`, top: `${b.y}px`, width: `${b.w}px`, height: `${b.h}px` })
      const lb = el('div', 'ac-lb')
      if (b.lbLeft) lb.style.left = `${b.lbLeft}px`
      if (b.title) lb.append(el('b', '', b.title))
      if (b.note) lb.append(document.createTextNode(b.note))
      d.append(lb); st.append(d)
    }
    // the lines go over the bands (which are opaque) and under the cards
    const svg = svgEl('svg', { width: L.width, height: L.height, 'aria-hidden': 'true' })
    st.append(svg)
    const all: ArchNode[] = [...this.a.inputs, ...this.a.lanes.flatMap((l) => l.ids.map((id) => this.a.nodes[id])), ...this.a.sides]
    for (const n of all) {
      const p = L.places[n.id]
      if (!p) continue
      const c = el('div', `ac-nd ac-${n.kind}`)
      c.append(icon(n.icon, n.kind), el('b', '', n.title))
      if (n.desc) c.append(el('p', '', n.desc))
      if (n.tag) c.append(el('i', '', n.tag))
      Object.assign(c.style, { left: `${p.x}px`, top: `${p.y}px`, width: `${p.w}px`, height: `${p.h}px` })
      if (n.more || n.facts.length || n.files.length || n.desc) {
        c.classList.add('ac-has')
        c.tabIndex = 0
        c.setAttribute('role', 'button')
        c.setAttribute('aria-label', `${n.title}，看詳細說明`)
        c.setAttribute('aria-expanded', 'false')
        const toggle = (ev: Event) => { ev.stopPropagation(); if (this.openId === n.id) this.close(); else this.open(n.id) }
        c.addEventListener('click', toggle)
        c.addEventListener('keydown', (ev) => { if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); toggle(ev) } })
      }
      c.addEventListener('pointerenter', (ev) => { if (ev.pointerType === 'mouse') this.focus(n.id) })
      c.addEventListener('pointerleave', () => this.focus(null))
      st.append(c); this.cards[n.id] = c
    }
    for (const spec of L.edges) {
      const pts = spec.pts.map((q) => [...q] as Pt)
      const [ex, ey] = pts[pts.length - 1], [px, py] = pts[pts.length - 2]
      const ang = Math.atan2(ey - py, ex - px)
      pts[pts.length - 1] = [ex - Math.cos(ang), ey - Math.sin(ang)]
      const d = rounded(pts)
      const p = svgEl('path', { d, class: 'ac-ed' }, svg)
      const ah = svgEl('path', { d: 'M-6 -4 L0 0 L-6 4', class: 'ac-ah', transform: `translate(${ex},${ey}) rotate(${ang * 180 / Math.PI})` }, svg)
      let l: HTMLElement | undefined
      if (spec.label && spec.at) {
        l = el('div', `ac-el${spec.inBand ? ' ac-inband' : ''}${spec.side ? ` ac-${spec.side}` : ''}`, spec.label)
        Object.assign(l.style, { left: `${spec.at[0]}px`, top: `${spec.at[1]}px` })
        st.append(l)
      }
      this.edges.push({ spec, p, ah, d, len: p.getTotalLength(), l })
    }
    const defs = svgEl('defs', {}, svg)
    const fid = `ac-glow-${Math.random().toString(36).slice(2, 8)}`
    const flt = svgEl('filter', { id: fid, x: '-50%', y: '-50%', width: '200%', height: '200%' }, defs)
    svgEl('feGaussianBlur', { stdDeviation: 3 }, flt)
    this.beamG = svgEl('g', { class: 'ac-beam' }, svg)
    this.beam = BEAM.map((b) => svgEl('path', { 'stroke-width': b.w, 'stroke-opacity': b.o, ...(b.glow ? { filter: `url(#${fid})` } : {}) }, this.beamG))
    this.beamG.style.opacity = '0'
    this.phase = 'start'; this.t = 0; this.seg = 0; this.lit = null; this.litEdge = null
    if (this.entered) { st.classList.add('ac-in', 'ac-still'); this.running = true; this.kick() }
    else st.classList.add('ac-pre')
    if (!this.entered && this.visible) { this.entered = true; this.enter() }
  }

  /** Cards rise in flow order, then the lines draw themselves, then arrows and labels appear. */
  private enter() {
    const st = this.stage
    const L = this.L
    const order = [...new Set([L.start, ...L.route.map((r) => r.to), ...Object.keys(this.cards)].filter(Boolean) as string[])]
    order.forEach((id, k) => this.cards[id]?.style.setProperty('--d', `${k * 110}ms`))
    this.edges.forEach((e, i) => { e.p.style.strokeDasharray = `${e.len} ${e.len}`; e.p.style.strokeDashoffset = `${e.len}`; e.p.style.setProperty('--d', `${700 + i * 90}ms`) })
    const drawEnd = 700 + this.edges.length * 90 + 1800
    st.style.setProperty('--after-draw', `${drawEnd - 300}ms`)
    st.classList.remove('ac-pre'); st.classList.add('ac-in')
    requestAnimationFrame(() => this.edges.forEach((e) => { e.p.style.strokeDashoffset = '0' }))
    this.timers.push(window.setTimeout(() => {
      this.edges.forEach((e) => { e.p.style.strokeDasharray = ''; e.p.style.strokeDashoffset = '' })
      st.classList.add('ac-still')
      this.running = true; this.kick()
    }, drawEnd + 60))
  }

  private kick() {
    if (!this.raf && this.running && this.visible && !this.openId) this.raf = requestAnimationFrame(this.frameFn)
  }

  private frameFn = (now: number) => {
    this.raf = 0
    if (!this.running || !this.visible || this.openId) { this.last = 0; return }
    const dt = this.last ? Math.min(50, now - this.last) : 0
    this.last = now
    this.step(dt)
    this.raf = requestAnimationFrame(this.frameFn)
  }

  private light(id: string | null) {
    if (this.lit === id) return
    if (this.lit) this.cards[this.lit]?.classList.remove('ac-live')
    this.lit = id
    if (!id || !this.cards[id]) return
    const c = this.cards[id]
    clearTimeout(this.arriveTimers.get(id)); c.classList.remove('ac-arrive'); void c.offsetWidth
    c.classList.add('ac-live', 'ac-arrive')
    // the arrival animation plays to its end, even after the beam has moved on
    this.arriveTimers.set(id, window.setTimeout(() => c.classList.remove('ac-arrive'), 2000))
  }

  private setBeam(e: EdgeView | null, p: number, alpha: number) {
    if (!e) { this.beamG.style.opacity = '0'; return }
    const head = e.len * p
    this.beam.forEach((b, i) => {
      if (b.getAttribute('d') !== e.d) { b.setAttribute('d', e.d); b.setAttribute('stroke-dasharray', `${BEAM[i].len} ${e.len + 400}`) }
      b.setAttribute('stroke-dashoffset', String(BEAM[i].len - head))
    })
    this.beamG.style.opacity = String(alpha)
  }

  private markEdge(e: EdgeView | null) {
    if (this.litEdge === e) return
    this.litEdge?.p.classList.remove('ac-lit'); this.litEdge?.ah.classList.remove('ac-lit')
    this.litEdge = e
    e?.p.classList.add('ac-lit'); e?.ah.classList.add('ac-lit')
  }

  private dwell(id: string) { const k = this.a.nodes[id]?.kind; return k === 'key' ? DWELL.key : k === 'gate' ? DWELL.gate : DWELL.plain }

  /** One line at a time: the beam runs it, fades on the card it reaches, the card holds a while. */
  private step(dt: number) {
    const route = this.L.route
    this.t += dt
    if (!route.length) return
    if (this.phase === 'start') {
      this.light(this.L.start); this.setBeam(null, 0, 0); this.markEdge(null)
      if (this.t >= DWELL.start) { this.phase = 'move'; this.t = 0; this.seg = 0 }
      return
    }
    if (this.phase === 'rest') {
      if (this.t >= 2600) { this.phase = 'start'; this.t = 0 }
      return
    }
    const r = route[this.seg], e = this.edges[r.e]
    if (this.phase === 'move') {
      this.markEdge(e)
      if (this.t < 120 && this.lit) this.light(null)
      const dur = Math.min(1400, Math.max(450, e.len / 0.26)), p = Math.min(1, this.t / dur)
      this.setBeam(e, ease(p), Math.min(1, this.t / 160))
      if (p >= 1) { this.phase = 'dwell'; this.t = 0; this.light(r.to) }
      return
    }
    this.setBeam(e, 1, Math.max(0, 1 - this.t / 280))
    if (this.t >= this.dwell(r.to)) {
      if (this.seg + 1 < route.length) { this.seg += 1; this.phase = 'move'; this.t = 0 }
      else { this.phase = 'rest'; this.t = 0; this.light(null); this.markEdge(null); this.setBeam(null, 0, 0) }
    }
  }

  /** Hovering a card keeps it, its neighbours and their lines; the rest steps back. */
  private focus(id: string | null) {
    const st = this.stage
    if (id && this.openId) return
    st.classList.toggle('ac-focus', !!id)
    st.querySelectorAll('.ac-on').forEach((x) => x.classList.remove('ac-on', 'ac-hot'))
    if (!id) return
    this.cards[id]?.classList.add('ac-on', 'ac-hot')
    for (const e of this.edges) {
      if (e.spec.s !== id && e.spec.t !== id) continue
      e.p.classList.add('ac-on'); e.ah.classList.add('ac-on'); e.l?.classList.add('ac-on')
      this.cards[e.spec.s]?.classList.add('ac-on'); this.cards[e.spec.t]?.classList.add('ac-on')
    }
  }

  private open(id: string) {
    const n = this.a.nodes[id], c = this.cards[id], p = this.L.places[id]
    if (!n || !c || !p) return
    if (this.openId) this.cards[this.openId]?.classList.remove('ac-picked')
    this.openId = id
    this.focus(null)
    c.classList.add('ac-picked'); this.stage.classList.add('ac-picking')
    c.setAttribute('aria-expanded', 'true')
    const reach = this.reach(id)
    const pop = this.pop
    pop.replaceChildren()
    const x = el('button', 'ac-x', '×')
    x.setAttribute('type', 'button'); x.setAttribute('aria-label', '關閉')
    x.addEventListener('click', () => this.close())
    const head = el('div', 'ac-ph')
    head.append(icon(n.icon, n.kind), el('b', '', n.title))
    pop.append(x, head)
    const body = n.more || n.desc
    if (body) pop.append(el('p', 'ac-pm', body))
    if (n.facts.length) { const ul = el('ul', 'ac-pf'); n.facts.forEach((f) => ul.append(el('li', '', f))); pop.append(ul) }
    const name = (nid: string) => this.a.nodes[nid]?.title || ''
    const ins = [...new Set(this.L.edges.filter((e) => e.t === id).map((e) => name(e.s)).filter(Boolean))]
    const outs = [...new Set(this.L.edges.filter((e) => e.s === id).map((e) => name(e.t)).filter(Boolean))]
    if (ins.length || outs.length) {
      const pr = el('div', 'ac-pr')
      if (ins.length) { const s = el('span', ''); s.append(el('i', '', '從'), document.createTextNode(ins.join('、'))); pr.append(s) }
      if (outs.length) { const s = el('span', ''); s.append(el('i', '', '到'), document.createTextNode(outs.join('、'))); pr.append(s) }
      const far = [reach.up > ins.length ? `上游共 ${reach.up} 個` : '', reach.down > outs.length ? `下游共 ${reach.down} 個` : ''].filter(Boolean)
      if (far.length) pr.append(el('span', 'ac-far', far.join('，')))
      pop.append(pr)
    }
    if (n.files.length) {
      const pp = el('div', 'ac-pp')
      for (const raw of n.files) {
        const m = raw.match(/^([\w./-]+?)(?::(\d+)(?:-(\d+))?)?$/)
        if (this.a.repo && m) {
          const [, f, a, b] = m
          const link = el('a', '', a ? `${f} 第 ${a}${b && b !== a ? `–${b}` : ''} 行` : f) as HTMLAnchorElement
          const lines = a ? `#L${a}${b && b !== a ? `-L${b}` : ''}` : ''
          link.href = `https://github.com/${this.a.repo}/blob/${this.a.sha || 'HEAD'}/${f.split('/').map(encodeURIComponent).join('/')}${lines}`
          link.target = '_blank'; link.rel = 'noopener noreferrer'
          pp.append(link)
        } else pp.append(el('span', '', raw))
      }
      pop.append(pp)
    }
    this.stage.append(pop)
    const W = this.L.width, H = this.L.height, pw = Math.min(this.L.narrow ? 420 : 300, W)
    pop.style.width = `${pw}px`
    const ph = pop.offsetHeight
    // try the four sides and keep the one that hides the fewest cards, above all the ones this card
    // connects to; the pop may use the empty frame margin beside the stage
    const fr = this.frame.getBoundingClientRect(), sr = this.stage.getBoundingClientRect()
    const lo = Math.min(0, fr.left + 12 - sr.left), hi = Math.max(W, fr.right - 12 - sr.left)
    const clampX = (x: number) => Math.max(lo, Math.min(x, hi - pw)), clampY = (y: number) => Math.max(0, Math.min(y, Math.max(0, H - ph)))
    const tries: [number, number][] = this.L.narrow
      ? [[clampX(p.x + p.w - pw), p.y + p.h + 8], [clampX(p.x + p.w - pw), p.y - ph - 8]]
      : [[p.x + p.w + 14, clampY(p.y)], [p.x - pw - 14, clampY(p.y)], [clampX(p.x + p.w / 2 - pw / 2), p.y + p.h + 12], [clampX(p.x + p.w / 2 - pw / 2), Math.max(0, p.y - ph - 12)]]
    const cost = ([x, y]: [number, number]) => {
      let c = (x < lo || x + pw > hi ? 1e9 : 0) + Math.max(0, y + ph - H) * pw * 2
      for (const [nid, q] of Object.entries(this.L.places)) {
        const ox = Math.max(0, Math.min(x + pw, q.x + q.w) - Math.max(x, q.x)), oy = Math.max(0, Math.min(y + ph, q.y + q.h) - Math.max(y, q.y))
        const near = this.cards[nid]?.classList.contains('ac-up') || this.cards[nid]?.classList.contains('ac-down')
        c += ox * oy * (nid === id ? 20 : near ? 4 : 1)
      }
      return c
    }
    const [px, py] = tries.reduce((best, t) => (cost(t) < cost(best) ? t : best))
    pop.style.left = `${px}px`; pop.style.top = `${py}px`
    pop.setAttribute('aria-label', `${n.title}的詳細說明`)
    pop.classList.remove('ac-pop-in'); void pop.offsetWidth; pop.classList.add('ac-pop-in')
    // opened from the keyboard: move into the pop so its links are next, and come back on close
    if (c === document.activeElement) x.focus({ preventScroll: true })
    requestAnimationFrame(() => pop.scrollIntoView({ block: 'nearest', behavior: 'smooth' }))
  }

  /** Light the cards and lines that lead to `id` (upstream) and that it leads to (downstream). */
  private reach(id: string): { up: number; down: number } {
    this.unreach()
    const walk = (from: string, fwd: boolean) => {
      const seen = new Set<string>(), todo = [from]
      while (todo.length) {
        const cur = todo.pop() as string
        for (const e of this.edges) {
          const [a, b] = fwd ? [e.spec.s, e.spec.t] : [e.spec.t, e.spec.s]
          if (a !== cur) continue
          for (const x of [e.p, e.ah, e.l]) x?.classList.add(fwd ? 'ac-down' : 'ac-up')
          if (b !== from && !seen.has(b)) { seen.add(b); todo.push(b) }
        }
      }
      seen.forEach((x) => this.cards[x]?.classList.add(fwd ? 'ac-down' : 'ac-up'))
      return seen.size
    }
    return { up: walk(id, false), down: walk(id, true) }
  }

  private unreach() {
    this.stage.querySelectorAll('.ac-up, .ac-down').forEach((x) => x.classList.remove('ac-up', 'ac-down'))
  }

  private close() {
    if (!this.openId) return
    const c = this.cards[this.openId]
    c?.classList.remove('ac-picked'); c?.setAttribute('aria-expanded', 'false')
    if (this.pop.contains(document.activeElement)) c?.focus({ preventScroll: true })
    this.unreach()
    this.pop.remove(); this.stage.classList.remove('ac-picking')
    this.openId = null; this.last = 0
    this.kick()
  }

  destroy() {
    cancelAnimationFrame(this.raf); this.raf = 0; this.running = false
    this.timers.forEach(clearTimeout); this.arriveTimers.forEach(clearTimeout)
    this.observers.forEach((o) => o.disconnect())
    this.offDoc()
  }
}

// every live view, so a block that left the page (its markdown was replaced) can be stopped
const views = new Map<HTMLElement, ArchView>()

function expandIcon(): SVGSVGElement {
  const s = svgEl('svg', { viewBox: '0 0 24 24', class: 'ac-xi', 'aria-hidden': 'true' }) as SVGSVGElement
  svgEl('path', { d: 'M15 3h6v6M9 21H3v-6M21 3l-7 7M3 21l7-7' }, s)
  return s
}

/** The whole diagram on a full-screen sheet, laid out side by side; Esc, the close button or 縮小 brings the reader back. */
function openFull(a: Arch, from: HTMLElement) {
  const sheet = el('div', 'prose-reader ac-sheet')
  sheet.dataset.ownsKeys = '' // the reader's shortcuts (J, K, [, ], Esc…) wait while it is open
  sheet.setAttribute('role', 'dialog'); sheet.setAttribute('aria-modal', 'true'); sheet.setAttribute('aria-label', '完整架構圖')
  const close = el('button', 'ac-sheet-x', '收合') as HTMLButtonElement
  close.type = 'button'
  const block = el('div', 'arch-block')
  sheet.append(close, block)
  document.body.append(sheet)
  const overflow = document.body.style.overflow
  document.body.style.overflow = 'hidden'
  // keep Tab inside the sheet: the app under it cannot take focus while it is open
  const app = document.getElementById('app')
  if (app) app.inert = true
  const view = new ArchView(block, a, true)
  const done = () => {
    view.destroy(); sheet.remove(); document.body.style.overflow = overflow
    if (app) app.inert = false
    document.removeEventListener('keydown', onKey, true); from.focus({ preventScroll: true })
  }
  // Esc closes an open card first (ArchView's own handler), then the sheet
  const onKey = (ev: KeyboardEvent) => { if (ev.key === 'Escape' && !block.querySelector('.ac-pop')) { ev.stopPropagation(); done() } }
  document.addEventListener('keydown', onKey, true)
  close.addEventListener('click', done)
  close.focus({ preventScroll: true })
}

function dropDetached() {
  views.forEach((v, b) => { if (!b.isConnected) { v.destroy(); views.delete(b) } })
}

function fallback(block: HTMLElement, a: Arch | null, code: string) {
  const ol = el('ol', 'mermaid-fallback')
  const names = a ? a.lanes.flatMap((l) => l.ids.map((id) => a.nodes[id].title))
    : code.split('\n').map((l) => l.trim().split(SEP)).filter((f) => f[0] === '元件' && f[3]).map((f) => f[3])
  names.forEach((n) => ol.append(el('li', '', n)))
  block.replaceChildren(ol)
}

/** Draw every not-yet-drawn architecture block inside a rendered markdown container. */
export function renderArchIn(container: HTMLElement | null): void {
  if (!container) return
  // a re-render with the same markdown keeps the blocks and their views; only replaced ones go
  dropDetached()
  for (const block of Array.from(container.querySelectorAll<HTMLElement>('.arch-block:not([data-done])'))) {
    block.dataset.done = '1'
    const code = block.querySelector('.arch-src')?.textContent || ''
    const a = parseArch(code)
    if (!a) { fallback(block, null, code); continue }
    try { views.set(block, new ArchView(block, a)) } catch { fallback(block, a, code) }
  }
}

/** Stop every diagram inside a container that is going away for good (the reader closes). */
export function disposeArchIn(container: HTMLElement | null): void {
  container?.querySelectorAll<HTMLElement>('.arch-block').forEach((b) => { views.get(b)?.destroy(); views.delete(b) })
  dropDetached()
}
