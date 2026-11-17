import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import ts from 'typescript'

// The layout half of lib/archchart.ts is pure, so it is checked here on real-shaped blocks at
// several widths: no line may run through a card or a band's name, and labels stay off the cards.
const source = await readFile(new URL('../src/lib/archchart.ts', import.meta.url), 'utf8')
const js = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } }).outputText
const { parseArch, layoutArch } = await import('data:text/javascript,' + encodeURIComponent(js))

// shaped like the migro diagram that showed the bug: the third band starts under the first column
// and its name is as long as the card is wide
const SNAKE = `總結：把對話記憶轉給另一個模型
入口｜user｜user｜使用者｜輸入對話歷史與查詢｜rec｜歷史對話
區｜紀錄｜格式化對話並產生表徵｜
元件｜rec｜list｜紀錄處理｜結構化對話紀錄｜時間戳記｜一般｜｜｜
元件｜ref｜code｜參考寫入器｜來源模型因果寫入｜凍結權重｜一般｜｜｜
區｜持久存儲｜緊湊壓縮狀態以節約空間｜記憶表徵
元件｜store｜db｜狀態儲存庫｜保存錨點與內容綁定｜約 1.86 MB｜重點｜｜｜
元件｜codec｜cpu｜編碼核心｜序列化與精確解碼｜8 位元量化｜一般｜｜｜
區｜轉移適配｜對齊目標模型詞彙並檢索｜壓縮狀態
元件｜trans｜swap｜詞彙轉換器｜跨模型詞彙對齊｜詞表映射｜一般｜｜｜
元件｜reader｜search｜證據檢索器｜挑選相關記憶回傳｜Top-K 檢索｜一般｜｜｜
旁｜cal｜gear｜介面校準｜微調讀取連接介面｜trans｜殘差特徵｜校準權重｜｜｜`

// an input that comes up from the gap into the last card of the first band, and lines that skipped
// the 小標籤 column (the model wrote the kind where the tag goes)
const VIA_GAP = `入口｜web｜globe｜網頁介面｜管理實驗群組｜svc｜點擊操作
入口｜cli｜terminal｜命令列｜執行評測與統整｜run｜指令
區｜實驗調度｜排程評測並調度執行緒｜
元件｜svc｜server｜實驗服務｜協調背景工作緒｜一般｜｜｜
元件｜run｜cpu｜評測執行器｜推進對話與驗證動作｜重點｜｜｜
區｜環境評定｜模擬任務物理狀態與驗證結果｜步驟資料
元件｜env｜box｜任務環境｜模擬太空實體狀態｜一般｜｜｜
元件｜score｜stamp｜評分模組｜計算任務成果指標｜一般｜｜｜`

const textW = (s, px) => [...s].reduce((w, c) => w + (c.charCodeAt(0) > 0x2e80 ? px : px * 0.56), 0)
const hit = (a, b) => a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h
const seg = ([x1, y1], [x2, y2]) => ({ x: Math.min(x1, x2) - 0.5, y: Math.min(y1, y2) - 0.5, w: Math.abs(x2 - x1) + 1, h: Math.abs(y2 - y1) + 1 })
const inset = (r, d) => ({ x: r.x + d, y: r.y + d, w: r.w - 2 * d, h: r.h - 2 * d })

function problems(code, width) {
  const L = layoutArch(parseArch(code), width), out = []
  const names = L.bands.filter((b) => b.title || b.note).map((b) => {
    const left = b.lbLeft || 14, full = (b.title ? textW(b.title, 12.5) + 8 : 0) + textW(b.note, 12.5)
    return { x: b.x + left, y: b.y + 11, w: Math.min(full, b.w - left - 14), h: 18, t: b.title }
  })
  for (const e of L.edges) {
    for (let k = 1; k < e.pts.length; k++) {
      const s = seg(e.pts[k - 1], e.pts[k])
      for (const [id, p] of Object.entries(L.places)) if (hit(s, inset(p, 3))) out.push(`${e.s}->${e.t} through card ${id}`)
      for (const n of names) if (hit(s, n)) out.push(`${e.s}->${e.t} through band name ${n.t}`)
    }
    if (e.label && e.at) {
      const w = textW(e.label, 11.5) + (e.side ? 4 : 12), [x, y] = e.at
      const box = { x: e.side === 'l' ? x - w : e.side === 'r' ? x : x - w / 2, y: y - 8, w, h: 16 }
      for (const [id, p] of Object.entries(L.places)) if (hit(box, inset(p, 1))) out.push(`label ${e.label} on card ${id}`)
    }
  }
  return out
}

for (const [name, code] of [['snake', SNAKE], ['via gap', VIA_GAP]]) {
  for (const width of [1080, 860, 640, 350]) {
    test(`${name} at ${width}px: no line through a card or a band name`, () => {
      assert.deepEqual(problems(code, width), [])
    })
  }
}

test('a line that skipped the 小標籤 column keeps its kind and shows no tag', () => {
  const a = parseArch(VIA_GAP)
  assert.equal(a.nodes.run.kind, 'key')
  assert.equal(a.nodes.run.tag, '')
  assert.equal(a.nodes.svc.tag, '')
})

test('cards are only as tall as what they hold', () => {
  const L = layoutArch(parseArch(VIA_GAP), 1080)
  // no tag and a one-line description: well under the old fixed 92px
  assert.ok(L.places.svc.h < 80, `card is ${L.places.svc.h}px tall`)
})

// two bands under each other in the same column, a second input coming up from the gap into the last
// card of the first band, and a long next-band name that pushes the line down to the card's left edge
const CROSS = `入口｜web｜globe｜網頁｜送出請求｜a1｜請求
入口｜cli｜terminal｜命令列｜批次送出｜a2｜指令
區｜接收｜檢查請求｜
元件｜a1｜server｜接收器｜驗證格式｜｜一般｜｜｜
元件｜a2｜cpu｜排程器｜分派工作｜｜一般｜｜｜
區｜處理與回寫階段｜把請求轉成結果並寫回儲存再通知所有使用者｜工作
元件｜b1｜box｜執行器｜跑工作｜｜一般｜｜｜
元件｜b2｜db｜儲存｜寫回結果｜｜一般｜｜｜`

// the input from the gap goes into a card that has a helper hanging under it
const HELPER = `入口｜web｜globe｜網頁｜送出請求｜n1｜請求
入口｜cli｜terminal｜命令列｜批次送出｜n2｜指令
區｜流程｜三步｜
元件｜n1｜server｜第一步｜收下｜｜一般｜｜｜
元件｜n2｜cpu｜第二步｜處理｜｜一般｜｜｜
元件｜n3｜db｜第三步｜存下｜｜一般｜｜｜
旁｜s1｜gear｜輔助｜幫第二步｜n2｜送出｜收回｜｜｜
區｜收尾｜通知｜結果
元件｜m1｜bell｜通知｜告訴使用者｜｜一般｜｜｜`

const crossings = (code, width) => {
  const L = layoutArch(parseArch(code), width), segs = []
  for (const e of L.edges) for (let k = 1; k < e.pts.length; k++) segs.push({ e: `${e.s}->${e.t}`, a: e.pts[k - 1], b: e.pts[k] })
  const out = []
  for (const p of segs) for (const q of segs) {
    if (p.e >= q.e) continue
    const pv = p.a[0] === p.b[0], qv = q.a[0] === q.b[0]
    if (pv === qv) continue
    const [v, h] = pv ? [p, q] : [q, p], x = v.a[0], y = h.a[1]
    const inside = (u, lo, hi) => u > Math.min(lo, hi) + 1 && u < Math.max(lo, hi) - 1
    if (inside(x, h.a[0], h.b[0]) && inside(y, v.a[1], v.b[1])) out.push(`${p.e} x ${q.e}`)
  }
  return out
}

for (const width of [1080, 860, 640, 580, 520]) {
  test(`at ${width}px the input from the gap crosses no other line`, () => {
    assert.deepEqual(crossings(CROSS, width), [])
    assert.deepEqual(problems(CROSS, width), [])
  })
  test(`at ${width}px the input from the gap goes round a helper card`, () => {
    assert.deepEqual(problems(HELPER, width), [])
  })
}

test('a full line whose tag happens to read like a kind keeps both', () => {
  const a = parseArch(`入口｜usr｜user｜人｜用｜kk｜送
區｜甲｜｜
元件｜kk｜box｜卡｜說明｜重點｜一般｜｜｜src/a.py
元件｜jj｜box｜卡二｜說明｜｜一般｜｜｜`)
  assert.equal(a.nodes.kk.tag, '重點')
  assert.equal(a.nodes.kk.kind, 'plain')
  assert.deepEqual(a.nodes.kk.files, ['src/a.py'])
})

// a band longer than the reading column holds (like the swin-transformer diagram that fell back to
// the stacked layout): it wraps onto a second row inside the band and the diagram stays side by side
const LONG = `入口｜data｜folder｜ImageNet｜影像分類資料集｜pipe｜資料
入口｜who｜user｜研究者｜指定設定檔與資料路徑｜cfg｜命令列
區｜準備｜讀取設定與資料｜
元件｜cfg｜gear｜設定解析｜讀 YAML 與命令列覆寫｜Swin-V2 設定｜一般｜｜｜
元件｜pipe｜db｜資料管線｜載入 ImageNet 並快取｜快取 3 模式｜重點｜｜｜
區｜模型｜建構 Swin 骨幹與分類頭｜設定
元件｜build｜box｜模型建構｜依設定挑 Swin 版本｜V1/V2｜一般｜｜｜
元件｜back｜layers｜Swin 骨幹｜分層特徵與位移視窗｜4 階段｜一般｜｜｜
元件｜head｜cpu｜分類頭｜池化後輸出類別｜1000 類｜一般｜｜｜
元件｜loss｜chart｜損失函數｜標籤平滑交叉熵｜Mixup｜一般｜｜｜
元件｜opt｜swap｜最佳化器｜AdamW 與學習率排程｜餘弦退火｜一般｜｜｜
旁｜amp｜cpu｜混合精度｜縮放梯度避免溢位｜back｜前向｜梯度｜｜｜
區｜訓練｜分散式迴圈與存檔｜批次
元件｜loop｜replay｜訓練迴圈｜多卡同步梯度｜DDP｜一般｜｜｜
元件｜ckpt｜download｜存檔｜保存最佳權重｜｜一般｜｜｜`

for (const width of [1080, 860, 640, 580]) {
  test(`at ${width}px a long band wraps instead of stacking, with no line through a card or another line`, () => {
    const L = layoutArch(parseArch(LONG), width)
    assert.equal(L.narrow, false)
    assert.deepEqual(problems(LONG, width), [])
    assert.deepEqual(crossings(LONG, width), [])
  })
}

test('at 640px the five-card band wraps onto more rows inside one band, a row ending early before the helper', () => {
  const L = layoutArch(parseArch(LONG), 640)
  const ys = ['build', 'back', 'head', 'loss', 'opt'].map((id) => L.places[id].y)
  assert.ok(new Set(ys).size >= 2, `rows at ${ys}`)
  // no line goes down out of the card the helper hangs under
  assert.ok(!L.edges.some((e) => e.s === 'back' && e.down), 'down line leaves the card the helper hangs under')
  const band = L.bands[1]
  for (const id of ['build', 'opt']) assert.ok(L.places[id].y + L.places[id].h <= band.y + band.h, `${id} inside its band`)
  // every step of the flow is still walked by the beam
  assert.equal(L.route.filter((r) => r.to === 'opt').length, 1)
})

test('the stacked layout is left only for a column too narrow for two cards a row', () => {
  assert.equal(layoutArch(parseArch(LONG), 350).narrow, true)
  assert.deepEqual(problems(LONG, 520), [])
})
