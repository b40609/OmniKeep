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
  private stage: HTMLElement
  private cards: Record<string, HTMLElement> = {}
  private edges: EdgeView[] = []
  private sel: string | null = null
  private beam: { total: number; paths: SVGPathElement[]; lens: number[]; marks: { e: FlowEdge; from: number; to: number }[] } | null = null
  private head = 0
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
    root.replaceChildren()
    if (flow.gist) root.append(el('p', 'fc-gist', flow.gist))
    this.stage = el('div', 'fc-stage')
    root.append(this.stage)
    root.append(el('p', 'fc-hint', '點步驟看完整說明，點空白處繼續播放。'))
    this.stage.addEventListener('click', () => { if (this.sel) this.select(null) })
    const ro = new ResizeObserver(() => { const w = this.stage.clientWidth; if (w && w !== this.width) { this.width = w; this.layout() } })
    ro.observe(this.stage)
    const io = new IntersectionObserver(([en]) => { this.visible = en.isIntersecting }, { threshold: 0.3 })
    io.observe(this.stage)
    this.observers.push(ro, io)
    this.raf = requestAnimationFrame(this.frame)
  }

  destroy() { cancelAnimationFrame(this.raf); this.observers.forEach((o) => o.disconnect()) }

  private cardFor(id: string, n: number): HTMLElement {
    const s = this.flow.steps[id]
    const c = el('div', 'fc-card')
    c.setAttribute('role', 'button')
    c.tabIndex = 0
    const head = el('div', 'fc-head')
    const ico = el('span', `fc-ico fc-k-${s.kind}`)
    ico.append(icon(ICONS[s.kind]))
    head.append(ico, el('span', 'fc-title', s.label), el('span', 'fc-no', `${this.flow.order.indexOf(id) + 1}/${n}`))
    c.append(head)
    if (s.desc) c.append(el('div', 'fc-desc', s.desc))
    if (s.more) c.append(el('div', 'fc-more', s.more))
    if (s.tags.length) { const f = el('div', 'fc-tags'); s.tags.forEach((t) => f.append(el('span', 'fc-tag', t))); c.append(f) }
    if (s.gate) { const g = el('div', 'fc-gate'); g.append(icon(GATE_ICON), document.createTextNode(s.gate)); c.append(g) }
    const toggle = (ev: Event) => { ev.stopPropagation(); this.select(this.sel === id ? null : id) }
    c.addEventListener('click', toggle)
    c.addEventListener('keydown', (ev) => { if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); toggle(ev) } })
    return c
  }

  private layout() {
    const { flow, stage } = this
    stage.replaceChildren()
    this.cards = {}
    this.edges = []
    const W = stage.clientWidth, P = W < 480 ? 16 : 24, order = flow.order, N = order.length, G = flow.groups.length
    const main = flow.edges.filter((e) => !e.back), backs = flow.edges.filter((e) => e.back)
    const groupOf: Record<string, number> = {}
    flow.groups.forEach((g, gi) => g.ids.forEach((id) => { groupOf[id] = gi }))
    const ix = (id: string) => order.indexOf(id)
    const isSkip = (e: FlowEdge) => !e.back && ix(e.t) > ix(e.s) + 1 && (G === 1 || groupOf[e.s] === groupOf[e.t])
    const skips = main.filter(isSkip)
    const narrow = W < 480
    const gutter = backs.length ? (narrow ? 30 : 48) + backs.length * 8 : 0, lgutter = skips.length ? (narrow ? 26 : 40) + skips.length * 6 : 0
    let mode: 'stack' | 'row' | 'cols' = 'stack', cw = 0
    const colW = (W - P * 2 - (G - 1) * 40) / G
    const gaps = order.slice(0, -1).map((id, k) => { const e = main.find((x) => x.s === id && x.t === order[k + 1]); return e?.label ? Math.max(56, e.label.length * 12 + 28) : 56 })
    const gapSum = gaps.reduce((a, b) => a + b, 0)
    if (G > 1 && colW >= 160) { mode = 'cols'; cw = Math.min(260, colW) }
    else if (G === 1 && N <= 6 && (W - P * 2 - gapSum) / N >= 170) { mode = 'row'; cw = Math.min(220, (W - P * 2 - gapSum) / N) }
    else cw = Math.min(W - P * 2 - gutter - lgutter, 400)

    for (const id of order) { const c = this.cardFor(id, N); c.style.width = `${cw}px`; stage.append(c); this.cards[id] = c }
    const pos: Record<string, Box> = {}
    const H = (id: string) => this.cards[id].offsetHeight
    const labels: { text: string; n: number; x: number; y: number; band?: boolean }[] = []
    let stageH = 0
    if (mode === 'stack') {
      const x = (W - cw - gutter - lgutter) / 2 + lgutter
      let y = P
      flow.groups.forEach((g, gi) => {
        if (g.label) { labels.push({ text: g.label, n: g.ids.length, x, y }); y += 28 }
        g.ids.forEach((id, k) => { pos[id] = { x, y, w: cw, h: H(id) }; y += H(id) + (k < g.ids.length - 1 ? 52 : 0) })
        if (gi < G - 1) y += 56
      })
      stageH = y + P
    } else if (mode === 'row') {
      let x = (W - N * cw - gapSum) / 2
      const top = P + (skips.length ? 40 : 0)
      order.forEach((id, k) => { pos[id] = { x, y: top, w: cw, h: H(id) }; x += cw + (gaps[k] || 0) })
      stageH = top + Math.max(...order.map(H)) + (backs.length ? 44 : 0) + P
    } else {
      let x = (W - G * cw - (G - 1) * 40) / 2, maxY = 0
      flow.groups.forEach((g) => {
        let y = P
        labels.push({ text: g.label, n: g.ids.length, x, y, band: true }); if (g.label) y += 28
        g.ids.forEach((id) => { pos[id] = { x, y, w: cw, h: H(id) }; y += H(id) + 44 })
        maxY = Math.max(maxY, y - 44)
        x += cw + 40
      })
      stageH = maxY + P
    }
    stage.style.height = `${stageH}px`
    order.forEach((id, i) => { const p = pos[id], c = this.cards[id]; c.style.left = `${p.x}px`; c.style.top = `${p.y}px`; c.style.setProperty('--d', `${i * 70}ms`) })
    for (const l of labels) {
      if (l.band) { const b = el('div', 'fc-band'); b.style.cssText = `left:${l.x - 10}px;top:${l.y - 8}px;width:${cw + 20}px;height:${stageH - l.y - P + 16}px`; stage.prepend(b) }
      if (!l.text) continue
      const g = el('div', 'fc-group', l.text)
      g.append(el('i', '', `${l.n} 步`))
      g.style.left = `${l.x}px`; g.style.top = `${l.y}px`
      stage.append(g)
    }

    const svg = svgEl('svg', { width: W, height: stageH, 'aria-hidden': 'true' })
    stage.prepend(svg)
    const add = (e: FlowEdge, pts: [number, number][], at: [number, number], alignRight = false) => {
      const d = rounded(pts)
      const p = svgEl('path', { class: `fc-edge${e.back ? ' fc-back' : ''}`, d }, svg)
      const [ex, ey] = pts[pts.length - 1], [px, py] = pts[pts.length - 2]
      const ah = svgEl('path', { class: 'fc-ah', d: 'M0 0 L-7 -4 L-7 4 Z', transform: `translate(${ex},${ey}) rotate(${Math.atan2(ey - py, ex - px) * 180 / Math.PI})` }, svg)
      let lb: HTMLElement | null = null
      if (e.label) {
        lb = el('div', 'fc-elabel', e.label)
        lb.style.left = `${at[0]}px`; lb.style.top = `${at[1]}px`
        if (alignRight) lb.style.transform = 'translate(-100%,-50%)'
        stage.append(lb)
      }
      this.edges.push({ e, p, ah, lb })
    }
    for (const e of main) {
      const a = pos[e.s], b = pos[e.t]
      if (isSkip(e)) {
        // a forward jump past other steps goes round them: above the row, or down the left side
        if (mode === 'row') { const yt = a.y - 22; add(e, [[a.x + a.w / 2, a.y], [a.x + a.w / 2, yt], [b.x + b.w / 2, yt], [b.x + b.w / 2, b.y - 2]], [(a.x + a.w / 2 + b.x + b.w / 2) / 2 - 40, yt]) }
        else {
          // label in the gap just above the target, so it never shares a gap with the edge out of `a`
          const lx = Math.min(a.x, b.x) - (narrow ? 14 : 22) - skips.indexOf(e) * 6, prev = pos[order[ix(e.t) - 1]]
          add(e, [[a.x, a.y + a.h - 18], [lx, a.y + a.h - 18], [lx, b.y + 18], [b.x - 2, b.y + 18]], [lx + 8, (prev.y + prev.h + b.y) / 2])
        }
        continue
      }
      if (mode === 'row') add(e, [[a.x + a.w, a.y + 26], [b.x - 2, b.y + 26]], [a.x + a.w + 8, a.y + 10])
      else if (mode === 'stack' || groupOf[e.s] === groupOf[e.t]) {
        if (b.y > a.y) add(e, [[a.x + a.w / 2, a.y + a.h], [b.x + b.w / 2, b.y - 2]], [a.x + a.w / 2 + 10, (a.y + a.h + b.y) / 2])
        else { const gx = Math.max(a.x + a.w, b.x + b.w) + 28; add(e, [[a.x + a.w, a.y + 26], [gx, a.y + 26], [gx, b.y + 26], [b.x + b.w + 2, b.y + 26]], [gx + 10, b.y + b.h + 12], true) }
      } else {
        const mx = a.x + a.w + 20, ya = a.y + a.h / 2, yb = b.y + 26
        add(e, [[a.x + a.w, ya], [mx, ya], [mx, yb], [b.x - 2, yb]], [mx, (ya + yb) / 2])
        const lb = this.edges[this.edges.length - 1].lb
        if (lb) lb.style.transform = 'translate(-50%,-50%)'
      }
    }
    backs.forEach((e, k) => {
      const a = pos[e.s], b = pos[e.t]
      if (mode === 'row') {
        const yb = Math.max(a.y + a.h, b.y + b.h) + 30
        add(e, [[a.x + a.w / 2, a.y + a.h], [a.x + a.w / 2, yb], [b.x + b.w / 2, yb], [b.x + b.w / 2, b.y + b.h + 2]], [(a.x + a.w / 2 + b.x + b.w / 2) / 2 - 48, yb])
      } else {
        const gx = Math.max(a.x + a.w, b.x + b.w) + (narrow ? 16 : 24) + k * 8, top = a.y > b.y ? b : a, bot = a.y > b.y ? a : b
        add(e, [[a.x + a.w, a.y + 26 + k * 6], [gx, a.y + 26 + k * 6], [gx, b.y + 20 + k * 6], [b.x + b.w + 2, b.y + 20 + k * 6]], [gx + 10, (top.y + top.h + bot.y) / 2], true)
      }
    })
    this.buildBeam(svg)
    this.head = 0; this.rest = 0
    if (this.sel) this.select(this.sel)
  }

  private buildBeam(svg: SVGSVGElement) {
    const route = flowRoute(this.flow)
    const probe = svgEl('path', {}, svg)
    const ds: string[] = [], marks: { e: FlowEdge; from: number; to: number }[] = []
    route.forEach((e, i) => {
      const v = this.edges.find((x) => x.e === e)
      if (!v) return
      const d = v.p.getAttribute('d') || ''
      ds.push(i === 0 ? d : d.replace(/^M/, 'L'))
      probe.setAttribute('d', ds.join(' '))
      const end = probe.getTotalLength()
      marks.push({ e, from: end - v.p.getTotalLength(), to: end })
    })
    const total = ds.length ? probe.getTotalLength() : 0
    probe.remove()
    const g = svgEl('g', { class: 'fc-beam' }, svg)
    const layers = [{ len: 120, w: 2, op: 0.16 }, { len: 70, w: 2, op: 0.38 }, { len: 28, w: 2.5, op: 1 }]
    const paths = layers.map((l) => svgEl('path', { d: ds.join(' '), 'stroke-width': l.w, 'stroke-opacity': l.op, 'stroke-dasharray': `${l.len} ${total + 400}`, 'stroke-dashoffset': l.len + 200 }, g))
    this.beam = { total, paths, lens: layers.map((l) => l.len), marks }
  }

  private setHead(h: number) {
    const b = this.beam
    if (!b) return
    b.paths.forEach((p, i) => p.setAttribute('stroke-dashoffset', String(b.lens[i] - h)))
    let lit: string | null = null
    b.marks.forEach((m, i) => {
      const v = this.edges.find((x) => x.e === m.e)!
      v.p.classList.toggle('fc-lit', h >= m.from && h <= m.to + 40)
      v.ah.classList.toggle('fc-lit', h >= m.to - 6 && h <= m.to + 60)
      const next = b.marks[i + 1]
      if (h >= m.to - 8 && (next ? h <= next.from + 24 : h <= m.to + 260)) lit = m.e.t
      if (i === 0 && h >= 0 && h < m.from + 30) lit = m.e.s
    })
    for (const [id, c] of Object.entries(this.cards)) c.classList.toggle('fc-live', id === lit)
  }

  private frame = (now: number) => {
    this.raf = requestAnimationFrame(this.frame)
    const dt = this.last ? Math.min(now - this.last, 50) : 0
    this.last = now
    if (this.paused || !this.visible || !this.beam) return
    if (this.rest > 0) { this.rest -= dt; if (this.rest <= 0) this.head = 0; return }
    this.head += 170 * dt / 1000 // steady speed, px per second
    if (this.head > this.beam.total + 140) { this.rest = 1100; this.setHead(-400); return }
    this.setHead(this.head)
  }

  private select(id: string | null) {
    const { stage } = this
    stage.classList.remove('fc-dim')
    Object.values(this.cards).forEach((c) => c.classList.remove('fc-sel', 'fc-on'))
    this.edges.forEach((v) => { v.p.classList.remove('fc-on'); v.ah.classList.remove('fc-on'); v.lb?.classList.remove('fc-on') })
    this.sel = id
    if (!id) { this.paused = false; this.head = 0; this.rest = 0; return }
    this.paused = true
    this.setHead(-400)
    stage.classList.add('fc-dim')
    this.cards[id].classList.add('fc-sel', 'fc-on')
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

