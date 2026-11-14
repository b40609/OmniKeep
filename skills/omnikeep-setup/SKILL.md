---
name: omnikeep-setup
description: 安裝 OmniKeep（自架的連結收藏工具：在 Telegram 丟連結，它幫你讀完，之後找得到），並用簡短訪談帶使用者完成首次設定：接上 AI、接上 Telegram、丟第一個連結。探索（實驗功能）的關注主題、探索來源與精選通知，只在使用者開了實驗功能時才問。使用者說「幫我安裝 OmniKeep」「幫我設定 OmniKeep」「重新設定 OmniKeep」「OmniKeep 裝好了然後呢」「更新 OmniKeep」「升級 OmniKeep」「多加幾個 X 的來源」「摘要改到晚上」「匯入書籤」時使用。Installs, updates OmniKeep and runs its first-time setup interview.
---

# OmniKeep 安裝與設定

目標：從安裝一路帶到「第一次成功」：使用者接上 AI、接上 Telegram，丟出第一個連結，看到它被收藏並寫好摘要。使用者只需要回答幾題、在 OmniKeep 頁面自己貼金鑰與機器人權杖、按確認。

主線只有三件事：

1. 接上 AI（可以略過：沒有 AI 也能收藏）
2. 接上 Telegram（可以略過：也能在網頁按「新增」貼連結）
3. 丟第一個連結

探索（定時檢查探索來源、整理成精選）是預設關閉的實驗功能，不在主線裡。使用者開了、或主動提到，才照最後的「實驗功能：探索」一節問。

原則：

- **先掃描**：掃得到的不問，只請使用者確認。
- **題目少，選擇題為主**。主線最多 4 題；使用者說「再問深一點」才多問。
- **你只判斷，OmniKeep 寫入**：你把答案寫成 JSON 交給 `omnikeep_preview_setup`；設定一律由 OmniKeep 驗證後寫入。不要自己改資料庫、`.env` 或設定檔。
- **寫入前先預覽**，使用者同意才套用。
- **金鑰與權杖不經過聊天**：AI 金鑰、Telegram 的機器人權杖都一樣。用 `omnikeep_open_settings` 拿到設定頁連結，請使用者自己在頁面貼上，貼完你再呼叫 `omnikeep_test_provider`。使用者在聊天裡貼了金鑰或權杖：不要複述、不要寫進任何檔案，提醒使用者它已經送進對話紀錄，建議到原本的服務那邊換一把新的，再到設定頁貼。只有使用者明確要求時，才改用聊天裡給的金鑰。
- **不讀、不印金鑰**：工具只回傳「已設定」與末四碼，照原樣轉述就好。
- **選項只說明，不替使用者決定**：各 AI 服務的優缺點講清楚，讓使用者選。
- **用畫面上的名稱**：設定在右上角頭像選單 ›「設定」，左側分成一般、收錄管道、AI、通知、資料與備份、進階、實驗功能。跟使用者講路徑時用這些名稱，例如「設定 › 收錄管道 › Telegram」「設定 › AI」。

## 怎麼問

- **Claude Code**：用 AskUserQuestion，每題一次。
- **Codex、Antigravity**：把題目和選項列成編號清單，請使用者用編號回答（多選用逗號分隔，例如 `1,3`）。
- 每題都可以讓使用者自由輸入；使用者的話優先於你的猜測。

## 0. 安裝（還沒裝 OmniKeep 時）

先判斷有沒有裝好：

- 這個 session 裡有 `omnikeep_scan` 工具（Claude Code 裡叫 `mcp__omnikeep__omnikeep_scan`）：已安裝也已註冊，直接到第 1 步。
- 沒有工具，但使用者說已經裝了：問 OmniKeep 資料夾在哪，在那裡跑 `python scripts/register_agents.py`（有 `.venv` 就用 `.venv` 裡的 Python），然後請使用者開新的 session 再說「繼續設定 OmniKeep」。
- 都沒有：照下面安裝。

安裝步驟（預設裝在家目錄的 `OmniKeep` 資料夾；使用者要別的位置就換掉路徑）：

1. 檢查 `git`、Python 3.12 以上、Node.js 20.19 以上（或 22.12 以上）。缺的話，先跟使用者說要裝哪幾個，然後代為安裝（Windows 用 `winget`，macOS 用 `brew`，Linux 用系統套件管理員）。
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
   腳本會：建立 `.venv`、安裝依賴、產生 `.env`（含隨機存取金鑰，不會印出來）、建置前端、啟動服務並設定自動重啟（Windows 是排程工作「OmniKeep Watchdog」）、把 MCP 與這份 Skill 註冊到這台電腦的 Claude Code、Codex、Antigravity。腳本可以重複執行，已完成的步驟會略過。
   想先看會做什麼：Windows 加 `-DryRun`，macOS、Linux 加 `--dry-run`。
3. 安裝需要幾分鐘（依賴與前端建置），等的時候跟使用者說明在做什麼。腳本失敗時，照錯誤訊息處理；不要跳過失敗的步驟繼續往下。
4. 完成後請使用者在這台電腦用瀏覽器打開 `http://127.0.0.1:5000`。在執行 OmniKeep 的這台電腦上打開，會直接看到主畫面，不用登入。第一次打開會出現首次設定（選 AI 服務 → 連線與測試 → 接上 Telegram → 完成）；使用者可以在那裡做，也可以關掉、由你帶著做，兩邊設定的是同一份。
   使用者說看到的是登入頁時（例如他在 `.env` 寫了 `LOCAL_AUTO_LOGIN=false`、在「設定 › 進階」關掉了「這台電腦免登入」，或是從別台裝置、經 Tailscale 打開）：
   - 有另一個已經登入的瀏覽器：在那邊打開「設定 › 收錄管道 ›「手機登入」」產生配對碼（QR code 或 8 碼，5 分鐘內有效、只能用一次），在登入頁輸入。
   - 沒有：請使用者自己打開 OmniKeep 資料夾裡的 `.env`，複製 `API_KEY=` 後面的值，貼到登入頁。你不要讀 `.env`、不要印出金鑰，也不要請使用者把金鑰貼到聊天。
5. MCP 要開新的 session 才會載入：請使用者開新的 session（Claude Code 也可以重新啟動），說「繼續設定 OmniKeep」，從第 1 步接著做。

## 更新（使用者說「更新 OmniKeep」「升級 OmniKeep」時）

不重跑訪談，設定與收藏都不會動。照順序做，任何一步失敗就停下來照錯誤訊息處理，不要跳過：

1. **找到安裝資料夾**：預設是家目錄的 `OmniKeep`；找不到就問使用者。以下指令都在那個資料夾執行，Python 一律用 `.venv` 裡的（Windows `.venv\Scripts\python.exe`，macOS、Linux `.venv/bin/python`）。
2. **檢查有沒有本機修改**：`git status --short`。除了沒追蹤的檔案以外還有修改時，先列給使用者看、問要怎麼處理，不要自己丟掉或 stash。
3. **看有什麼新東西**：`git fetch`，再用 `git log --oneline HEAD..origin/main` 列出新的 commit，用 3 到 5 行跟使用者說這次更新了什麼。沒有新 commit 就說已是最新版，到此為止。
4. **先備份資料庫**（服務可以繼續跑）：
   ```
   <.venv 的 python> -c "from app.backup import snapshot_archive; print(snapshot_archive('preupdate'))"
   ```
   印出的 zip 路徑告訴使用者。要還原時用 `python scripts/restore_backup.py <zip> --yes`（先停止服務，見 `docs/backup_restore.md`）。
5. **取得新版**：`git pull --ff-only`。失敗（通常是第 2 步的本機修改）就停下來問使用者。
6. **重跑安裝腳本**：Windows `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\install.ps1`，macOS、Linux `bash scripts/install.sh`。它會更新 Python 依賴、重建前端，並把新版的這份 Skill 註冊到 agent；`.env` 不會被覆寫。腳本回報「Skill 被改過、沒有覆蓋」時，告訴使用者，不要自己加 `--force`。
7. **重啟服務**：服務已經在跑時，安裝腳本不會重啟它，新版要重啟才會生效。資料庫結構的變更在服務啟動時自動套用，不用另外執行。
   - Windows：結束這個資料夾的 `run.py` 行程，再啟動排程讓它立刻重開：
     ```
     $dir = (Get-Location).Path
     Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like "*$dir*run.py*" } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
     Start-ScheduledTask -TaskName 'OmniKeep Watchdog'
     ```
   - Linux（systemd）：`systemctl --user restart omnikeep`
   - macOS（launchd）：`launchctl kickstart -k gui/$(id -u)/com.omnikeep.server`
   - 都沒有（用 nohup 啟動的）：結束 `run.py` 行程，再跑一次 `bash scripts/install.sh`，它會重新啟動。
8. **確認**：等到 `http://127.0.0.1:5000/health` 回 `healthy`（`.env` 改過 `PORT` 就用那個埠），最多等 90 秒；沒等到就看 `%LOCALAPPDATA%\OmniKeep\logs`（macOS、Linux 是 `~/.local/state/omnikeep/logs` 或 install.sh 印出的位置）的 `service-*.stderr.log`。用 `git log -1 --oneline` 告訴使用者現在的版本。
9. **提醒**：已經開著的 OmniKeep 分頁要重新整理，舊頁面可能一片空白。這次 Skill 也更新了，要開新的 session 才會讀到新版。

## 1. 掃描

呼叫 `omnikeep_scan`。用 3 到 5 行告訴使用者看到什麼：

- 硬體（CPU、RAM、GPU、VRAM），有沒有本機推論引擎（例如 Ollama）。
- OmniKeep 的版本與狀態，收藏幾筆。
- 已接的 AI 連線和健康狀況；`ai.needs_setup` 是 true 表示還沒接上任何 AI。
- Chrome、Edge 書籤與 GitHub 加星的專案：只有「有沒有、幾筆」，掃描不讀內容。
- 上次訪談的答案：有的話，下面每題的預設就帶入上次的答案，使用者只改想改的。
- OmniKit profile 的語言與背景：有就照用，不再問。

掃描看不到的兩件事，需要時直接問使用者：Telegram 有沒有綁定帳號、實驗功能有沒有開。掃描回傳的 `radar`、`radar_sources` 是探索的背景設定與探索來源數量；沒在帶探索就不用提。

同時依掃描結果和你對使用者的了解（記憶、這次與過去的對話、使用者的專案），起草「關於你」：2 到 4 句，職務、領域、常用技術。AI 分析工程與工具類的收藏時會參考它。不另外問使用者，預覽時讓使用者看、直接改。不要編造你不知道的事；資訊不夠就寫得保守一點，或乾脆不帶這個欄位。

**重新設定、或 OmniKeep 已經有資料時**：跳過「第一次成功」，只改使用者想改的那幾項，一樣要預覽再套用。

## 2. 題 1：接上 AI

OmniKeep 的摘要、重點分析與提問要用 AI。先跟使用者說清楚：**沒有 AI 也能收藏**，連結會存下標題、網址、封面與擷取到的正文，標成「尚未分析」，之後接上 AI 會自動補分析。所以這一題可以略過。

- 掃描到已經有可用的 AI 連線：只請使用者確認，直接到第 3 步。
- 否則呼叫 `omnikeep_list_provider_options` 拿選項卡片，照卡片內容說明每個選項：費用與限額、要不要信用卡、建議模型、申請連結、最後查證日期。

> 分析要用哪些 AI 服務？（可複選：第一個是主要，其餘依序當備援；也可以先略過）

掃描到可用的先勾好。使用者選了會拿資料訓練的免費方案，照卡片說明提醒一次，不要反覆勸。

使用者還沒有任何金鑰時，先介紹卡片標了 `no_signup` 的服務：不用註冊、現在就能試。限額、會不會拿資料訓練，一律照卡片當下的內容講清楚（這些條件常變，不要憑記憶講），問使用者要不要先接上，之後再加其他家當主要。不要替使用者勾選。不用金鑰的卡片，`omnikeep_open_settings(card=…)` 打開表單後直接按「儲存」即可。

每個選中、還沒接好的服務：

1. 說明申請步驟，打開卡片的申請頁。
2. 呼叫 `omnikeep_open_settings(card=<卡片 id>)` 取得設定頁連結。在執行 OmniKeep 的這台電腦上打開不用登入，使用者打開後會直接看到「設定 › AI」裡那張卡片的新增表單（已經接過的就是編輯表單），請他自己貼金鑰、按「儲存」。先出現登入頁時（免登入被關掉，或是從別台裝置打開），照第 0 步第 4 點處理，登入後再開一次連結。
3. 使用者說貼好了，再呼叫一次 `omnikeep_list_provider_options`，從 `current.connections` 找到新連線的 `id`，用 `omnikeep_test_provider(connection_id=<id>)` 測試。它會實際送一筆中文 JSON 小請求。
4. 失敗時照回傳的中文說明處理（金鑰錯、被停用、限流、模型不存在……）。一直失敗就先接下一個，不要卡住後面的步驟。

本機推論（例如 Ollama）不需要金鑰，測試通過就好。

都接好之後，把「主要在前、備援依序在後」的連線 id 放進答案的 `ai_order`，連同「關於你」（`about_you`）照「預覽與套用」一節預覽，使用者同意再套用。提問與探索預設跟著分析用的順序；使用者想分開設定，請他到「設定 › AI」的「用途與備援順序」調整。

使用者略過 AI：不帶 `ai_order`。有起草「關於你」就只預覽那一項；沒有就不用預覽，直接到第 3 步。

### 語意搜尋的向量模型（不用問，依硬體自動配）

掃描的 `embedding` 是依這台的顯示卡與記憶體挑好的本機向量模型（`recommended`，附理由 `why` 與下載大小 `download_gb`）。Ollama 有在跑、而且 `current` 不是 `recommended` 時：

1. `pulled` 是 false 就直接執行 `ollama pull <recommended>`（不用先問，下載完簡短回報大小）。
2. 在答案帶 `embedding_model: "<recommended>"`，跟其他設定一起預覽與套用。換了之後 OmniKeep 會在背景自己重建既有收藏的向量，期間語意搜尋暫時只用關鍵字。
3. 用一句話告訴使用者選了哪個模型、為什麼（照 `why`）。

沒有 Ollama：照「本機推論」的說明處理，先不帶 `embedding_model`。

## 3. 題 2：接上 Telegram

> 要接上 Telegram 嗎？接上之後，在 Telegram 把連結傳給你自己的機器人就會收藏。

1. 現在接（建議）
2. 先不用，我在網頁上貼連結 → 跳到第 4 步

MCP 工具不能代為設定機器人權杖，也不能產生配對連結：這兩件事都由使用者在設定頁自己做。你負責一步一步講清楚，並在中間幫忙測試。

1. **建立機器人**：請使用者在 Telegram 找 `@BotFather`，傳 `/newbot`。它會問名稱（name）和使用者名稱（username）。使用者名稱要 5 到 32 個字元、只能用英數字與底線、必須以 `bot` 結尾，之後不能改。BotFather 說這個使用者名稱不能用時（例如已經有人用了），換一個再試。完成後它會給一串權杖。提醒使用者：權杖不要貼到聊天。
2. **貼上權杖**：呼叫 `omnikeep_open_settings(tab="telegram")` 取得連結，使用者打開後會在「設定 › 收錄管道」的 Telegram 區塊。請他把權杖貼到「機器人權杖」，按「儲存」。
3. **測試**：使用者說存好了，呼叫 `omnikeep_test_provider(service="telegram")`。成功時回傳的訊息裡有機器人的使用者名稱，跟使用者核對是不是他剛建的那一個。失敗就照回傳的說明處理（通常是權杖沒複製完整）。
4. **配對帳號**：請使用者在同一個畫面的「已綁定的帳號」下面按「產生配對連結」，再按「在 Telegram 開啟」（要在手機上綁定就按「複製連結」，傳到手機開）。Telegram 打開和機器人的對話後，**要按「開始」**。配對連結 10 分鐘內有效、只能用一次。
5. **確認**：問使用者機器人有沒有回覆已綁定為 OmniKeep 擁有者。有，請他回網頁按「我綁好了」，「已綁定的帳號」會多一個編號。機器人回覆配對連結無效或已過期，就請他再按一次「產生配對連結」。你看不到綁定狀態，以使用者看到的為準。

完整說明在 `docs/telegram_bot.md`。使用者想接 LINE：見 `docs/line_bot.md`，一樣在「設定 › 收錄管道」自己貼（`omnikeep_open_settings(tab="line")`），貼完用 `omnikeep_test_provider(service="line")` 測試；LINE 還需要對外的 webhook，步驟比較多，不要放進首次設定的主線。

## 4. 題 3：丟第一個連結

> 給我一個你最近想留下來的連結，或直接在 Telegram 傳給你的機器人。

- **已經接上 Telegram**：請使用者在 Telegram 把連結傳給機器人。機器人會先回覆已收到，處理完換成一張有摘要的卡片。請使用者把看到的結果告訴你。
- **沒接 Telegram，或使用者把連結貼給你**：呼叫 `omnikeep_ingest(url=…)`，把標題、摘要、標籤貼回來。也告訴使用者：平常在 OmniKeep 按頂部的「新增」貼連結就可以。

看 `omnikeep_ingest` 回傳的 `analysed`：

- `analysed: true`：有 AI 分析。把結果給使用者看，接著問題 4。
- `analysed: false`：沒有接上 AI，這個連結只存了標題、網址與擷取到的原文，沒有摘要與分析（回傳的 `note` 也會這樣寫）。照實跟使用者說：**已經收藏，在清單上標示「尚未分析」；到「設定 › AI」接上 AI 連線後會在背景自動補分析，也可以打開那則收藏按「現在分析」。** 不要說成失敗，也不要自己編摘要。問使用者要不要現在回第 2 步接上 AI；不要的話跳過題 4。

工具回錯誤（例如免費層限流）：這個連結沒有存檔。照錯誤說明原因，改用備援的 AI 連線或稍後重試，不要卡住。

### 題 4：分析深度（看完有 AI 分析的結果才問）

> 這樣的分析可以嗎？

1. 剛好 → 不改（維持 `standard`）
2. 太長，精簡一點 → `concise`
3. 要更多技術細節 → `technical`
4. 要加結合自己背景的建議 → `actionable`

選了「剛好」以外的：照「預覽與套用」一節，用第二次的答案只帶 `analysis_depth`，預覽、同意後套用。下一篇開始用新寫法；想看效果，說「重新分析這篇」。

## 5. 收尾卡

用一張精簡的卡片收尾：

- 接了哪些 AI 連線、主要和備援的順序；沒接的話寫明「尚未接上 AI，收藏會標示尚未分析」。
- Telegram 有沒有接上；沒有的話寫在網頁按「新增」貼連結。
- 之後怎麼找：頂部的搜尋框，搜尋、提問、篩選都在裡面。
- 之後想改，直接跟 agent 說，只會改那一項。例如：「分析短一點」「換一個 AI 服務」。
- 想搬舊資料，說「匯入書籤」：可以搬 Chrome、Edge 書籤、GitHub 加星的專案、Pocket 匯出檔，用 `omnikeep_import`，預設只存標題與網址，不跑 AI。
- 探索是實驗功能，預設關閉。使用者有興趣再提：在 設定 › 實驗功能 開啟後，說「幫我設定探索」。

## 預覽與套用

寫入設定只有一條路：把答案寫成 JSON 交給 `omnikeep_preview_setup`，把回傳的 `changes` 原樣給使用者看，問「照這樣設定嗎？」；同意後呼叫 `omnikeep_apply_setup`，帶同一份答案與預覽回傳的確認碼（`confirm_code`）。確認碼對不上（答案改過，或設定在預覽後變了）時，重新預覽。

答案分兩次。**只帶這次要改的欄位**，沒帶的不會動。

第一次（`"stage": "first"`）。下面的範例把欄位都列出來；主線只會用到 `about_you` 和 `ai_order`，其餘是探索用的：

```json
{
  "stage": "first",
  "about_you": "產線設備資料蒐集與分析，常用 Python，想追工業 AI 與邊緣推論",
  "topics": ["工業 AI", "邊緣推論", "時序資料庫"],
  "seed_links": ["https://example.com/post"],
  "sources": [
    {"name": "Example Blog", "source_type": "rss", "url": "https://example.com/feed.xml", "pack": "工業 AI"}
  ],
  "ai_order": [2, 1]
}
```

| 欄位 | 用在哪 | 說明 |
|---|---|---|
| `about_you` | 主線 | 「關於你」，最多 1000 字；會存成一行 |
| `ai_order` | 主線 | 分析用的 AI 連線，數字 id（`omnikeep_list_provider_options` 回傳的 `current.connections` 裡的 `id`），主要在前、備援依序在後；不是服務名稱 |
| `interest_profile` | 探索 | 興趣描述，自由文字，最多 2000 字 |
| `topics` | 探索 | 關注主題，最多 8 個，每個最多 60 字；只記在上次的答案裡，下次訪談帶入 |
| `seed_links` | 探索 | 使用者給的種子連結，最多 3 個；一樣只記在上次的答案裡 |
| `sources` | 探索 | 探索來源，最多 40 個。每個有 `name`、`source_type`、`url`，選填 `pack`（主題包名稱）、`tier`（1 到 3，預設 2）。`source_type` 只能是 `youtube`、`github`、`rss`、`google_news`、`web_change` |
| `radar` | 探索 | `{"enabled": true 或 false, "interval_minutes": 30 到 1440}`。有帶 `sources` 而沒帶 `radar.enabled` 時，會自動啟用背景檢查 |

第二次（`"stage": "followup"`）只能帶 `analysis_depth` 和 `notifications`，至少要有一個；帶其他欄位會被拒絕。主線只用 `analysis_depth`（例如 `{"stage": "followup", "analysis_depth": "concise"}`），`notifications` 是探索的通知：

```json
{
  "stage": "followup",
  "analysis_depth": "concise",
  "notifications": {
    "mode": "daily_digest",
    "daily_digest_hour": 8,
    "channels": ["web_push", "telegram"]
  }
}
```

- `analysis_depth` 是 `standard`、`concise`、`technical` 或 `actionable`。
- `notifications.mode` 是 `silent`、`daily_digest` 或 `vip_alert`；選 `daily_digest` 一定要給 `daily_digest_hour`（0 到 23）。`channels` 可以放 `web_push`、`telegram`、`line`。
- 不認得的欄位會被拒絕，不會被忽略。

欄位名稱與格式以 `omnikeep_preview_setup` 的工具說明為準；它回「答案格式有誤」時，照訊息修正 JSON 再預覽，不要繞過它自己寫設定。預覽回傳的 `warnings`（例如選了 Telegram 通知但還沒設定機器人權杖）要一併告訴使用者。

## 實驗功能：探索（使用者開了才問）

探索會定時檢查使用者加的探索來源（RSS、YouTube 頻道、GitHub 專案、Google News 關鍵字、網頁變動），挑分數高的做 AI 分析，整理成精選。它是預設關閉的實驗功能，介面與行為還會改，而且會用 AI 額度。

**什麼時候才進這一節**：使用者說他開了探索、主動說想追某些來源（「多加幾個 X 的來源」「摘要改到晚上」「幫我設定探索」），或在收尾時表示有興趣。主線做完之前不要主動問這些題目。

**先確認開關**：MCP 工具看不到、也不能改實驗功能的開關。請使用者到 設定 › 實驗功能 打開「探索」（`omnikeep_open_settings(tab="labs")` 可以拿到連結）；沒開的話，介面上看不到探索清單與「探索設定」。注意：這個開關只決定介面上看不看得到；背景檢查由探索自己的「啟用」決定，套用探索來源時會一併啟用。探索要有 AI 連線才有意義，還沒接就先回第 2 步。

### 題 5：種子與關注主題

依掃描結果和你對使用者的了解，起草 3 到 5 個關注主題，每個一句話。

> 我猜你最近在追 X、Y、Z。要更準的話，給我 1 到 3 個最近覺得有價值的連結。

選項：

1. 猜得對，直接用
2. 我貼連結
3. 從你的書籤或 GitHub 加星的專案挑（掃描到書籤或 `gh` 已登入才列這個選項）
4. 改一下（自由輸入）：使用者的話取代你的猜測

- **貼了連結**：每個連結呼叫 `omnikeep_peek`（只解析，不跑 AI、不存），依內容修正主題。
- **從書籤或加星的專案挑**：只讀最近加入的 50 筆書籤的標題與資料夾名稱，或用 `gh api user/starred --paginate -q '.[].full_name'` 讀專案名稱。只用來推興趣，不寫進 OmniKeep，也不要把清單整份貼回聊天。

### 題 6：主題包（探索來源）

1. 依主題與種子提出候選來源。給網站首頁也可以，OmniKeep 會自己找 RSS；只給關鍵字會當成 Google News 查詢。
2. 全部交給 `omnikeep_check_sources` 驗證（每次最多 20 個），只留 `ok` 是 true 的。不要列出沒驗證過的來源。
3. 分成 2 到 4 包，每包 3 到 5 個來源。每個來源列出：
   - 推薦理由：對應哪個主題或種子。
   - 最近一篇的日期、每週篇數。
   - 最近 3 篇的標題。
4. 驗證後湊不滿 2 包：補上內建的範例來源當一包。

> 要追蹤哪幾包？（可複選）

最多 4 包（AskUserQuestion 每題最多 4 個選項）。一包都不勾：不帶 `sources`，探索的背景檢查維持原狀，這一節到此為止。

有勾：照「預覽與套用」一節用第一次的答案帶 `topics`、`seed_links`、`sources`（要的話加 `interest_profile`、`radar.interval_minutes`），預覽、同意後套用。預覽會列出新增的探索來源，以及背景檢查會被啟用（預設每 3 小時檢查一次）。通知先維持不通知，看完第一份精選再決定。

### 第一份精選

用 `omnikeep_run_radar` 檢查一次並產生第一份精選，把內容貼回來。它會讀每個啟用中的探索來源、分析其中幾篇，可能要幾分鐘，等的時候跟使用者說在做什麼。

### 題 7、題 8：精選送到哪、幾點（看完精選才問；Claude Code 可以一起問）

> 題 7：精選要送到哪？（可複選）

1. 網頁推播：在 OmniKeep 的「設定 › 通知」打開這台裝置的「推播通知」，瀏覽器問的時候按「允許」
2. Telegram：送給已綁定的帳號；還沒接就先做第 3 步
3. LINE：要先接上 LINE 官方帳號
4. 不用送，我自己打開看 → `notifications.mode` 用 `silent`，題 8 不用答

> 題 8：什麼時候送？

1. 每天早上 8 點
2. 中午 12 點
3. 晚上 9 點
4. 只送重要的 → `vip_alert`：分數到門檻（預設 4.0）的收藏才通知，不送每日精選

選每天幾點時告訴使用者：從那個小時起 3 小時內送出，電腦晚開機也會補送；內容是上一份精選之後分析完的探索收藏，最多 20 篇。

照「預覽與套用」一節用第二次的答案帶 `notifications`，預覽、同意後套用。

### 探索的收尾

在收尾卡多加：追蹤幾包、幾個探索來源；精選送到哪、幾點；之後可以說「多加幾個 X 的來源」「摘要改到晚上」；用逐則篩選一則一則決定要不要留，推薦會越來越準。

## 之後的單項修改

使用者只想改一項時（例如「分析短一點」）：不重跑整套訪談。先 `omnikeep_scan` 看現況，只問那一項，照「預覽與套用」一節預覽、同意後套用。

- 「換一個 AI 服務」「加一個備援」：照第 2 步接好新的連線，用 `ai_order` 套用新的順序。
- 「接上 Telegram」：照第 3 步。
- 「匯入書籤」：問要匯入哪一種，用 `omnikeep_import`；匯入前說明筆數，同意才做。
  - 瀏覽器書籤：`kind="bookmarks"`，加 `browser="chrome"` 或 `"edge"`（讀這台電腦的書籤），或加 `path`（書籤匯出檔；Pocket 的 CSV 匯出檔也走這個）。
  - GitHub 加星的專案：`kind="github_stars"`（要先 `gh auth login`）。
  - OPML：`kind="opml"` 加 `path`。OPML 裡的訂閱會變成探索來源，屬於實驗功能，先照上一節確認使用者開了探索。
  - 預設只存標題與網址。`enqueue_ai=true` 會把每個連結都排進 AI 分析、會用額度，先問過使用者。
- 「多加幾個 X 的來源」「摘要改到晚上」：這是探索，照「實驗功能：探索」一節，只列新的來源、只改那一項。

## MCP 工具一覽

| 工具 | 用途 | 會寫入嗎 |
|---|---|---|
| `omnikeep_scan` | 硬體、狀態、已接的 AI 連線、上次答案、OmniKit profile、書籤與 GitHub 加星的專案筆數 | 否 |
| `omnikeep_list_provider_options` | AI 服務的選項卡片與目前的 AI 連線 | 否 |
| `omnikeep_open_settings` | 設定頁的連結。`card` 指向某張 AI 卡片；`tab` 指向分頁（`ai`、`telegram`、`line`、`push`、`labs` 等） | 否 |
| `omnikeep_test_provider` | 用已存的金鑰或權杖送一筆小請求。`connection_id` 測一條 AI 連線；`service` 測某個用途（`analysis`、`brain`、`radar`、`embeddings`、`video`）的第一條連線，或 `telegram`、`line`、`github` | 否 |
| `omnikeep_preview_setup` | 驗證答案 JSON，回傳設定差異與確認碼 | 否 |
| `omnikeep_apply_setup` | 套用設定，要帶確認碼 | 是 |
| `omnikeep_ingest` | 收藏一個網址並分析；回傳的 `analysed` 是 false 表示沒接 AI、只存了原文 | 是（新增一筆收藏） |
| `omnikeep_import` | 匯入書籤、GitHub 加星的專案、Pocket 匯出檔、OPML | 是 |
| `omnikeep_peek` | 解析一個網址，不跑 AI、不存（探索的種子連結用） | 否 |
| `omnikeep_check_sources` | 驗證候選的探索來源，首頁自動找 RSS | 否 |
| `omnikeep_run_radar` | 探索檢查一次並產生精選 | 是 |

工具回錯誤時，照錯誤訊息處理並跟使用者說明；不要改用直接讀寫資料庫或設定檔繞過。
