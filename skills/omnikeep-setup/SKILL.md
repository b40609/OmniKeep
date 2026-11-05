---
name: omnikeep-setup
description: 安裝 OmniKeep（自架第二大腦與資訊雷達），並用最多 6 題的簡短訪談帶使用者完成首次設定：關注主題、雷達來源、AI 管道、分析深度、雷達摘要送到哪和幾點。使用者說「幫我安裝 OmniKeep」「幫我設定 OmniKeep」「重新設定 OmniKeep」「OmniKeep 裝好了然後呢」「多加幾個 X 的來源」「摘要改到晚上」「匯入書籤」時使用。Installs OmniKeep and runs its first-time setup interview.
---

# OmniKeep 安裝與設定

目標：從安裝一路帶到「第一次成功」：使用者看到為自己挑的雷達來源、第一篇分析、第一份雷達摘要。使用者只需要回答幾題、在 OmniKeep 頁面自己貼金鑰、按確認。

原則：

- **先掃描**：掃得到的不問，只請使用者確認。
- **最多 6 題，選擇題為主**。使用者說「再問深一點」才多問。
- **你只判斷，OmniKeep 寫入**：你把答案寫成 JSON 交給 `omnikeep_preview_setup`；設定一律由 OmniKeep 驗證後寫入。不要自己改資料庫、`.env` 或設定檔。
- **寫入前先預覽**，使用者同意才套用。
- **金鑰不經過聊天**：用 `omnikeep_open_settings` 拿到設定頁連結，請使用者自己在頁面貼上，貼完你再呼叫 `omnikeep_test_provider`。使用者在聊天裡貼了金鑰：不要複述、不要寫進任何檔案，提醒使用者這把金鑰已經送進對話紀錄，建議到服務商那邊換一把新的，再到設定頁貼。只有使用者明確要求時，才改用聊天裡給的金鑰。
- **不讀、不印金鑰**：工具只回傳「已設定」與末四碼，照原樣轉述就好。
- **選項只說明，不替使用者決定**：各 AI 管道的優缺點講清楚，讓使用者選。

## 怎麼問

- **Claude Code**：用 AskUserQuestion，每題一次；題 5、題 6 一起問。
- **Codex、Antigravity**：把題目和選項列成編號清單，請使用者用編號回答（多選用逗號分隔，例如 `1,3`）。
- 每題都可以讓使用者自由輸入；使用者的話優先於你的猜測。

## 0. 安裝（還沒裝 OmniKeep 時）

先判斷有沒有裝好：

- 這個 session 裡有 `omnikeep_scan` 工具（Claude Code 裡叫 `mcp__omnikeep__omnikeep_scan`）：已安裝也已註冊，直接到第 1 步。
- 沒有工具，但使用者說已經裝了：問 OmniKeep 資料夾在哪，在那裡跑 `python scripts/register_agents.py`（有 `.venv` 就用 `.venv` 裡的 Python），然後請使用者開新的 session 再說「繼續設定 OmniKeep」。
- 都沒有：照下面安裝。

安裝步驟（預設裝在家目錄的 `OmniKeep` 資料夾；使用者要別的位置就換掉路徑）：

1. 檢查 `git`、Python 3.12 以上、Node.js 20.19 以上。缺的話，先跟使用者說要裝哪幾個，然後代為安裝（Windows 用 `winget`，macOS 用 `brew`，Linux 用系統套件管理員）。
2. clone 並執行安裝腳本。先讀過腳本內容再執行：
   - Windows（PowerShell）：
     ```
     git clone https://github.com/b40609/OmniKeep.git "$HOME\OmniKeep"
     powershell -NoProfile -ExecutionPolicy Bypass -File "$HOME\OmniKeep\scripts\install.ps1"
     ```
   - macOS、Linux：
     ```
     git clone https://github.com/b40609/OmniKeep.git ~/OmniKeep
     bash ~/OmniKeep/scripts/install.sh
     ```
   腳本會：建立 `.venv`、安裝依賴、產生 `.env`（含隨機存取金鑰，不會印出來）、建置前端、啟動服務並設定自動重啟（Windows 是排程工作「OmniKeep Watchdog」）、把 MCP 與這份 Skill 註冊到這台電腦的 Claude Code、Codex、Antigravity。
   想先看會做什麼：Windows 加 `-DryRun`，macOS、Linux 加 `--dry-run`。
3. 安裝需要幾分鐘（依賴與前端建置），等的時候跟使用者說明在做什麼。腳本失敗時，照錯誤訊息處理；不要跳過失敗的步驟繼續往下。
4. 完成後打開 `http://127.0.0.1:5000`，確認看得到 OmniKeep。
5. MCP 要開新的 session 才會載入：請使用者開新的 session（Claude Code 也可以重新啟動），說「繼續設定 OmniKeep」，從第 1 步接著做。

## 1. 掃描

呼叫 `omnikeep_scan`。用 3 到 5 行告訴使用者看到什麼：

- 硬體（CPU、RAM、GPU、VRAM），有沒有本機推論引擎（例如 Ollama）。
- OmniKeep 的版本與狀態，收藏幾筆、雷達來源幾個。
- 已接的 AI 管道和健康狀況。
- Chrome、Edge 書籤與 GitHub 星標：只有「有沒有、幾筆」，掃描不讀內容。
- 上次訪談的答案：有的話，下面每題的預設就帶入上次的答案，使用者只改想改的。
- OmniKit profile 的語言與背景：有就照用，不再問。

**重新設定、或 OmniKeep 已經有資料時**：跳過種子與「第一次成功」，只改使用者想改的那幾項，一樣要預覽再套用。

## 2. 起草

依掃描結果和你對使用者的了解（記憶、這次與過去的對話、使用者的專案），起草：

- 3 到 5 個關注主題，每個一句話。
- 「關於你」：2 到 4 句，職務、領域、常用技術、想追的方向。不另外問使用者，第一次預覽時讓使用者看、直接改。

不要編造你不知道的事；資訊不夠就寫得保守一點。

## 3. 題 1：種子

> 我猜你最近在追 X、Y、Z。要更準的話，給我 1 到 3 個最近覺得有價值的連結。

選項：

1. 猜得對，直接用
2. 我貼連結
3. 從你的書籤或 GitHub 星標挑（掃描到書籤或 `gh` 已登入才列這個選項）
4. 改一下（自由輸入）：使用者的話取代你的猜測

- **貼了連結**：每個連結呼叫 `omnikeep_peek`（只解析，不跑 AI、不存），依內容修正主題。連結先記著，第 7 步再分析。
- **從書籤或星標挑**：只讀最近加入的 50 筆書籤的標題與資料夾名稱，或用 `gh api user/starred --paginate -q '.[].full_name'` 讀星標名稱。只用來推興趣，不寫進 OmniKeep，也不要把清單整份貼回聊天。

## 4. 題 2：主題包

1. 依主題與種子提出候選來源：RSS、YouTube 頻道、GitHub 專案、Google News 關鍵字、網頁變動。給網站首頁也可以，OmniKeep 會自己找 RSS。
2. 全部交給 `omnikeep_check_sources` 驗證，只留抓得到的。不要列出沒驗證過的來源。
3. 分成 2 到 4 包，每包 3 到 5 個來源。每個來源列出：
   - 推薦理由：對應哪個主題或種子。
   - 最近一篇的日期、每週篇數。
   - 最近 3 篇的標題。
4. 驗證後湊不滿 2 包：補上內建的 4 個範例來源當一包。

> 要追蹤哪幾包？（可複選）

最多 4 包（AskUserQuestion 每題最多 4 個選項）。一包都不勾：雷達維持關閉，第 8 步與題 5、題 6 跳過。

## 5. 題 3：AI 管道

OmniKeep 的分析、Ask Brain、雷達摘要要用 AI。

- 掃描到已經有可用的管道：只請使用者確認，可以直接跳到第 6 步。
- 否則呼叫 `omnikeep_list_provider_options` 拿選項卡片，照卡片內容說明每個選項：費用與限額、要不要信用卡、建議模型、申請連結、最後查證日期。

> 分析要用哪些 AI 管道？（可複選：第一個是主要，其餘依序當備援）

掃描到可用的先勾好。使用者選了會拿資料訓練的免費方案，照卡片說明提醒一次，不要反覆勸。

每個選中、還沒接好的管道：

1. 說明申請步驟，打開卡片的申請頁。
2. 呼叫 `omnikeep_open_settings(card=<卡片 id>)` 取得設定頁連結。使用者打開後會直接看到那張卡片的新增表單（已經接過的就是編輯表單），請他自己貼金鑰、按儲存。
3. 使用者說貼好了，再呼叫一次 `omnikeep_list_provider_options`，從 `current.connections` 找到新連線的 `id`，用 `omnikeep_test_provider(connection_id=<id>)` 測試。它會實際送一筆中文 JSON 小請求。
4. 失敗時照回傳的中文說明處理（金鑰錯、被停用、限流、模型不存在……）。一直失敗就先接下一個管道，不要卡住後面的步驟。

本機推論（例如 Ollama）不需要金鑰，測試通過就好。

都接好之後，把「主要在前、備援依序在後」的連線 id 放進答案的 `ai_order`，在第 6 步一起預覽。Ask Brain 與雷達預設跟著分析用的順序；使用者想分開設定，請他到設定頁的「用途排序」調整。

## 6. 第一次預覽與套用

把答案寫成 JSON，交給 `omnikeep_preview_setup`：

```json
{
  "stage": "initial",
  "about_me": "產線設備資料蒐集與分析，常用 Python，想追工業 AI 與邊緣推論",
  "topics": ["工業 AI", "邊緣推論", "時序資料庫"],
  "seed_urls": ["https://example.com/post"],
  "radar_sources": [
    {"type": "rss", "url": "https://example.com/feed.xml", "name": "Example Blog", "pack": "工業 AI"}
  ],
  "ai_connections": ["agnes", "ollama"]
}
```

欄位名稱與格式以 `omnikeep_preview_setup` 的工具說明為準；它回「答案有問題」時，照訊息修正 JSON 再預覽，不要繞過它自己寫設定。

把預覽原樣給使用者看。預覽包含：

- 關於你、興趣設定檔。
- 雷達來源。有勾主題包就開啟雷達，預設每 3 小時巡檢一次。
- AI 管道，以及主要和備援的順序。
- 通知先維持不送（`silent`），看完第一份雷達摘要再決定。

問「照這樣設定嗎？」要改就回到對應的題目或直接改 JSON，改完重新預覽。同意後呼叫 `omnikeep_apply_setup`，帶上預覽回傳的確認碼。確認碼過期或對不上時，重新預覽。

## 7. 第一次成功之一：分析

- **有種子連結**：用 `omnikeep_ingest` 分析（最多 3 篇），挑一篇最好的，把結果貼回來。
- **沒有種子、有勾主題包**：先做第 8 步，再分析雷達摘要裡最相關的一篇。
- **沒有種子、也沒勾主題包**：請使用者給一個網址；沒有就分析一篇範例。

分析失敗（例如免費層限流）：照錯誤說明原因，改用備援管道或稍後重試，不要卡住。

### 題 4：分析深度（看完分析才問）

> 這樣的分析可以嗎？

1. 剛好 → 不改（維持 `standard`）
2. 太長，精簡一點 → `concise`
3. 要更多技術細節 → `technical`
4. 要加落地建議 → `actionable`

## 8. 第一次成功之二：雷達摘要

一包都沒勾就跳過這一步與題 5、題 6。

用 `omnikeep_run_radar` 跑一次巡檢，產生第一份雷達摘要，把摘要貼回來。首輪巡檢加分析需要一點時間，等的時候跟使用者說在做什麼。

### 題 5、題 6（看完摘要才問；Claude Code 一起問）

> 題 5：雷達摘要要送到哪？（可複選）

1. 網頁推播：打開 OmniKeep，按「允許」就好
2. Telegram：要先建一個 Bot
3. LINE：要先建一個官方帳號
4. 不用送，我自己打開看 → `notification_mode` 用 `silent`，題 6 不用答

> 題 6：什麼時候送？

1. 每天早上 8 點
2. 中午 12 點
3. 晚上 9 點
4. 只送重要的 → `vip_alert`：分數到門檻（預設 4.0）的項目才通知，不送每日摘要

選每天幾點時告訴使用者：從那個小時起 3 小時內送出，電腦晚開機也會補送；內容是上一份摘要之後分析完的雷達項目，最多 20 篇。

- **Telegram 或 LINE**：一步步帶使用者建 Bot。Token 與密鑰一樣請使用者在設定頁自己貼（用 `omnikeep_open_settings`）。Telegram 綁定走設定頁的配對連結。
- **網頁推播**：請使用者打開 OmniKeep，按瀏覽器的「允許」。

## 9. 第二次預覽與套用

只改分析深度與通知，做法同第 6 步：

```json
{
  "stage": "followup",
  "analysis_depth": "concise",
  "notification_channels": ["web_push", "telegram"],
  "notification_mode": "daily_digest",
  "daily_digest_hour": 8
}
```

題 4 選了「剛好」以外的：下一篇開始用新寫法；想看效果，說「重新分析這篇」。

## 10. 收尾卡

用一張精簡的卡片收尾：

- 接了哪些 AI 管道、主要和備援的順序。
- 追蹤幾包、幾個來源，巡檢間隔。
- 雷達摘要送到哪、幾點，下一份什麼時候到。
- 之後想改，直接跟 agent 說，只會改那一項。例如：「多加幾個 X 的來源」「摘要改到晚上」「分析短一點」。
- 想搬舊資料，說「匯入書籤」：可以搬 Chrome、Edge 書籤、GitHub 星標、Pocket 匯出檔、OPML，用 `omnikeep_import`，預設只存標題與網址，不跑 AI。
- 每天滑卡一分鐘，推薦會越來越準。累積夠多互動後，Dreampass 會提議更新興趣設定檔，使用者批准才改。

## 之後的單項修改

使用者只想改一項時（例如「摘要改到晚上」）：不重跑整套訪談。先 `omnikeep_scan` 看現況，只問那一項，照第 6 步或第 9 步預覽、同意後套用。

- 「多加幾個 X 的來源」：照第 4 步提出並驗證候選來源，只列新的。
- 「匯入書籤」：問要匯入哪一種（書籤、星標、Pocket、OPML），用 `omnikeep_import`；匯入前說明筆數，同意才做。

## MCP 工具一覽

| 工具 | 用途 | 會寫入嗎 |
|---|---|---|
| `omnikeep_scan` | 硬體、狀態、已接管道、上次答案、OmniKit profile、書籤與星標筆數 | 否 |
| `omnikeep_peek` | 解析一個網址，不跑 AI、不存 | 否 |
| `omnikeep_check_sources` | 驗證候選雷達來源，首頁自動找 RSS | 否 |
| `omnikeep_list_provider_options` | AI 管道選項卡片 | 否 |
| `omnikeep_open_settings` | 指向某張卡片的設定頁連結 | 否 |
| `omnikeep_test_provider` | 用已存的金鑰送一筆中文 JSON 小請求 | 否 |
| `omnikeep_preview_setup` | 驗證答案 JSON，回傳設定差異與確認碼 | 否 |
| `omnikeep_apply_setup` | 套用設定，要帶確認碼 | 是 |
| `omnikeep_ingest` | 分析一個網址 | 是（新增一筆收藏） |
| `omnikeep_run_radar` | 跑一次巡檢並產生雷達摘要 | 是 |
| `omnikeep_import` | 匯入書籤、星標、Pocket、OPML | 是 |

工具回錯誤時，照錯誤訊息處理並跟使用者說明；不要改用直接讀寫資料庫或設定檔繞過。
