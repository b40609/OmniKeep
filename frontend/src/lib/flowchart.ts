/* Flowcharts in the deep analysis (prompt rule "流程圖" in app/pipeline.py). The model writes a
   ```flow block of plain lines, no quotes, so it survives being a JSON string:

     總結：一句白話
     段：準備                                   (only when there are more than 8 steps)
     A｜開始｜名稱｜一行說明｜小標籤、小標籤｜完整說明｜關卡
     A -> B
     C -> B｜發現缺陷，退回                      (an edge back to an earlier step is a side branch)

   Drawn the way floorplan draws its maps: cards with an icon, a one-line note and tags, the main
   line kept straight and branches dashed at the side, laid out to fit the column (a stack, a row,
   or one column per section). A beam of light runs the whole flow at a steady speed and the card
   it passes under lights up, so the order reads at a glance. Everything is DOM text set with
   textContent; nothing from the model reaches innerHTML. */

export type FlowKind = 'start' | 'work' | 'check' | 'human' | 'done'
export interface FlowStep { id: string; kind: FlowKind; label: string; desc: string; tags: string[]; more: string; gate: string }
export interface FlowEdge { s: string; t: string; label: string; back: boolean }
export interface Flow { gist: string; groups: { label: string; ids: string[] }[]; steps: Record<string, FlowStep>; order: string[]; edges: FlowEdge[] }

const KINDS: Record<string, FlowKind> = { 開始: 'start', 執行: 'work', 檢查: 'check', 人工: 'human', 完成: 'done' }
const ICONS: Record<FlowKind, string> = {
  start: '<path d="M7 4.5v15l12-7.5z"/>',
  work: '<circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M2 12h3M19 12h3M4.9 19.1L7 17M17 7l2.1-2.1"/>',
  check: '<path d="M9 12l2 2 4-4"/><path d="M12 3l8 4v5c0 5-3.5 8-8 9-4.5-1-8-4-8-9V7z"/>',
  human: '<circle cx="12" cy="8" r="4"/><path d="M4 21c1.5-4 4.5-6 8-6s6.5 2 8 6"/>',
  done: '<path d="M5 21V4h11l-2 4 2 4H5"/>',
}
const GATE_ICON = '<circle cx="12" cy="12" r="9"/><path d="M8 12h8"/>'

const SEP = /\s*[｜|]\s*/
export function parseFlow(code: string): Flow | null {
  const flow: Flow = { gist: '', groups: [], steps: {}, order: [], edges: [] }
  let group: { label: string; ids: string[] } | null = null
  for (const raw of code.split('\n')) {
    const line = raw.trim()
    if (!line) continue
    let m = line.match(/^總結[:：]\s*(.+)$/)
    if (m) { flow.gist = m[1]; continue }
    m = line.match(/^段[:：]\s*(.+)$/)
    if (m) { group = { label: m[1], ids: [] }; flow.groups.push(group); continue }
    m = line.match(/^([A-Za-z]\w{0,2})\s*-+>\s*([A-Za-z]\w{0,2})\s*(?:[｜|]\s*(.*))?$/)
    if (m) { flow.edges.push({ s: m[1], t: m[2], label: (m[3] || '').trim(), back: false }); continue }
    const f = line.split(SEP)
    if (f.length >= 3 && /^[A-Za-z]\w{0,2}$/.test(f[0]) && f[2]) {
      const id = f[0]
      if (flow.steps[id]) continue
      flow.steps[id] = {
        id, kind: KINDS[f[1]] || 'work', label: f[2], desc: f[3] || '',
        tags: (f[4] || '').split(/[、,，]/).map((t) => t.trim()).filter(Boolean).slice(0, 3),
        more: f[5] || '', gate: f[6] || '',
      }
      flow.order.push(id)
      if (!group) { group = { label: '', ids: [] }; flow.groups.push(group) }
      group.ids.push(id)
    }
  }
  flow.groups = flow.groups.filter((g) => g.ids.length)
  // A long flow the model left in one piece is split evenly, so it can sit in columns.
  if (flow.groups.length === 1 && !flow.groups[0].label && flow.order.length > 8) {
    const k = Math.min(3, Math.ceil(flow.order.length / 4)), per = Math.ceil(flow.order.length / k)
    flow.groups = Array.from({ length: k }, (_, i) => ({ label: '', ids: flow.order.slice(i * per, (i + 1) * per) })).filter((g) => g.ids.length)
  }
  flow.edges = flow.edges.filter((e) => flow.steps[e.s] && flow.steps[e.t] && e.s !== e.t)
  if (flow.order.length < 2) return null
  if (!flow.edges.length) for (let i = 1; i < flow.order.length; i++) flow.edges.push({ s: flow.order[i - 1], t: flow.order[i], label: '', back: false })
  const idx = (id: string) => flow.order.indexOf(id)
  for (const e of flow.edges) e.back = idx(e.t) <= idx(e.s)
  return flow
}

/** The beam's route: one walk through the flow from the first step, always taking the edge to
 *  the nearest later step; a branch back is taken once when the walk first reaches its source,
 *  and the steps it skipped are walked again. Edges off this walk are drawn but not animated. */
export function flowRoute(flow: Flow): FlowEdge[] {
  const idx = (id: string) => flow.order.indexOf(id)
  const next = (at: string) => flow.edges.filter((e) => !e.back && e.s === at).sort((a, b) => idx(a.t) - idx(b.t))[0]
  const route: FlowEdge[] = []
  const used = new Set<FlowEdge>()
  const walk = (from: string, until: string) => {
    for (let cur = from, n = 0; cur !== until && n < flow.order.length; n++) { const e = next(cur); if (!e) return; route.push(e); cur = e.t }
  }
  let cur = flow.order[0]
  for (let n = 0; n <= flow.order.length * 2; n++) {
    for (const b of flow.edges) {
      if (!b.back || used.has(b) || b.s !== cur) continue
      used.add(b); route.push(b); walk(b.t, cur)
    }
    const e = next(cur)
    if (!e) break
    route.push(e); cur = e.t
  }
  return route
}

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
function icon(paths: string): SVGSVGElement {
  // The paths are the constants above, never model text.
  const s = svgEl('svg', { viewBox: '0 0 24 24', 'aria-hidden': 'true' })
  s.innerHTML = paths
  return s
}
function rounded(pts: [number, number][]): string {
  let d = `M${pts[0][0]} ${pts[0][1]}`
  for (let k = 1; k < pts.length; k++) {
    const [x, y] = pts[k], nx = pts[k + 1]
    if (!nx) { d += ` L${x} ${y}`; break }
    const [px, py] = pts[k - 1]
    const r = Math.min(10, Math.hypot(x - px, y - py) / 2, Math.hypot(nx[0] - x, nx[1] - y) / 2)
    const u = [Math.sign(x - px), Math.sign(y - py)], v = [Math.sign(nx[0] - x), Math.sign(nx[1] - y)]
    d += ` L${x - u[0] * r} ${y - u[1] * r} Q${x} ${y} ${x + v[0] * r} ${y + v[1] * r}`
  }
  return d
}

interface EdgeView { e: FlowEdge; p: SVGPathElement; ah: SVGPathElement; lb: HTMLElement | null }
type Box = { x: number; y: number; w: number; h: number }

class FlowView {
  private root: HTMLElement
  private stage: HTMLElement
  private cap: HTMLElement
  private capId: string | null | undefined = undefined
  private cards: Record<string, HTMLElement> = {}
  private edges: EdgeView[] = []
  private sel: string | null = null
  private beam: { total: number; g: SVGGElement; paths: SVGPathElement[]; lens: number[]; marks: { e: FlowEdge; from: number; to: number }[] } | null = null
  private head = 0
  private litId: string | null = null
  private rest = 0
  private paused = false
  private visible = false
  private last = 0
  private raf = 0
  private width = 0
  private observers: { disconnect(): void }[] = []

  private flow: Flow

  constructor(root: HTMLElement, flow: Flow) {
    this.flow = flow
    this.root = root
    root.replaceChildren()
    if (flow.gist) root.append(el('p', 'fc-gist', flow.gist))
    this.stage = el('div', 'fc-stage')
    root.append(this.stage)
    this.cap = el('div', 'fc-cap')
    // a flow whose steps carry nothing beyond the card has no caption to show
    const extra = flow.order.some((id) => { const s = flow.steps[id]; return s.more || s.gate || s.tags.length }) || flow.edges.some((e) => e.label)
    if (extra) root.append(this.cap)
    this.stage.addEventListener('click', () => { if (this.sel) this.select(null) })
    const ro = new ResizeObserver(() => { this.fit(); const w = this.stage.clientWidth; if (w && w !== this.width) { this.width = w; this.layout() } })
    ro.observe(this.stage)
    const io = new IntersectionObserver(([en]) => { this.visible = en.isIntersecting }, { threshold: 0.3 })
    io.observe(this.stage)
    this.observers.push(ro, io)
    // on a wide screen the chart steps out of the reading column, up to 1120px, but never past the
    // nearest scrolling panel, so a reader shown in a side panel keeps it inside
    const bound = this.bound()
    if (bound) { const fo = new ResizeObserver(() => this.fit()); fo.observe(bound); this.observers.push(fo) }
    this.fit()
    this.caption(flow.order[0])
    this.raf = requestAnimationFrame(this.frame)
  }

  private bound(): HTMLElement | null {
    for (let e = this.root.parentElement; e; e = e.parentElement) {
      if (e === document.body) return e
      const st = getComputedStyle(e)
      if (st.overflowX !== 'visible' || st.overflowY !== 'visible') return e
    }
    return null
  }

  private fit() {
    const root = this.root, bound = this.bound()
    root.style.marginLeft = ''; root.style.width = ''
    if (!bound) return
    const a = bound.getBoundingClientRect(), c = root.getBoundingClientRect()
    if (!c.width) return // inside a closed section; fitted again when it opens
    const W = Math.min(1120, a.width - 48)
    if (W <= c.width + 40) return
    const left = Math.max(a.left + 24, Math.min(c.left + c.width / 2 - W / 2, a.right - 24 - W))
    root.style.marginLeft = `${left - c.left}px`; root.style.width = `${W}px`
  }

  destroy() { cancelAnimationFrame(this.raf); this.observers.forEach((o) => o.disconnect()) }

  private cardFor(id: string, n: number): HTMLElement {
    const s = this.flow.steps[id]
    const c = el('div', `fc-card fc-c-${s.kind}`)
    c.setAttribute('role', 'button')
    c.tabIndex = 0
    const head = el('div', 'fc-head')
    const ico = el('span', `fc-ico fc-k-${s.kind}`)
    ico.append(icon(ICONS[s.kind]))
    head.append(ico, el('span', 'fc-title', s.label), el('span', 'fc-no', `${this.flow.order.indexOf(id) + 1}/${n}`))
    c.append(head)
    if (s.desc) c.append(el('div', 'fc-desc', s.desc))
    const toggle = (ev: Event) => { ev.stopPropagation(); this.select(this.sel === id ? null : id) }
    c.addEventListener('click', toggle)
    c.addEventListener('keydown', (ev) => { if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); toggle(ev) } })
    return c
  }

  /** The caption under the chart tells the step the beam is on (or the one picked): what it
   *  does, its numbers, where it stops, and where it goes next and when. */
  private caption(id: string | null) {
    if (id === this.capId) return
    this.capId = id
    const cap = this.cap
    cap.classList.remove('fc-cap-in'); void cap.offsetWidth; cap.classList.add('fc-cap-in')
    if (!id) { cap.replaceChildren(); return }
    const s = this.flow.steps[id], n = this.flow.order.length, picked = this.sel === id
    const head = el('div', 'fc-cap-head')
    head.append(el('span', `fc-cap-dot fc-k-${s.kind}`), el('span', 'fc-cap-no', `${this.flow.order.indexOf(id) + 1}/${n}`), el('b', '', s.label))
    if (!picked) head.append(el('span', 'fc-cap-tip', '點步驟可停下來細看'))
    const body: HTMLElement[] = [head]
    // the card already shows the one-line note; the caption adds the full one
    if (s.more || (picked && s.desc)) body.push(el('p', 'fc-cap-desc', s.more || s.desc))
    const meta = el('div', 'fc-cap-meta')
    s.tags.forEach((t) => meta.append(el('span', 'fc-tag', t)))
    if (s.gate) { const g = el('span', 'fc-cap-gate'); g.append(icon(GATE_ICON), document.createTextNode(s.gate)); meta.append(g) }
    for (const e of this.flow.edges) {
      if (e.s !== id || !e.label) continue
      const g = el('span', `fc-cap-next${e.back ? ' fc-cap-back' : ''}`)
      g.append(document.createTextNode(`${e.label} → `), el('b', '', this.flow.steps[e.t].label))
      meta.append(g)
    }
    if (meta.childNodes.length) body.push(meta)
    cap.replaceChildren(...body)
  }

  /* Layout: rows read left to right and wrap, like text; a section starts a new row. On a phone a
     row holds one card, so the same rules give a single column. Every edge that is not a plain
     step to the right runs in the gap between rows, each on a lane of its own, and every edge end
     gets its own port on the card, so no two lines or arrowheads share a spot. */
  private layout() {
    const { flow, stage } = this
    stage.replaceChildren()
    this.cards = {}
    this.edges = []
    const W = stage.clientWidth, narrow = W < 480, P = narrow ? 14 : 20, order = flow.order, N = order.length

    // rows
    // conditions between neighbours in a row are told by the caption, so the gap stays narrow
    const colGap = 40
    const backCount = flow.edges.filter((e) => e.back).length
    const rg = backCount ? 18 + backCount * 8 : 0
    let k = 1
    if (!narrow) for (let n = 4; n >= 2; n--) if ((W - P * 2 - rg - (n - 1) * colGap) / n >= 200) { k = n; break }
    const rows: { label: string; group: number; ids: string[] }[] = []
    // rows of a section are filled evenly (5 steps on 4 columns give 3 + 2, not 4 + 1)
    flow.groups.forEach((g, gi) => {
      const per = Math.ceil(g.ids.length / Math.ceil(g.ids.length / k))
      for (let i = 0; i < g.ids.length; i += per) rows.push({ label: i === 0 ? g.label : '', group: gi, ids: g.ids.slice(i, i + per) })
    })
    const R = rows.length
    const rowOf: Record<string, number> = {}, colOf: Record<string, number> = {}
    rows.forEach((r, ri) => r.ids.forEach((id, ci) => { rowOf[id] = ri; colOf[id] = ci }))

    // edge kinds, and the gaps (0 = above the first row, R = below the last) each one runs through
    type Kind = 'h' | 'over' | 'down' | 'far' | 'under' | 'back1' | 'up'
    const kind = (e: FlowEdge): Kind => {
      const rs = rowOf[e.s], rt = rowOf[e.t]
      if (!e.back) {
        if (rt === rs) return colOf[e.t] === colOf[e.s] + 1 ? 'h' : 'over'
        return rt === rs + 1 ? 'down' : 'far'
      }
      return rt === rs ? 'under' : rt === rs - 1 ? 'back1' : 'up'
    }
    const lanes: FlowEdge[][] = Array.from({ length: R + 1 }, () => [])
    const second = new Map<FlowEdge, number>()
    const slot = new Map<FlowEdge, number>()
    let leftSlots = 0, rightSlots = 0
    for (const e of flow.edges) {
      const rs = rowOf[e.s], rt = rowOf[e.t], kd = kind(e)
      if (kd === 'h') continue
      if (kd === 'over') lanes[rs].push(e)
      else if (kd === 'down' || kd === 'under') lanes[rs + 1].push(e)
      else if (kd === 'back1') lanes[rs].push(e)
      else if (kd === 'far') { lanes[rs + 1].push(e); lanes[rt].push(e); second.set(e, rt); slot.set(e, leftSlots++) }
      else { lanes[rs + 1].push(e); lanes[rt + 1].push(e); second.set(e, rt + 1); slot.set(e, rightSlots++) }
    }
    const lg = leftSlots ? 18 + leftSlots * 8 : 0
    const kc = Math.max(...rows.map((r) => r.ids.length)) // columns actually used
    const cw = Math.min(narrow ? 420 : 300, (W - P * 2 - rg - lg - (kc - 1) * colGap) / kc)
    const gridW = kc * cw + (kc - 1) * colGap
    const x0 = lg + (W - lg - rg - gridW) / 2

    // cards, equal height within a row
    for (const id of order) { const c = this.cardFor(id, N); c.style.width = `${cw}px`; stage.append(c); this.cards[id] = c }
    const rowH = rows.map((r) => Math.max(...r.ids.map((id) => this.cards[id].offsetHeight)))
    const laneH = (e: FlowEdge) => (e.label ? 26 : 16)
    const LABEL = 26
    const labelIn = (g: number) => (g < R && rows[g].label ? LABEL : 0)
    const gapH = lanes.map((ls, g) => {
      const inner = ls.reduce((a, e) => a + laneH(e), 0)
      const min = g === 0 || g === R ? 0 : 40
      return labelIn(g) + Math.max(min, ls.length ? inner + 36 : 0)
    })
    const gapTop: number[] = [], rowY: number[] = []
    let y = P
    for (let g = 0; g <= R; g++) { gapTop[g] = y; y += gapH[g]; if (g < R) { rowY[g] = y; y += rowH[g] } }
    const stageH = y + P
    stage.style.height = `${stageH}px`
    const pos: Record<string, Box> = {}
    order.forEach((id, i) => {
      const r = rowOf[id], c = this.cards[id]
      pos[id] = { x: x0 + colOf[id] * (cw + colGap), y: rowY[r], w: cw, h: rowH[r] }
      c.style.left = `${pos[id].x}px`; c.style.top = `${pos[id].y}px`; c.style.height = `${rowH[r]}px`
      c.style.setProperty('--d', `${i * 60}ms`)
    })
    // a section label sits at the bottom of the gap above its row; lanes use the rest of the gap
    rows.forEach((r, ri) => {
      if (!r.label) return
      const g = el('div', 'fc-group', r.label)
      g.append(el('i', '', `${flow.groups[r.group].ids.length} 步`))
      g.style.left = `${x0}px`; g.style.top = `${rowY[ri] - LABEL}px`
      stage.append(g)
    })
    const laneY = new Map<string, number>()
    const key = (g: number, e: FlowEdge) => `${g}:${flow.edges.indexOf(e)}`
    lanes.forEach((ls, g) => {
      const inner = ls.reduce((a, e) => a + laneH(e), 0)
      let yy = gapTop[g] + (gapH[g] - labelIn(g) - inner) / 2
      for (const e of ls) { laneY.set(key(g, e), yy + laneH(e) / 2); yy += laneH(e) }
    })
    const LY = (g: number, e: FlowEdge) => laneY.get(key(g, e))!

    // ports: each edge end gets its own spot on the card's top or bottom
    // a card's top and the bottom of the card above it face the same gap, so their ends share one
    // list and get distinct spots; an edge straight down that column keeps one spot and stays straight
    const ports = new Map<string, FlowEdge[]>()
    const pkey = (id: string, side: 'top' | 'bot') => `${side === 'top' ? rowOf[id] : rowOf[id] + 1}:${colOf[id]}`
    const addPort = (id: string, side: 'top' | 'bot', e: FlowEdge) => { const k2 = pkey(id, side); if (!ports.has(k2)) ports.set(k2, []); const l = ports.get(k2)!; if (!l.includes(e)) l.push(e) }
    for (const e of flow.edges) {
      const kd = kind(e)
      if (kd === 'h') continue
      if (kd === 'over') { addPort(e.s, 'top', e); addPort(e.t, 'top', e) }
      else if (kd === 'down' || kd === 'far') { addPort(e.s, 'bot', e); addPort(e.t, 'top', e) }
      else if (kd === 'back1') { addPort(e.s, 'top', e); addPort(e.t, 'bot', e) }
      else { addPort(e.s, 'bot', e); addPort(e.t, 'bot', e) }
    }
    const portX = (id: string, side: 'top' | 'bot', e: FlowEdge) => {
      const k2 = pkey(id, side), list = ports.get(k2)!
      // order the ends along the card by where the other end lies; when that is the same column,
      // branches back to the row above go left, the main line sits in the middle, and lines that
      // leave by the right-hand gutter go right, so the lines in the gap do not cross
      const weight = (x: FlowEdge) => { const kd = kind(x); return kd === 'up' || kd === 'under' ? 1 : kd === 'back1' ? -1 : kd === 'far' ? -2 : 0 }
      const near = (o: string) => pkey(o, 'top') === k2 || pkey(o, 'bot') === k2
      const other = (x: FlowEdge) => { const o = near(x.s) && !near(x.t) ? x.t : near(x.t) && !near(x.s) ? x.s : x.t; return pos[o].x + weight(x) * 0.25 * cw }
      const sorted = [...list].sort((p1, p2) => other(p1) - other(p2))
      const n = sorted.length, step = Math.min(40, cw / (n + 1))
      return pos[id].x + cw / 2 + (sorted.indexOf(e) - (n - 1) / 2) * step
    }

    const svg = svgEl('svg', { width: W, height: stageH, 'aria-hidden': 'true' })
    stage.prepend(svg)
    const gridL = x0, gridR = x0 + gridW
    type How = 'center' | 'above' | 'right'
    for (const e of flow.edges) {
      const a = pos[e.s], b = pos[e.t], kd = kind(e)
      let pts: [number, number][]
      let lab: [number, number, How]
      if (kd === 'h') {
        const yy = a.y + Math.min(26, a.h / 2)
        pts = [[a.x + a.w, yy], [b.x - 2, yy]]
        lab = [(a.x + a.w + b.x) / 2, yy, 'above']
      } else if (kd === 'over') {
        const sx = portX(e.s, 'top', e), tx = portX(e.t, 'top', e), ly = LY(rowOf[e.s], e)
        pts = [[sx, a.y], [sx, ly], [tx, ly], [tx, b.y - 2]]
        lab = [(sx + tx) / 2, ly, 'center']
      } else if (kd === 'down') {
        const sx = portX(e.s, 'bot', e), tx = portX(e.t, 'top', e), ly = LY(rowOf[e.s] + 1, e)
        pts = Math.abs(sx - tx) < 1 ? [[sx, a.y + a.h], [tx, b.y - 2]] : [[sx, a.y + a.h], [sx, ly], [tx, ly], [tx, b.y - 2]]
        lab = Math.abs(sx - tx) > 140 ? [(sx + tx) / 2, ly, 'center'] : [Math.max(sx, tx), ly, 'right']
      } else if (kd === 'far') {
        const sx = portX(e.s, 'bot', e), tx = portX(e.t, 'top', e), l1 = LY(rowOf[e.s] + 1, e), l2 = LY(second.get(e)!, e)
        const gx = gridL - 14 - slot.get(e)! * 8
        pts = [[sx, a.y + a.h], [sx, l1], [gx, l1], [gx, l2], [tx, l2], [tx, b.y - 2]]
        lab = [(gx + tx) / 2, l2, 'center']
      } else if (kd === 'back1') {
        // back to the row just above: straight up through the gap between the two rows
        const sx = portX(e.s, 'top', e), tx = portX(e.t, 'bot', e), ly = LY(rowOf[e.s], e)
        pts = [[sx, a.y], [sx, ly], [tx, ly], [tx, b.y + b.h + 2]]
        lab = Math.abs(sx - tx) > 140 ? [(sx + tx) / 2, ly, 'center'] : [Math.max(sx, tx), ly, 'right']
      } else if (kd === 'under') {
        const sx = portX(e.s, 'bot', e), tx = portX(e.t, 'bot', e), ly = LY(rowOf[e.s] + 1, e)
        pts = [[sx, a.y + a.h], [sx, ly], [tx, ly], [tx, b.y + b.h + 2]]
        lab = [(sx + tx) / 2, ly, 'center']
      } else {
        const sx = portX(e.s, 'bot', e), tx = portX(e.t, 'bot', e), l1 = LY(rowOf[e.s] + 1, e), l2 = LY(second.get(e)!, e)
        const gx = gridR + 14 + slot.get(e)! * 8
        pts = [[sx, a.y + a.h], [sx, l1], [gx, l1], [gx, l2], [tx, l2], [tx, b.y + b.h + 2]]
        lab = Math.abs(gx - tx) > 140 ? [(gx + tx) / 2, l2, 'center'] : [tx, l2, 'right']
      }
      // the line stops at the arrowhead's base, so it never pokes past the tip
      const [ex, ey] = pts[pts.length - 1], [px, py] = pts[pts.length - 2]
      const ang = Math.atan2(ey - py, ex - px), cut = Math.min(6, Math.hypot(ex - px, ey - py) / 2)
      const d = rounded([...pts.slice(0, -1), [ex - Math.cos(ang) * cut, ey - Math.sin(ang) * cut]])
      const p = svgEl('path', { class: `fc-edge${e.back ? ' fc-back' : ''}`, d }, svg)
      const ah = svgEl('path', { class: 'fc-ah', d: 'M0 0 L-8 -4.5 L-8 4.5 Z', transform: `translate(${ex},${ey}) rotate(${ang * 180 / Math.PI})` }, svg)
      let lb: HTMLElement | null = null
      // a condition shows only while the beam runs its edge or its step is picked; the ones between
      // neighbours in a row are told by the caption instead
      if (e.label && kd !== 'h') {
        lb = el('div', 'fc-elabel', e.label)
        lb.style.left = `${lab[0]}px`; lb.style.top = `${lab[1]}px`
        lb.style.transform = lab[2] === 'center' ? 'translate(-50%,-50%)' : lab[2] === 'above' ? 'translate(-50%,calc(-100% - 6px))' : 'translate(8px,-50%)'
        stage.append(lb)
      }
      this.edges.push({ e, p, ah, lb })
    }
    this.buildBeam(svg)
    this.head = 0; this.rest = 0; this.litId = null
    if (this.sel) this.select(this.sel)
  }

  private buildBeam(svg: SVGSVGElement) {
    const route = flowRoute(this.flow)
    const probe = svgEl('path', {}, svg)
    const ds: string[] = [], marks: { e: FlowEdge; from: number; to: number }[] = []
    route.forEach((e) => {
      const v = this.edges.find((x) => x.e === e)
      if (!v) return
      const d = v.p.getAttribute('d') || ''
      // each edge stays its own subpath: joining them with a line would cut straight across the
      // card between two edges; the dash runs on across subpaths, so the beam hops the card
      ds.push(d)
      probe.setAttribute('d', ds.join(' '))
      const end = probe.getTotalLength()
      marks.push({ e, from: end - v.p.getTotalLength(), to: end })
    })
    const total = ds.length ? probe.getTotalLength() : 0
    probe.remove()
    const g = svgEl('g', { class: 'fc-beam' }, svg)
    const layers = [{ len: 120, w: 2, op: 0.16 }, { len: 70, w: 2, op: 0.38 }, { len: 28, w: 2.5, op: 1 }]
    const paths = layers.map((l) => svgEl('path', { d: ds.join(' '), 'stroke-width': l.w, 'stroke-opacity': l.op, 'stroke-dasharray': `${l.len} ${total + 400}`, 'stroke-dashoffset': l.len + 200 }, g))
    this.beam = { total, g, paths, lens: layers.map((l) => l.len), marks }
  }

  private setHead(h: number) {
    const b = this.beam
    if (!b) return
    b.paths.forEach((p, i) => p.setAttribute('stroke-dashoffset', String(b.lens[i] - h)))
    // fade in at the start and out at the end instead of popping on and off
    const fade = Math.max(0, Math.min(1, (h + 10) / 50, (b.total + 120 - h) / 90))
    b.g.style.opacity = String(fade)
    let lit: string | null = null
    b.marks.forEach((m, i) => {
      const v = this.edges.find((x) => x.e === m.e)!
      v.p.classList.toggle('fc-lit', h >= m.from - 10 && h <= m.to + 50)
      v.lb?.classList.toggle('fc-show', h >= m.from - 30 && h <= m.to + 160)
      v.ah.classList.toggle('fc-lit', h >= m.to - 6 && h <= m.to + 70)
      const next = b.marks[i + 1]
      if (h >= m.to - 4 && (next ? h <= next.from + 20 : h <= m.to + 240)) lit = m.e.t
      if (i === 0 && h >= -40 && h < m.from + 24) lit = m.e.s
    })
    if (lit !== this.litId) {
      for (const [id, c] of Object.entries(this.cards)) c.classList.toggle('fc-live', id === lit)
      if (lit) { const c = this.cards[lit]; c.classList.remove('fc-arrive'); void c.offsetWidth; c.classList.add('fc-arrive') }
      this.litId = lit
      if (!this.sel && lit) this.caption(lit)
    }
  }

  /** Speed along the route: full speed on open line, easing down as the beam nears a card and
   *  picking up again as it leaves, by distance rather than by edge, so every edge feels alike. */
  private speedAt(h: number): number {
    const b = this.beam!
    let d = Infinity
    for (const m of b.marks) d = Math.min(d, Math.abs(h - m.from), Math.abs(h - m.to))
    const t = Math.min(1, d / 80), smooth = t * t * (3 - 2 * t)
    return 70 + 150 * smooth // px per second, 70 at a card and 220 in between
  }

  private frame = (now: number) => {
    this.raf = requestAnimationFrame(this.frame)
    const dt = this.last ? Math.min(now - this.last, 50) : 0
    this.last = now
    if (this.paused || !this.visible || !this.beam) return
    if (this.rest > 0) { this.rest -= dt; if (this.rest <= 0) this.head = -40; return }
    this.head += this.speedAt(this.head) * dt / 1000
    if (this.head > this.beam.total + 130) { this.rest = 1200; this.setHead(-400); return }
    this.setHead(this.head)
  }

  private select(id: string | null) {
    const { stage } = this
    stage.classList.remove('fc-dim')
    Object.values(this.cards).forEach((c) => c.classList.remove('fc-sel', 'fc-on'))
    this.edges.forEach((v) => { v.p.classList.remove('fc-on'); v.ah.classList.remove('fc-on'); v.lb?.classList.remove('fc-on') })
    this.sel = id
    if (!id) { this.paused = false; this.head = -40; this.rest = 0; this.capId = undefined; this.caption(this.litId ?? this.flow.order[0]); return }
    this.paused = true
    this.setHead(-400)
    stage.classList.add('fc-dim')
    this.cards[id].classList.add('fc-sel', 'fc-on')
    this.capId = undefined
    this.caption(id)
    for (const v of this.edges) {
      if (v.e.s !== id && v.e.t !== id) continue
      v.p.classList.add('fc-on'); v.ah.classList.add('fc-on'); v.lb?.classList.add('fc-on')
      this.cards[v.e.s].classList.add('fc-on'); this.cards[v.e.t].classList.add('fc-on')
    }
  }
}

const views = new WeakMap<HTMLElement, FlowView>()

function fallback(block: HTMLElement, code: string) {
  const names = code.split('\n').map((l) => l.trim().split(SEP)).filter((f) => f.length >= 3 && /^[A-Za-z]\w{0,2}$/.test(f[0])).map((f) => f[2])
  const ol = el('ol', 'mermaid-fallback')
  names.forEach((n) => ol.append(el('li', '', n)))
  block.replaceChildren(ol)
}

/** Draw every not-yet-drawn flow block inside a rendered markdown container. */
export function renderFlowsIn(container: HTMLElement | null): void {
  if (!container) return
  for (const block of Array.from(container.querySelectorAll<HTMLElement>('.flow-block:not([data-done])'))) {
    block.dataset.done = '1'
    const code = block.querySelector('.flow-src')?.textContent || ''
    const flow = parseFlow(code)
    if (!flow) { fallback(block, code); continue }
    try { views.set(block, new FlowView(block, flow)) } catch { fallback(block, code) }
  }
}

/** Stop the animation of every flow drawn inside a container that is about to be replaced. */
export function disposeFlowsIn(container: HTMLElement | null): void {
  container?.querySelectorAll<HTMLElement>('.flow-block').forEach((b) => views.get(b)?.destroy())
}

