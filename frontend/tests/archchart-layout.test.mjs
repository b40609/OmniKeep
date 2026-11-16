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
