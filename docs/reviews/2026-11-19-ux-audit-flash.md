# OmniKeep 前端巡檢清單（2026-11-19，Gemini 3.8 Flash，未審）

來源：[OmniKeep 主線] T3 對話 `mcp:launch:03ab43aa…` 第 12、13 回合（2026-11-19 17:53、18:06）。
使用者的指示：「不要修，先記起來……不用怕誤報，我會把你的所有回饋再整理給更強的模型審查才決定要不要採用」。
本檔是原文整理，**尚未審查**；行號是 11-19 當時的，可能已位移。審查結果另寫在 `2026-11-22-ux-audit-review.md`。

## 第一部分：Bug／體驗死角（8 項）

1. **新增對話框手動指定分類對網址失效**：`frontend/src/components/modals/AddDialog.vue:131-150`、`:267`。`saveNote` 有傳 `category`，`saveLinks` 呼叫 `api.ingest(url, { async: queued })` 漏傳；分類選單被 `v-if="plan.kind === 'note'"` 限制，貼網址時看不到。
2. **原文分頁無快照時是死胡同**：`frontend/src/components/reader/ReaderTab.vue:34-37`。只顯示「未抓取到原文快照或純淨內文」，沒有「開啟原網頁」「開啟離線快照」按鈕。
3. **隨手筆記來源露出英文 `snippet`、選單有無效連結**：`frontend/src/lib/format.ts:4-18`、`frontend/src/components/items/ItemActions.vue:57`。URL 是 `local://snippet/{id}`，`cleanHost()` 只判斷 `note://`；「開啟原始連結」會開 `local://`。建議 `v-if="item.url && /^https?:\/\//.test(item.url)"`。
4. **清單視圖未分類項目沒有「收件匣」標籤**：`frontend/src/components/items/ItemRow.vue:44-47`，`<template v-if="item.category_name">`，應改用 `displayCategory()`。
5. **「新增分類字典」舊術語**：`frontend/src/components/modals/CategoryDialog.vue:39`，改「新增分類」。
6. **J/K 換篇時原文分頁變空白**：`frontend/src/composables/useKeyboard.ts:178-183`、`frontend/src/components/reader/ReaderPane.vue:76-79`。新項目沒原文時應切回重點分析分頁或提示。
7. **窄螢幕詳情頁標頭標題與來源互擠**：`frontend/src/components/reader/ReaderPane.vue:100-103`，<840px 時 `span.min-w-0.truncate` 只剩 2～3 字；建議來源移到次級列。
8. **未分析完成時「複製重點」複製出空字串**：`frontend/src/components/items/ItemActions.vue:18-25`，`copyTakeaway()` 直接拼 `summary_l1`；建議改複製標題＋網址並在 toast 註明。

## 第二部分：設定頁整併建議

目前分頁：一般、收錄管道、AI、通知、資料與備份、進階、實驗功能。

- A. **「分析深度」「關於你」從「一般」移到「AI」**：兩者是送給模型的參數與個人化提示；「一般」只留外觀、閱讀面板、預設檢視。
- B. **收掉 AI 頁的舊「提問」表單**：`frontend/src/components/settings/AiSection.vue:15-25` 的 `BRAIN_PROVIDER`／`BRAIN_BASE_URL`／`BRAIN_MODEL` 與 `AiConnections.vue` 的提問槽位重複；只留 `BRAIN_MAX_CITATIONS`、`BRAIN_NUM_CTX` 當進階參數。（需確認後端關聯）
- C. **匯入與匯出放一起**：「匯入書籤」在收錄管道、「匯出收藏」在資料與備份；改成「資料、匯入與備份」，收錄管道只放即時收錄。
- D. **通知頁收攏**：Telegram 通知要跳到收錄管道、只有 VAPID 信箱；改成「發送管道 × 通知事件」（每日摘要時間、探索推播、高星提醒）。

## 第三部分：參考競品的方向（較大，屬改版）

- Readwise Reader：收錄管道改成整合卡片網格（圖示、狀態、管理按鈕）。
- Linear：按鈕與選單旁標 `<kbd>` 快捷鍵、快捷鍵輔助列。
- Notion／Superhuman：側邊欄分類就地改名、換圖示、刪除、拖曳排序；展開不跳動。

## Flash 自評的決策矩陣（未審）

| # | 項目 | 性質 | 它估的風險 |
|---|---|---|---|
| 1 | AddDialog 補傳分類、開放選單 | Bug | 極低 |
| 2 | ReaderTab 空狀態補按鈕 | UX | 極低 |
| 3 | format.ts 筆記來源、隱藏無效連結 | UI | 極低 |
| 4 | ItemRow 收件匣標籤 | UI | 極低 |
| 5 | CategoryDialog 正名 | 文案 | 極低 |
| 6 | J/K 無原文切回分析 | UX | 低 |
| 7 | 設定整併 A | IA | 低 |
| 8 | 設定整併 B（廢舊提問表單） | 重構 | 中 |
| 9 | 設定整併 C（匯入匯出） | IA | 低 |
