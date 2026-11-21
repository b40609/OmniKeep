# OmniKeep 前端巡檢清單事實查證報告（2026-11-22）

- 查證對象：[docs/reviews/2026-11-19-ux-audit-flash.md](file:///C:/Users/user/Desktop/OmniKeep/docs/reviews/2026-11-19-ux-audit-flash.md)
- 查證基準：專案根目錄 `C:\Users\user\Desktop\OmniKeep`，`main` 分支（`HEAD = f9be735`，已包含後續前端提交 `6e95954` 與 `606161b`）；正式資料庫僅透過 `GET http://127.0.0.1:5000/api/items`（共 3,480 筆）與無頭瀏覽器唯讀檢視，未作任何新增、修改或刪除。
- 性質說明：本報告僅核對程式碼現況、判定原主張是否屬實、記錄觸發情境與變更影響面，不對優先順序或取捨下決策結論。

---

## 第一部分：Bug／體驗死角（1–8）

### 1. 新增對話框手動指定分類對網址失效

- **判定**：屬實
- **目前位置**：
  - [AddDialog.vue:115](file:///C:/Users/user/Desktop/OmniKeep/frontend/src/components/modals/AddDialog.vue#L115)（`saveNote` 傳入 `category`）
  - [AddDialog.vue:141](file:///C:/Users/user/Desktop/OmniKeep/frontend/src/components/modals/AddDialog.vue#L141)（`saveLinks` 未傳 `category`）
  - [AddDialog.vue:267-270](file:///C:/Users/user/Desktop/OmniKeep/frontend/src/components/modals/AddDialog.vue#L267-L270)（分類選單條件顯示）
  - 後端延伸關聯：[ingest.py:67-93](file:///C:/Users/user/Desktop/OmniKeep/app/routers/ingest.py#L67-L93)、[database.py:242-255](file:///C:/Users/user/Desktop/OmniKeep/app/database.py#L242-L255)、[database.py:2096-2099](file:///C:/Users/user/Desktop/OmniKeep/app/database.py#L2096-L2099)、[worker.py:404](file:///C:/Users/user/Desktop/OmniKeep/app/queue/worker.py#L404)
- **證據片段**：
  ```ts
  // frontend/src/components/modals/AddDialog.vue:115 (saveNote)
  const data = await api.ingest(content, { category: category.value === AUTO ? null : category.value, asNote: true })

  // frontend/src/components/modals/AddDialog.vue:141 (saveLinks)
  const data = await api.ingest(url, { async: queued })
  ```
  ```html
  <!-- frontend/src/components/modals/AddDialog.vue:267-270 -->
  <div v-if="plan.kind === 'note'" class="flex items-center justify-between gap-4 text-sm">
    <span class="text-muted-foreground">分類</span>
    <Select v-model="category" :options="categoryOptions" :disabled="busy" aria-label="分類" small />
  </div>
  ```
- **觸發情境**：使用者打開「新增」對話框並貼上一個或多個網址時，`plan.kind` 不為 `'note'`，分類下拉選單不會出現；就算程式層將選單顯示出來，現有 `saveLinks` 呼叫 `api.ingest(url, { async: queued })` 也未把 `category` 帶給後端。
- **影響面**：
  - 前端：[AddDialog.vue](file:///C:/Users/user/Desktop/OmniKeep/frontend/src/components/modals/AddDialog.vue) 開放 `plan.kind === 'links'`（或非空時）顯示分類選單並傳遞 `category` 參數。
  - 後端與資料結構：目前單一一般網址走同步路徑時，`app/routers/ingest.py:90` 會將 `req.category` 傳給 `run_pipeline(clean_input, req.category, ...)`；**但多連結批次送出（`queued = true`，`async_mode`）或超過長度門檻的 YouTube 長影片（`ingest.py:67-86`）會轉入非同步佇列**。`ingest_tasks` 資料表（`database.py:242-255`）目前只有 `id, url, source, chat_id, message_id, status, error_message, item_id, retry_count, created_at, updated_at`，**沒有 `category` 欄位**；`create_ingest_task()` 的寫入語句（`database.py:2096-2099`）與背景排程 `worker.py:404`（`run_pipeline(url)`）都沒有接收或轉傳手動分類。若要讓批次貼網址與長影片也支援手動分類，需一併修改資料庫欄位（migration）、`ingest.py` 與 `worker.py`。

---

### 2. 原文分頁無快照時是死胡同

- **判定**：屬實（`606161b` 僅在「重點分析」分頁、`ItemCover` 與 `OriginIcon` 補回原網頁連結，未改動 `ReaderTab.vue`）
- **目前位置**：
  - [ReaderTab.vue:28-37](file:///C:/Users/user/Desktop/OmniKeep/frontend/src/components/reader/ReaderTab.vue#L28-L37)
  - 對照 `606161b` 已加連結的位置：[AnalysisTab.vue:117-129](file:///C:/Users/user/Desktop/OmniKeep/frontend/src/components/reader/AnalysisTab.vue#L117-L129)、[AnalysisTab.vue:151-159](file:///C:/Users/user/Desktop/OmniKeep/frontend/src/components/reader/AnalysisTab.vue#L151-L159)
- **證據片段**：
  ```html
  <!-- frontend/src/components/reader/ReaderTab.vue:28-37 -->
  <div v-if="ui.activeItem?.content_raw" ... v-html="renderMarkdown(ui.activeItem.content_raw)" />
  <div v-else class="flex flex-col items-center gap-3 rounded-xl border border-border bg-card py-16 text-center">
    <BookX class="size-8 text-subtle-foreground" />
    <p class="font-mono text-xs text-muted-foreground">未抓取到原文快照或純淨內文</p>
  </div>
  ```
- **觸發情境**：使用者打開一則 `content_raw` 為空的收藏（例如僅存書籤、動態渲染失敗或探索摘要項目），切換至「原文」分頁時，畫面上只會顯示圖示與「未抓取到原文快照或純淨內文」，沒有提供前往原網頁或檢視離線快照（`app/pipeline.py:1047-1052` 會在抓取到可用 HTML 時儲存離線快照）的操作按鈕。
- **影響面**：
  - 純前端元件：[ReaderTab.vue](file:///C:/Users/user/Desktop/OmniKeep/frontend/src/components/reader/ReaderTab.vue)（可複用 `originLink`（[originLink.ts](file:///C:/Users/user/Desktop/OmniKeep/frontend/src/lib/originLink.ts)）與 `useMutations().openSnapshot`（[useMutations.ts](file:///C:/Users/user/Desktop/OmniKeep/frontend/src/composables/useMutations.ts)））。不涉及後端與資料庫。

---

### 3. 隨手筆記來源露出英文 `snippet`、選單有無效連結

- **判定**：部分屬實
  - 「URL 是 `local://snippet/{id}`、`cleanHost()` 露出英文 `snippet`」：**不屬實**（目前程式產生的是 `note://` 或原網頁 `#snippet-`，全庫與 git 歷史皆無 `local://`；但 `cleanHost()` 確實採黑名單而非白名單，若傳入其他自訂協定確實會抽出偽 host）。
  - 「選單『開啟原始連結』對非網頁筆記呈現無效連結」：**屬實**。
- **目前位置**：
  - [pipeline.py:953-966](file:///C:/Users/user/Desktop/OmniKeep/app/pipeline.py#L953-L966)（隨手筆記 URL 產生邏輯）
  - [format.ts:4-19](file:///C:/Users/user/Desktop/OmniKeep/frontend/src/lib/format.ts#L4-L19)（`cleanHost`）
  - [ItemActions.vue:57](file:///C:/Users/user/Desktop/OmniKeep/frontend/src/components/items/ItemActions.vue#L57)（更多操作選單）
- **證據片段**：
  ```python
  # app/pipeline.py:953-966
  source_type = "snippet"
  ...
  if embedded_urls:
      primary_url = embedded_urls[0]
      url = f"{primary_url}#snippet-{item_id_seed}"
  else:
      url = f"note://{item_id_seed}"
  ```
  ```html
  <!-- frontend/src/components/items/ItemActions.vue:57 -->
  <DropdownMenuItem as-child><a :href="item.url" target="_blank" rel="noopener noreferrer" class="app-menu__item"><ExternalLink />開啟原始連結</a></DropdownMenuItem>
  ```
  - 實測佐證：
    - `git log -S "local://"` 無任何紀錄；正式庫 3,480 筆資料中 `local://` 共有 0 筆、`note://` 共有 3 筆、`source_type="snippet"` 共有 4 筆。
    - `cleanHost()` 在 `format.ts` 先檢查 `if (url.startsWith('note://')) return '筆記片段'`，故現有 `note://` 筆記不會露出英文 `snippet`；但用 Node 測試 `new URL('local://snippet/abc').hostname` 確實得到 `'snippet'`，說明 `cleanHost` 僅排除 `note://` 而不是要求 `https?://`。
    - `606161b` 已於 `AnalysisTab.vue:118` 等處改用 `originLink()` 過濾 `/^https?:$/`，但 `ItemActions.vue:57` 仍無條件輸出 `<a :href="item.url">`。
- **觸發情境**：對純隨手筆記（`url` 為 `note://{seed}`）開啟項目右側「更多操作」選單，仍看得到並可點擊「開啟原始連結」，瀏覽器會嘗試開啟無效的 `note://...` URI。
- **影響面**：
  - 前端：[ItemActions.vue](file:///C:/Users/user/Desktop/OmniKeep/frontend/src/components/items/ItemActions.vue)（可比照 [originLink.ts](file:///C:/Users/user/Desktop/OmniKeep/frontend/src/lib/originLink.ts) 的 `isWebLink`／`/^https?:$/` 條件隱藏）、及視情況一併檢查 [format.ts](file:///C:/Users/user/Desktop/OmniKeep/frontend/src/lib/format.ts) 的 `cleanHost()` 是否改以 `http(s):` 白名單處理。不涉及後端與資料庫。

---

### 4. 清單視圖未分類項目沒有「收件匣」標籤

- **判定**：不屬實
- **目前位置**：[ItemRow.vue:44-47](file:///C:/Users/user/Desktop/OmniKeep/frontend/src/components/items/ItemRow.vue#L44-L47)、[database.py:64](file:///C:/Users/user/Desktop/OmniKeep/app/database.py#L64)、[database.py:597](file:///C:/Users/user/Desktop/OmniKeep/app/database.py#L597)
- **證據片段**：
  ```html
  <!-- frontend/src/components/items/ItemRow.vue:44-47 -->
  <template v-if="item.category_name">
    <span class="item-meta__sep" aria-hidden="true" />
    <span class="item-meta__clip">{{ displayCategory(item.category_name) }}</span>
  </template>
  ```
- **查證事實**：
  - 後端資料庫 `items.category_name` 預設即為 `'Inbox'`（`database.py:64, 597`），非空字串；`Inbox` 屬 truthy，因此 `<template v-if="item.category_name">` 本就會成立。
  - 在 `6e95954` 之前，`ItemRow.vue:46` 就已用三元運算 `item.category_name === 'Inbox' ? '收件匣' : item.category_name` 顯示為「收件匣」，後續提交 `6e95954` 進一步抽成共用 helper `displayCategory(item.category_name)`。
  - 正式庫 3,480 筆資料中，`category_name` 為空值／null 者共有 **0 筆**，`'Inbox'` 共有 **1,535 筆**。僅有在資料本身異常為空字串或 `null` 時才會因 `v-if="item.category_name"` 而不渲染。
- **影響面**：無須為標準 `'Inbox'` 補標籤（已正常顯示）；若要防呆極端空字串資料，範圍僅限 [ItemRow.vue:44-47](file:///C:/Users/user/Desktop/OmniKeep/frontend/src/components/items/ItemRow.vue#L44-L47) 一處 `v-if` 條件。

---

### 5. 「新增分類字典」舊術語

- **判定**：屬實
- **目前位置**：[CategoryDialog.vue:39](file:///C:/Users/user/Desktop/OmniKeep/frontend/src/components/modals/CategoryDialog.vue#L39)
- **證據片段**：
  ```html
  <!-- frontend/src/components/modals/CategoryDialog.vue:39 -->
  <DialogTitle>新增分類字典</DialogTitle>
  ```
- **觸發情境**：使用者點擊側邊欄「分類」標題旁的 `+` 按鈕開啟新增分類彈窗時，對話框標題顯示「新增分類字典」（全 repo 僅此一處仍殘留「分類字典」四字）。
- **影響面**：純文案修改，僅影響 [CategoryDialog.vue:39](file:///C:/Users/user/Desktop/OmniKeep/frontend/src/components/modals/CategoryDialog.vue#L39) 一行；無後端與測試關聯。

---

### 6. J/K 換篇時原文分頁變空白

- **判定**：屬實（補充：呈現的是「未抓取到原文快照或純淨內文」空狀態卡，而非全白畫面）
- **目前位置**：
  - [useKeyboard.ts:179-194](file:///C:/Users/user/Desktop/OmniKeep/frontend/src/composables/useKeyboard.ts#L179-L194)（`moveTo` 更新 `ui.activeItem` 未重設 `ui.detailTab`；對照 `:207` 按 `Enter` 明確設定 `ui.detailTab = 'analysis'`）
  - [ReaderPane.vue:46-52](file:///C:/Users/user/Desktop/OmniKeep/frontend/src/components/reader/ReaderPane.vue#L46-L52)、[ReaderPane.vue:76-78](file:///C:/Users/user/Desktop/OmniKeep/frontend/src/components/reader/ReaderPane.vue#L76-L78)、[ReaderPane.vue:172](file:///C:/Users/user/Desktop/OmniKeep/frontend/src/components/reader/ReaderPane.vue#L172)
  - [ReaderTab.vue:28-37](file:///C:/Users/user/Desktop/OmniKeep/frontend/src/components/reader/ReaderTab.vue#L28-L37)
- **觸發情境**：使用者在閱讀面板切到「原文」分頁（`ui.detailTab === 'reader'`）閱讀有原文的文章後，按下 `J` / `↓` 或 `K` / `↑` 切換到下一／上一則（或載入中的新項目尚無 `content_raw`），`ReaderPane` 不會重設 `ui.detailTab`，畫面停留在「原文」分頁並顯示空狀態提示卡片（或等待讀取完畢後依然顯示無內文卡片）。
- **影響面**：
  - 前端：[ReaderPane.vue](file:///C:/Users/user/Desktop/OmniKeep/frontend/src/components/reader/ReaderPane.vue)（於 `loadFull` 完成後或切換 `activeItem` 時判斷是否保留 `reader` 分頁）、[useKeyboard.ts](file:///C:/Users/user/Desktop/OmniKeep/frontend/src/composables/useKeyboard.ts)，以及詳見「清單外 #3」的 `AnalysisTab.vue` 內部切篇入口。不涉及後端與資料庫。

---

### 7. 窄螢幕詳情頁標頭標題與來源互擠

- **判定**：不屬實
- **目前位置**：
  - [ReaderPane.vue:72](file:///C:/Users/user/Desktop/OmniKeep/frontend/src/components/reader/ReaderPane.vue#L72)（`const merged = computed(() => isLg.value && paneW.value >= 840)`）
  - [ReaderPane.vue:100-103](file:///C:/Users/user/Desktop/OmniKeep/frontend/src/components/reader/ReaderPane.vue#L100-L103)（頂欄）
  - [ReaderPane.vue:140-162](file:///C:/Users/user/Desktop/OmniKeep/frontend/src/components/reader/ReaderPane.vue#L140-L162)（`!merged` 次級列）
  - [AnalysisTab.vue:113](file:///C:/Users/user/Desktop/OmniKeep/frontend/src/components/reader/AnalysisTab.vue#L113)（文章 `<h1>` 標題實際所在）
- **證據片段**：
  ```html
  <!-- frontend/src/components/reader/ReaderPane.vue:100-103 -->
  <div class="relative flex min-h-14 shrink-0 items-center justify-between gap-1 border-b border-hairline px-2 sm:px-4">
    <button class="item-action" :class="ui.focusMode ? '' : 'lg:hidden'" aria-label="返回清單" title="返回清單（Esc）" @click="closeReader"><ArrowLeft class="size-5" /></button>
    <span class="min-w-0 truncate text-sm text-muted-foreground" :class="merged && !ui.focusMode ? 'mr-3 shrink' : 'flex-1'">{{ sourceName(ui.activeItem) }}</span>
  ```
- **實測與查證事實**：
  - 標題（`<h1>`）位於主文捲動區（`AnalysisTab.vue:113`），**並未出現在 `ReaderPane.vue` 頂欄**。
  - 在 `< 840px`（`!merged`）時，頂欄只放返回鈕（手機／整頁模式顯示，桌機側邊欄隱藏）、`sourceName(ui.activeItem)`（`flex-1`），以及右側操作鈕（`ItemActions`，桌機另加放大與關閉鈕）；分頁標籤、字級、分類選單與封存狀態都已移至第二列（`ReaderPane.vue:140-162`）。
  - 於正式站 `http://127.0.0.1:5000` 以無頭 Edge 實測（來源 `huggingface.co`）：
    - `375px` 手機全頁：`paneW=375`，`spanW=191`，`spanScrollW=191`（未截斷）
    - `768px` 平板全頁：`paneW=768`，`spanW=568`，`spanScrollW=568`（未截斷）
    - `1024px` 桌機雙欄：`paneW=392`，`spanW=147`，`spanScrollW=147`（右側 5 顆按鈕共 200px，來源仍未截斷）
    - `1280px` 桌機雙欄：`paneW=607`，`spanW=362`
    - `1440px` 桌機雙欄：`paneW=700`，`spanW=455`
- **影響面**：無既有「標題與來源互擠」問題可修；除非針對極窄欄寬下極長的來源名稱，現有頂欄來源並無「只剩 2～3 字」狀況。

---

### 8. 未分析完成時「複製重點」複製出空字串

- **判定**：部分屬實
  - 「複製出空字串」：**不精確**（剪貼簿一定包含 `title_l1` 與 `原始連結：${url}`，不會是全空）。
  - 「未分析完成項目的重點區空白且 toast 仍報『已複製重點』」：**屬實**（僅針對探索尚未分析的項目）。
- **目前位置**：
  - [ItemActions.vue:18-25](file:///C:/Users/user/Desktop/OmniKeep/frontend/src/components/items/ItemActions.vue#L18-L25)
  - [scheduler.py:156-168](file:///C:/Users/user/Desktop/OmniKeep/app/radar/scheduler.py#L156-L168)（探索待分析項目寫入 `"summary_l1": ""`）
  - 對照其他尚未分析來源：[pipeline.py:997-1000](file:///C:/Users/user/Desktop/OmniKeep/app/pipeline.py#L997-L1000)（寫入 `not_analysed_summary(...)`）、[items.py:349](file:///C:/Users/user/Desktop/OmniKeep/app/routers/items.py#L349)（書籤無 AI 寫入「自書籤匯入（分類/資料夾：...）」）
- **證據片段**：
  ```ts
  // frontend/src/components/items/ItemActions.vue:18-25
  async function copyTakeaway() {
    try {
      await navigator.clipboard.writeText(`${props.item.title_l1}\n\n${props.item.summary_l1}\n\n原始連結：${props.item.url}`)
      toast.success('已複製重點')
    } catch {
  ```
  ```python
  # app/radar/scheduler.py:160-161
  "title_l1": (raw.title or "（待分析）")[:120],
  "summary_l1": "",
  ```
- **觸發情境**：正式庫 3,480 筆資料中共有 **1,495 筆** `summary_l1 === ""`（探索暫存項目）。對這類項目點擊「複製重點」，剪貼簿會寫入 `標題\n\n\n\n原始連結：https://...`（中間段落空白），且畫面提示仍顯示「已複製重點」。
- **影響面**：純前端元件 [ItemActions.vue:18-25](file:///C:/Users/user/Desktop/OmniKeep/frontend/src/components/items/ItemActions.vue#L18-L25)（依 `!item.summary_l1` 或 `isNotAnalysed(item)` 調整拼接字串與 toast 文案）。不影響後端或資料庫。

---

## 第二部分：設定頁整併建議（A–D）

### A. 「分析深度」「關於你」從「一般」移到「AI」

- **判定**：屬實（兩者在元件定位上確屬 `GeneralSection.vue` 內與 AI 提示相關的設定）
- **目前位置與證據**：
  - [GeneralSection.vue:49-57](file:///C:/Users/user/Desktop/OmniKeep/frontend/src/components/settings/GeneralSection.vue#L49-L57)：呈現 `<SettingBlock id="analysis" title="分析">`（`ANALYSIS_DEPTH`）與 `<SettingBlock id="profile" title="關於你">`（`USER_BACKGROUND`、`LOCAL_HARDWARE`）。
  - [settingsSections.ts:16,35](file:///C:/Users/user/Desktop/OmniKeep/frontend/src/lib/settingsSections.ts#L16)：`general` 分頁導語為「外觀，以及 AI 分析時參考的背景。」；舊連結對照 `LEGACY_TABS.profile` 對應 `['general', 'profile']`。
  - 後端定義與消費者：[app_settings.py:74,115-126](file:///C:/Users/user/Desktop/OmniKeep/app/app_settings.py#L74)（group 為 `"profile"`）、[pipeline.py:198,361,374,375,394](file:///C:/Users/user/Desktop/OmniKeep/app/pipeline.py#L198)、[brain.py:249](file:///C:/Users/user/Desktop/OmniKeep/app/brain.py#L249)、[setup_flow.py:349,350,802,811](file:///C:/Users/user/Desktop/OmniKeep/app/setup_flow.py#L349)。
- **影響面**：
  - 前端：[GeneralSection.vue](file:///C:/Users/user/Desktop/OmniKeep/frontend/src/components/settings/GeneralSection.vue)、[AiSection.vue](file:///C:/Users/user/Desktop/OmniKeep/frontend/src/components/settings/AiSection.vue)、[settingsSections.ts:16,18,35](file:///C:/Users/user/Desktop/OmniKeep/frontend/src/lib/settingsSections.ts#L16)（`LEGACY_TABS.profile` 需改指 `['ai', 'profile']`，否則 `sectionOfGroup('profile')` 在儲存錯誤時會跳錯分頁）、[settings-sections.test.mjs:26](file:///C:/Users/user/Desktop/OmniKeep/frontend/tests/settings-sections.test.mjs#L26)。
  - 後端：`pipeline.py`、`brain.py`、`setup_flow.py` 皆是依設定 key 名稱直接讀取，不因 UI 分頁改變而受影響。

---

### B. 收掉 AI 頁的舊「提問」表單

- **判定**：部分屬實（UI 上與 [AiConnections.vue](file:///C:/Users/user/Desktop/OmniKeep/frontend/src/components/settings/AiConnections.vue) 的 `brain` 槽位「提問」（[settingsText.ts:50](file:///C:/Users/user/Desktop/OmniKeep/frontend/src/lib/settingsText.ts#L50)）功能重疊，**但後端並非廢棄欄位，仍有核心推論函式與雙向同步直接讀取 `BRAIN_*`**）
- **目前位置與證據**：
  ```html
  <!-- frontend/src/components/settings/AiSection.vue:9, 15-25 -->
  const ASK_KEYS = ['BRAIN_PROVIDER', 'BRAIN_BASE_URL', 'BRAIN_MODEL', 'BRAIN_MAX_CITATIONS', 'BRAIN_NUM_CTX']
  ...
  <SettingBlock id="ask" title="提問" description="用收藏的內容回答你的問題，並附上引用的收藏。">
    <FieldRow field-key="BRAIN_PROVIDER" stacked />
    <FieldRow field-key="BRAIN_BASE_URL" />
    <FieldRow field-key="BRAIN_MODEL" placeholder="例如 qwen3:8b" />
    <FieldRow field-key="BRAIN_MAX_CITATIONS" />
    <FieldRow field-key="BRAIN_NUM_CTX" />
    <template #foot>
      <SaveBar :keys="ASK_KEYS" />
      <CheckButton service="brain" label="測試本機模型" :keys="ASK_KEYS" />
    </template>
  </SettingBlock>
  ```
- **後端與資料依賴完整盤點（誰還在讀 `BRAIN_*`）**：
  1. **核心 RAG 問答與健康檢查** — [brain.py:116,165-185,231,242-243](file:///C:/Users/user/Desktop/OmniKeep/app/brain.py#L116)：
     `ask_brain()` **直接檢查 `settings.BRAIN_PROVIDER in ("ollama", "strata")`**，並用 `settings.BRAIN_BASE_URL`、`settings.BRAIN_MODEL`、`settings.BRAIN_NUM_CTX` 呼叫 Ollama `/api/chat`，僅在本地失敗或 `BRAIN_PROVIDER` 為 `"cloud"` 時才退回 `get_provider("brain")`；`limit` 上限讀取 `settings.BRAIN_MAX_CITATIONS`；`get_brain_status()` 也直接讀 `BRAIN_BASE_URL`、`BRAIN_MODEL`、`BRAIN_PROVIDER`。
  2. **AI 連線槽位雙向同步** — [ai_connections.py:743-777,828,907-920,924-949](file:///C:/Users/user/Desktop/OmniKeep/app/ai_connections.py#L924-L949)：
     `push_brain_settings()` 會把 `brain` 槽位第一筆連線反寫回 `BRAIN_PROVIDER`／`BRAIN_BASE_URL`／`BRAIN_MODEL`（並於切換為雲端連線時寫入 `BRAIN_PROVIDER = "cloud"`）；反之，透過 `/api/settings` 修改 `BRAIN_*` 時，`sync_from_settings()` 亦會回寫 `brain` 槽位。
  3. **設定檢查 API** — [connection_checks.py:417-440](file:///C:/Users/user/Desktop/OmniKeep/app/connection_checks.py#L417-L440)：
     `POST /api/settings/check/brain`（`_check_brain`）讀取 `BRAIN_PROVIDER`、`BRAIN_BASE_URL`、`BRAIN_MODEL`。
  4. **開通導覽偵測** — [setup_flow.py:270](file:///C:/Users/user/Desktop/OmniKeep/app/setup_flow.py#L270)：
     `_local_inference()` 在 `OLLAMA_BASE_URL` 為空時 fallback 到 `settings.BRAIN_BASE_URL`。
  5. **設定 Schema、預設值與既有測試**：
     - [app_settings.py:73,105-113](file:///C:/Users/user/Desktop/OmniKeep/app/app_settings.py#L105-L113)（定義 `"brain"` group 與 5 個 `BRAIN_*` `Spec`）
     - [config.py:44-50](file:///C:/Users/user/Desktop/OmniKeep/app/config.py#L44-L50)
     - [settingsSections.ts:34](file:///C:/Users/user/Desktop/OmniKeep/frontend/src/lib/settingsSections.ts#L34)（`LEGACY_TABS.brain = ['ai', 'ask']`）
     - [test_ai_connections.py:172-183,514,516,527](file:///C:/Users/user/Desktop/OmniKeep/tests/test_ai_connections.py#L172-L183)、[test_app_settings.py:388-441](file:///C:/Users/user/Desktop/OmniKeep/tests/test_app_settings.py#L388-L441)、[test_brain_context.py:46-68](file:///C:/Users/user/Desktop/OmniKeep/tests/test_brain_context.py#L46-L68)、[test_first_day_fixes.py:100](file:///C:/Users/user/Desktop/OmniKeep/tests/test_first_day_fixes.py#L100)
- **影響面**：若僅隱藏前端欄位而不重構 `app/brain.py`、`app/ai_connections.py` 改為直接讀槽位連線，則 `BRAIN_PROVIDER`／`BRAIN_BASE_URL`／`BRAIN_MODEL` 仍是 `ask_brain()` 的實際執行來源；若連後端一併下線，需同步更新上述 5 支後端模組與 4 支 pytest 測試檔。

---

### C. 匯入與匯出放一起

- **判定**：屬實（現況「匯入書籤」與「匯出」按鈕確實分散在兩個設定分頁，點擊後開啟的卻是同一個對話框）
- **目前位置與證據**：
  - [ChannelsSection.vue:62-66](file:///C:/Users/user/Desktop/OmniKeep/frontend/src/components/settings/ChannelsSection.vue#L62-L66)：`<SettingBlock id="import" title="匯入書籤">` 呼叫 `ui.openImport('file')`
  - [DataSection.vue:24-28](file:///C:/Users/user/Desktop/OmniKeep/frontend/src/components/settings/DataSection.vue#L24-L28)：`<SettingBlock id="export" title="匯出">` 呼叫 `ui.openImport('export')`
  - [ImportDialog.vue:259-300](file:///C:/Users/user/Desktop/OmniKeep/frontend/src/components/modals/ImportDialog.vue#L259-L300)：本身已經包含 `上傳檔案`（`file`）、`貼上內容`（`text`）、`書籤列按鈕`（`bookmarklet`）、`匯出收藏`（`export`）4 個標籤頁。
- **影響面**：
  - 純前端與文件調整：[ChannelsSection.vue](file:///C:/Users/user/Desktop/OmniKeep/frontend/src/components/settings/ChannelsSection.vue)、[DataSection.vue](file:///C:/Users/user/Desktop/OmniKeep/frontend/src/components/settings/DataSection.vue)、[settingsSections.ts:17,20](file:///C:/Users/user/Desktop/OmniKeep/frontend/src/lib/settingsSections.ts#L17)（`SETTINGS_SECTIONS` 的 `label` 與 `lead`）、[SearchBox.vue:131](file:///C:/Users/user/Desktop/OmniKeep/frontend/src/components/layout/SearchBox.vue#L131)（關鍵字索引）、[settings-sections.test.mjs](file:///C:/Users/user/Desktop/OmniKeep/frontend/tests/settings-sections.test.mjs)。不牽涉後端 API 或資料庫。

---

### D. 通知頁收攏（「發送管道 × 通知事件」）

- **判定**：現象屬實，但「改成『發送管道 × 通知事件』矩陣」目前**缺少對應的後端模型與分派過濾邏輯**
- **目前位置與證據**：
  - [NotificationsSection.vue:15-26](file:///C:/Users/user/Desktop/OmniKeep/frontend/src/components/settings/NotificationsSection.vue#L15-L26)：目前僅有 `<PushPanel />`（本機 Web Push）、`#telegram-notify`（僅放一顆跳往 `channels#telegram` 的按鈕）與 `#contact`（`VAPID_SUBJECT`）。
  - [RadarDialog.vue:476-570](file:///C:/Users/user/Desktop/OmniKeep/frontend/src/components/modals/RadarDialog.vue#L476-L570)：探索的 `notification_mode`（`silent` / `daily_digest` / `vip_alert`）、`daily_digest_hour` 與 `vip_threshold` 放在探索設定彈窗內，且標題仍寫 `Telegram 通知`（`:481`）。
  - **後端真實行為**：[scheduler.py:323-342](file:///C:/Users/user/Desktop/OmniKeep/app/radar/scheduler.py#L323-L342) 的 `_announce_autostar`、`_announce_vip`、`_announce_digest` 會在觸發時**同時無條件廣播給 Telegram、Web Push 與 LINE 三個管道**；[push.py:150-161](file:///C:/Users/user/Desktop/OmniKeep/app/push.py#L150-L161) 的 `notify_new_proposal` 則只發送 Web Push；[telegram_bot.py:789-817](file:///C:/Users/user/Desktop/OmniKeep/app/bot/telegram_bot.py#L789-L817) 另有 per-user 的 `/mode [heartbeat|quiet]` 指令（存在 `user_settings`），管理主動收錄回應進度而非探索事件。
  - 資料庫欄位：[database.py:148-160](file:///C:/Users/user/Desktop/OmniKeep/app/database.py#L148-L160) 中的 `radar_settings` 僅有單一 `notification_mode` 與舊旗標 `auto_digest_push`、`auto_star_push`（沒有依管道細分的開關），讀寫函式見 [database.py:1369,1382,1394,1417](file:///C:/Users/user/Desktop/OmniKeep/app/database.py#L1369)。
- **影響面**：
  - 若只集中現有 UI（例如把 `RadarDialog.vue` 裡的時間／模式控制同步到通知頁），需動到 [NotificationsSection.vue](file:///C:/Users/user/Desktop/OmniKeep/frontend/src/components/settings/NotificationsSection.vue)、[RadarDialog.vue](file:///C:/Users/user/Desktop/OmniKeep/frontend/src/components/modals/RadarDialog.vue) 與探索 API store。
  - 若要實作清單所稱的「發送管道 × 通知事件」開關矩陣，後端必須擴充通知偏好設定儲存（`app_settings` 或 `radar_settings`）、[routers/radar.py](file:///C:/Users/user/Desktop/OmniKeep/app/routers/radar.py)、[radar/scheduler.py:323-342](file:///C:/Users/user/Desktop/OmniKeep/app/radar/scheduler.py#L323-L342)（依事件與管道過濾發送）以及 [push.py](file:///C:/Users/user/Desktop/OmniKeep/app/push.py)／[setup_flow.py:347,842,846](file:///C:/Users/user/Desktop/OmniKeep/app/setup_flow.py#L842)。

---

## 第三部分：參考競品的方向（目前實作狀態）

- **Readwise Reader（收錄管道改成整合卡片網格：圖示、狀態、管理按鈕）**：**沒有**（[ChannelsSection.vue:35-75](file:///C:/Users/user/Desktop/OmniKeep/frontend/src/components/settings/ChannelsSection.vue#L35-L75) 目前仍是依序條列的 `SettingBlock` 與設定表單欄位，無來源整合狀態卡片網格）。
- **Linear（按鈕與選單旁標 `<kbd>` 快捷鍵、快捷鍵輔助列）**：**部分已有**（全域按 `?` 可開 [ShortcutsDialog.vue:64](file:///C:/Users/user/Desktop/OmniKeep/frontend/src/components/modals/ShortcutsDialog.vue#L64)，部分元件如 [AnalysisTab.vue:478,483](file:///C:/Users/user/Desktop/OmniKeep/frontend/src/components/reader/AnalysisTab.vue#L478) 亦有 `<kbd>` 提示，但主要工具列按鈕與 [ItemActions.vue:28-69](file:///C:/Users/user/Desktop/OmniKeep/frontend/src/components/items/ItemActions.vue#L28-L69) 下拉選單未旁標 `<kbd>`，頁面底部亦無常駐快捷鍵輔助列）。
- **Notion／Superhuman（側邊欄分類就地改名、換圖示、刪除、拖曳排序；展開不跳動）**：**沒有**（[AppSidebar.vue:122-142](file:///C:/Users/user/Desktop/OmniKeep/frontend/src/components/layout/AppSidebar.vue#L122-L142) 僅提供點擊篩選與固定 `<Folder>` 圖示，且依 `item_count` 排序並將超額選中分類插入清單末端；後端 [categories.py:1-31](file:///C:/Users/user/Desktop/OmniKeep/app/routers/categories.py#L1-L31) 僅有清單／新增／刪除，缺少改名、換圖示與排序更新端點，雖然資料表欄位 `sort_order` 已定義於 [database.py:45,514,518](file:///C:/Users/user/Desktop/OmniKeep/app/database.py#L45)）。

---

## 清單外：查證過程中順便觀察到的同類問題（清單外）

1. **清單外 — 另有兩個對話框直接輸出未驗證 `https?://` 的 `item.url` 外連**：
   - [DailyDeckDialog.vue:421-431](file:///C:/Users/user/Desktop/OmniKeep/frontend/src/components/modals/DailyDeckDialog.vue#L421-L431) 直接綁定 `:href="currentCard.url"`。
   - [BrainDialog.vue:268-276](file:///C:/Users/user/Desktop/OmniKeep/frontend/src/components/modals/BrainDialog.vue#L268-L276) 直接綁定 `:href="cite.url"`。
   - 兩者皆未比照 [DeckDialog.vue:45-48](file:///C:/Users/user/Desktop/OmniKeep/frontend/src/components/modals/DeckDialog.vue#L45-L48) 或 [originLink.ts](file:///C:/Users/user/Desktop/OmniKeep/frontend/src/lib/originLink.ts) 過濾非網頁協定（如 `note://`）。
2. **清單外 — 「離線快照」按鈕對無快照或 `note://` 項目仍無條件顯示**：
   - [ItemActions.vue:56](file:///C:/Users/user/Desktop/OmniKeep/frontend/src/components/items/ItemActions.vue#L56)、[AnalysisTab.vue:151-159](file:///C:/Users/user/Desktop/OmniKeep/frontend/src/components/reader/AnalysisTab.vue#L151-L159) 與 [AnalysisTab.vue:502](file:///C:/Users/user/Desktop/OmniKeep/frontend/src/components/reader/AnalysisTab.vue#L502) 都無條件渲染「離線快照／開啟離線快照」按鈕，未先判斷連結類型或快照存在狀態，點擊後僅能在 API 回傳 404 時顯示錯誤 toast。
3. **清單外 — `AnalysisTab.vue` 內切換項目與清單 6 同樣未重設 `ui.detailTab`**：
   - [AnalysisTab.vue:101-103](file:///C:/Users/user/Desktop/OmniKeep/frontend/src/components/reader/AnalysisTab.vue#L101-L103)（`openItem`）與 [AnalysisTab.vue:477,482](file:///C:/Users/user/Desktop/OmniKeep/frontend/src/components/reader/AnalysisTab.vue#L477)（底部的上一篇／下一篇按鈕）直接變更 `ui.activeItem`，未配合處理分頁切換邏輯。
4. **清單外 — 分類顯示與列表呈現不一致**：
   - 手機版頂欄 [AppHeader.vue:93](file:///C:/Users/user/Desktop/OmniKeep/frontend/src/components/layout/AppHeader.vue#L93) 直接渲染 `items.currentCategory`，未經過 `displayCategory()`，選取未分類時頂欄標題會露出英文 `Inbox`。
   - 側邊欄 [AppSidebar.vue:60](file:///C:/Users/user/Desktop/OmniKeep/frontend/src/components/layout/AppSidebar.vue#L60) 仍自寫 `name === 'Inbox' ? '收件匣' : name`，未複用 `displayCategory()`；且封面牆 [ItemCards.vue:42-54](file:///C:/Users/user/Desktop/OmniKeep/frontend/src/components/items/ItemCards.vue#L42-L54) 完全不顯示分類名稱，與清單視圖 [ItemRow.vue:46](file:///C:/Users/user/Desktop/OmniKeep/frontend/src/components/items/ItemRow.vue#L46) 不一致。
5. **清單外 — `ItemList.vue` 重複實作 `bookmarkletHref`**：
   - [ItemList.vue:156-159](file:///C:/Users/user/Desktop/OmniKeep/frontend/src/components/items/ItemList.vue#L156-L159) 自行組裝書籤小工具 `javascript:` 字串，與已獨立抽出的 [bookmarklet.ts:6-8](file:///C:/Users/user/Desktop/OmniKeep/frontend/src/lib/bookmarklet.ts#L6-L8) 重複。
