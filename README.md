# OmniKeep

<div align="center">

**Self-hosted link keeper: send a link, it reads it for you, find it or ask about it later.**<br>
**在 Telegram 丟連結，OmniKeep 幫你讀完，之後找得到。**

[![Python 3.12+](https://img.shields.io/badge/Python-3.12%2B-3776AB?logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115%2B-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Vue 3](https://img.shields.io/badge/Vue.js-3.5%2B-4FC08D?logo=vuedotjs&logoColor=white)](https://vuejs.org)
[![Tailwind CSS](https://img.shields.io/badge/Tailwind_CSS-v4-06B6D4?logo=tailwindcss&logoColor=white)](https://tailwindcss.com)
[![SQLite WAL](https://img.shields.io/badge/SQLite-WAL%20%2B%20FTS5-003B57?logo=sqlite&logoColor=white)](https://sqlite.org)
[![Docker Ready](https://img.shields.io/badge/Docker-Ready-2496ED?logo=docker&logoColor=white)](Dockerfile)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

[三分鐘開始用](#三分鐘開始用) •
[它能做什麼](#它能做什麼) •
[收錄管道](#收錄管道) •
[AI 連線](#ai-連線) •
[登入與其他裝置](#登入與其他裝置) •
[安全注意事項](#安全注意事項) •
[進階](#進階安裝細節與其他裝法) •
[環境變數](#環境變數說明)

</div>

---

看到值得留的連結，收了常常就沒再看，要用的時候也找不到。OmniKeep 主要做一件事：

1. **丟連結**：在 Telegram 把連結傳給自己的機器人。
2. **幫你讀完**：網頁、影片（YouTube、Bilibili、短影音）、社群貼文（Threads、X）都會抓下內容，交給你接上的 AI 寫出摘要與重點。
3. **找得到**：之後用關鍵字或語意搜尋，或直接在搜尋框提問，回答會附上引用的收藏。

資料存在你自己的電腦上（SQLite），不放在別人的雲端。

---

## 三分鐘開始用

### 1. 安裝

對 Claude Code、Codex 或 Antigravity 說：

> 幫我安裝 OmniKeep：https://github.com/b40609/OmniKeep

agent 會照 [`skills/omnikeep-setup`](skills/omnikeep-setup/SKILL.md) 安裝，再帶你接上 AI、接上 Telegram、丟第一個連結。金鑰與機器人權杖一律在 OmniKeep 的設定頁自己貼，不經過聊天。

也可以自己執行安裝腳本：

```powershell
# Windows（Windows PowerShell 5.1 或 PowerShell 7）
& ([scriptblock]::Create((irm https://raw.githubusercontent.com/b40609/OmniKeep/main/scripts/install.ps1).TrimStart([char]0xFEFF)))
```

```bash
# macOS、Linux
curl -fsSL https://raw.githubusercontent.com/b40609/OmniKeep/main/scripts/install.sh | bash
```

需要 git、Python 3.12+、Node.js 20.19+ 或 22.12+。腳本做了什麼、怎麼移除，見[安裝細節](#安裝腳本做了什麼)。

### 2. 打開

在這台電腦用瀏覽器打開 `http://127.0.0.1:5000`，會直接進主畫面，不用登入。

第一次打開會出現首次設定，共四步：選 AI 服務 → 連線與測試 → 接上 Telegram → 完成。AI 與 Telegram 都可以略過，之後再到「設定」補。服務清單預設只列不用註冊或不用金鑰的幾個，其餘按「顯示全部」。

**還沒接上 AI 也能收藏。** 這時貼進來的連結會存下標題、網址、封面與擷取到的正文，卡片標示「尚未分析」。之後到「設定 › AI」接上 AI 連線，會在背景自動補分析；也可以打開那則收藏按「現在分析」。

### 3. 接上 Telegram

1. **建立機器人**：在 Telegram 找 `@BotFather`，傳 `/newbot`，照提示取名稱和使用者名稱（要以 `bot` 結尾）。完成後它會給你一串權杖。
2. **貼上權杖**：OmniKeep 右上角頭像選單 ›「設定」› 收錄管道 › Telegram，貼到「機器人權杖」，按「儲存」。
3. **配對你的帳號**：同一個畫面按「產生配對連結」，用你的 Telegram 開啟連結並按「開始」。機器人回覆已綁定就完成了。

每一步的畫面、常見問題與指令，見 [docs/telegram_bot.md](docs/telegram_bot.md)。

### 4. 丟第一個連結

- 在 Telegram 把連結傳給機器人，處理完它會回一張有摘要的卡片。
- 或在 OmniKeep 按頂部的「新增」（快捷鍵 `N`），把連結貼上。

之後要找，用頂部的搜尋框：搜尋、提問、篩選都在這一個框。

---

## 它能做什麼

### 1. 丟連結就收錄
- **Telegram 機器人（主要入口）**：把連結傳給自己的私人機器人，收錄後回覆摘要卡。用一次性配對連結綁定帳號，設定見 [docs/telegram_bot.md](docs/telegram_bot.md)。
- **LINE 官方帳號**：同樣是轉發連結就收錄，見 [docs/line_bot.md](docs/line_bot.md)。
- **網頁上的「新增」**：一個面板，貼連結、寫筆記、把書籤檔拖進來都從這裡。
- **手機**：iOS 原生捷徑（Share Sheet）一鍵收錄，或把 PWA 加到主畫面。
- **外部 agent（MCP）**：同一台電腦用 stdio，別台電腦用 Streamable HTTP（`/mcp-http`，經 Tailscale）；舊的 SSE 端點還保留。安裝腳本會自動註冊到 Claude Code、Codex、Antigravity，見 [docs/mcp_integration.md](docs/mcp_integration.md)。
- **REST API**：有 Swagger 文件，方便腳本與自動化流程串接。

### 2. 網頁、影片、社群貼文都讀得懂
- **YouTube**：接上 Google Gemini 時直接解析影片，主機不用下載。沒有 Gemini 時讀字幕，沒字幕就用本機語音轉錄（中文用台灣華語微調的 Breeze-ASR-25），逐字稿帶 `[MM:SS]` 時間與章節；選裝畫面 OCR 後，再補上投影片、圖表上旁白沒講到的字（見 [選用功能](docs/optional_features.md)）。
- **Bilibili 長影片**：先用官方 CC／AI 逐字稿 JSON（約 0.2 秒），沒有時改抓 DASH 音訊，交給本機 `faster-whisper` 轉錄（GPU CUDA／CPU 多執行緒自動切換；選用安裝，見 [選用功能](docs/optional_features.md)）。
- **社群短影音（Reels／TikTok／Shorts）**：關鍵幀 OCR 加語音轉錄（本機或雲端），兩邊的文字合併後再分析。
- **長文與永久快照**：用 trafilatura 清掉廣告與雜訊，並存一份 HTML 快照；原網頁失效後仍然看得到。

### 3. 先看摘要，需要再看重點分析
- **摘要**：卡片上是一個說重點的標題、一兩句白話說明，以及標籤。
- **重點分析**：打開收藏可以看完整的分析（架構、規格、程式碼細節），以及 Markdown 原文閱讀模式。

### 4. 找得到：搜尋與提問
- **全文檢索**：SQLite FTS5，用 trigram 分詞，中文句子裡的子字串也找得到；不到三個字的詞改用 LIKE 比對。
- **語意搜尋**：sqlite-vec 向量索引，和全文檢索的結果用 RRF 合併，關鍵字對不上時也找得到相關內容（索引的檢查與重建見 [向量索引](docs/vector_index.md)）。
- **提問**：直接對收藏的內容提問。先檢索相關的收藏，再交給 AI 回答，回答裡附上引用的來源編號。

### 5. 資料在自己手上，每天自動備份
- **SQLite WAL**：資料都在本機的一個 SQLite 資料庫（WAL 模式），全文索引是 trigram 分詞的 FTS5，向量索引是 sqlite-vec。
- **自動備份**：每天自動備份一次，支援本機多份輪替、雲端同步（rclone：Google Drive／Dropbox／S3）以及私有 Git 儲存庫自動提交。資料庫與 HTML 快照一起備份，用 `scripts/restore_backup.py` 還原，見 [備份與還原](docs/backup_restore.md)。

### 6. 實驗功能：探索與專案監看
這些功能還在、可以開，但介面與行為還會改。新安裝預設關閉，在 設定 › 實驗功能 開啟。
- **探索**：定時檢查你加的探索來源（RSS、YouTube 頻道、GitHub 專案、Google News 關鍵字、網頁變動），每輪只挑分數最高的幾篇做 AI 分析，再整理成精選。開啟實驗功能後，在「探索設定」的「排程與通知」分頁啟用並設定間隔。
- **通知**：預設不通知；可以改成每日精選，或只在分數到門檻時通知。
- **逐則篩選**：一則一則決定要不要留。喜歡、不喜歡會調整標籤的權重（14 天半衰期），影響之後的排序。
- **Dream Pass**：依最近的互動提議更新興趣描述，你同意才套用。目前只能手動觸發（Telegram 的 `/dreampass`），沒有排程，不會自動發生。
- **專案監看**：掃描你指定的本機資料夾，產生風險與改進的建議，見 [專案監看](docs/watch_proposals.md)。
- **每日回顧**：每天挑幾則未讀和值得重看的舊收藏，一則一則看過。

和常見做法的差別：
- **稍後讀服務（Pocket、Omnivore）**：服務可能終止，資料綁在廠商的雲端，而且多半只保存文字。
- **筆記工具（Notion、Obsidian）**：收錄流程比較繁瑣，影片（YouTube、Bilibili、Reels）不會自動整理成文字與重點。

---

## 收錄管道

| 管道 | 適用環境 | 說明 | 設定文件 |
| :--- | :--- | :--- | :--- |
| **Telegram 機器人（主要入口）** | 手機、電腦 | 把網址傳給私人機器人，收錄後回覆摘要卡 | [docs/telegram_bot.md](docs/telegram_bot.md) |
| **LINE 官方帳號** | LINE App | 轉發網址或長文，回傳 Flex 訊息卡 | [docs/line_bot.md](docs/line_bot.md) |
| **iOS 原生捷徑** | iPhone／iPad | 從分享表單一鍵送到後端，背景處理 | [docs/ios_shortcut.md](docs/ios_shortcut.md) |
| **PWA** | iOS／Android | 加到主畫面，獨立視窗執行 | [docs/ios_shortcut.md](docs/ios_shortcut.md) |
| **MCP（Model Context Protocol）** | Claude Code、Codex、Antigravity 等 | 讓外部 agent 檢索 OmniKeep、把結論寫回來 | [docs/mcp_integration.md](docs/mcp_integration.md) |

Telegram、LINE、手機登入、社群平台登入、匯入書籤、GitHub 權杖，都在「設定 › 收錄管道」。

---

## AI 連線

AI 連線在「設定 › AI」管理，分成兩層：

- **AI 連線**：一個服務的位址、金鑰與模型。按「新增連線」從目錄卡片挑，卡片上有費用與限額、建議模型、申請連結與最後查證日期（資料在 `app/provider_catalog.py`）；也可以自己填任何 OpenAI 相容的 `/v1` 位址。
- **用途與備援順序**：分析、提問、探索、語意搜尋、影片各排一串連線，第一條是主要，其餘依序備援。

支援三種協定：OpenAI 相容（`/v1`）、Google Gemini、本機 Ollama。儲存後立即生效，不必重啟。

模型名稱、免費額度變動很快，這裡不列，以設定頁目錄卡片上的內容為準。`.env` 的 `OPENAI_*`、`GEMINI_*` 是舊設定的相容，見下面的環境變數表。

- App 內輸入的金鑰會加密後才存進資料庫，之後只顯示末四碼；解密用的主金鑰是資料庫旁的 `omnikeep.secret.key`（不會進入備份，搬機時要一起帶走；遺失只需重新輸入金鑰）。
- 優先順序：App 內設定 > `.env` > 預設值。已經寫在 `.env` 的值仍然有效，可在「設定 › 進階」的「從 .env 匯入」一次匯入 App。
- `HOST`、`PORT`、`DATABASE_PATH`、`API_KEY` 在服務啟動前就要用到或負責保護登入，仍只能寫在 `.env`。

---

## 介面與鍵盤快捷鍵

主畫面頂部只有一個搜尋框（搜尋、提問、篩選與動作都在裡面）和一顆「新增」。設定在右上角頭像選單 ›「設定」，左側分成：一般、收錄管道、AI、通知、資料與備份、進階、實驗功能。

快捷鍵（在收藏清單按 `?` 可以看完整清單）：

| 按鍵 | 動作 |
| :--- | :--- |
| `J`／`↓`、`K`／`↑` | 下一則、上一則 |
| `Enter` | 開啟選取的收藏 |
| `Esc` | 關閉面板或對話框 |
| `/` 或 `Ctrl/Cmd+K` | 聚焦搜尋框：搜尋、篩選與動作 |
| `B` | 同一個搜尋框，切到提問 |
| `Ctrl/Cmd+B` | 展開或收合側邊欄 |
| `E` | 封存／取消封存 |
| `S` | 加星／取消加星 |
| `+`／`-` | 多推薦／少推薦這類內容 |
| `N` | 新增連結、筆記或書籤檔 |
| `?` | 鍵盤快捷鍵 |

開啟對應的實驗功能後才有的按鍵：`R` 探索設定、`D` 逐則篩選（探索）、`Shift+D` 每日回顧。

---

## 登入與其他裝置

- **這台電腦**：在執行 OmniKeep 的電腦上用瀏覽器打開 `http://127.0.0.1:5000`，直接進主畫面，不用輸入存取金鑰。
- **其他裝置**（手機、別台電腦，經 Tailscale 或任何反向代理連進來）：要輸入存取金鑰，或一次性配對碼。配對碼在已經登入的 OmniKeep 的「設定 › 收錄管道 ›「手機登入」」產生（QR code 或 8 碼，5 分鐘內有效、只能用一次）。連線方式見 [Tailscale 部署](docs/tailscale_pwa_deploy.md)。
- **關掉免登入**：「設定 › 進階 ›「這台電腦免登入」」預設是開的。關掉之後，這台電腦也要輸入存取金鑰或配對碼。
- **舊安裝**：`.env` 裡已經寫了 `LOCAL_AUTO_LOGIN=false` 的，行為不變，這台電腦一樣要登入。
- **Docker**：一律要存取金鑰，因為容器裡看到的連線來源不是本機位址。
- **存取金鑰**：安裝時隨機產生，存在 `.env` 的 `API_KEY`，給其他裝置、REST API 與遠端 MCP 用。只在這台電腦上用的話，不需要知道它。規則：至少 32 個字元，而且至少 12 種不同字元。

---

## 安全注意事項

- **預設只綁本機位址**：`HOST=127.0.0.1`（Docker 是 `BIND_ADDRESS=127.0.0.1`），別台裝置連不到。
- **這台電腦免登入的意思**：在執行 OmniKeep 的電腦上打開不用存取金鑰。同一台電腦上的其他程式、其他使用這台電腦的人，也一樣能使用 OmniKeep。多人共用的電腦，請到「設定 › 進階」關掉「這台電腦免登入」。
- **要給其他裝置用**：走 Tailscale 這類私有網路，見 [Tailscale 部署](docs/tailscale_pwa_deploy.md)。從其他裝置連進來一律要存取金鑰或配對碼。
- **不要把整個服務公開到網際網路**：不要把 `HOST` 改成 `0.0.0.0` 後直接對外，也不要用 `tailscale funnel 5000` 這類把整個服務公開的指令。LINE 需要公開的 webhook 時，只公開那一條路徑，見 [docs/line_bot.md](docs/line_bot.md)。
- **存取金鑰外洩時**：執行 `python scripts/rotate_api_key.py` 換一把，重啟服務，再更新各個 client。
- **不要提交到 Git**：`.env`、`omnikeep.secret.key`、`cookies.txt`、資料庫。`.gitignore` 已經排除這些檔案。

---

## 進階：安裝細節與其他裝法

這一節之後都是進階內容。照「三分鐘開始用」裝好、只在這台電腦上用的話，可以不用看。

三種裝法，建議用第一種：

| 裝法 | 適合 | agent 帶著設定 |
| :--- | :--- | :--- |
| [一行安裝](#1-安裝) | 大部分的人 | 有 |
| [方式 A：Docker](#方式-a-docker) | 已經在用 Docker 的主機 | 沒有，要在網頁的設定頁自己設定 |
| [方式 B：本地環境](#方式-b-本地環境) | 想自己一步一步裝 | 裝完再執行 `scripts/register_agents.py` 就有 |

### 安裝腳本做了什麼

這是什麼：一行安裝實際執行的步驟。想知道它動了電腦上哪些東西、或安裝失敗要查原因時才需要看。

Windows 的一行指令裡有一段 `.TrimStart([char]0xFEFF)`：`install.ps1` 開頭有 UTF-8 BOM，要先去掉；少了這一段，PowerShell 會解析失敗。

Claude Code 使用者也可以先裝 plugin，取得設定 Skill 後再說「幫我安裝 OmniKeep」：

```bash
claude plugin marketplace add b40609/OmniKeep
claude plugin install omnikeep@omnikeep
```

安裝腳本可以重複執行，已完成的步驟會略過：

1. 檢查 git、Python 3.12+、Node.js 20.19+ 或 22.12+（Windows 加 `-InstallPrereqs` 會用 winget 補裝）。
2. clone 到 `~/OmniKeep`（從 repo 內執行時就用這個 repo），建立 `.venv` 並安裝依賴。
3. 沒有 `.env` 時用 `scripts/bootstrap_env.py` 產生，存取金鑰隨機產生、不會顯示。只在這台電腦上用的話，不需要知道這把金鑰。
4. 建置前端（`npm ci`、`npm run build`），啟動服務並設定自動重啟：Windows 是排程工作「OmniKeep Watchdog」（每分鐘檢查、登入時啟動），Linux 是 systemd 使用者服務，macOS 是 launchd。健康檢查用的埠讀 `.env` 的 `PORT`，沒有設定就是 5000。
5. 用 `scripts/register_agents.py` 把 stdio MCP 與 `omnikeep-setup` Skill 註冊到這台電腦的 Claude Code（`claude mcp add -s user`）、Codex（`codex mcp add`）、Antigravity（`~/.gemini/config/mcp_config.json`）。agent 的設定檔裡不放任何金鑰；已經有別的 `omnikeep` 設定時不覆蓋，要加 `--force`。

想先看會做什麼：Windows 加 `-DryRun`，macOS、Linux 加 `--dry-run`；`python scripts/register_agents.py --dry-run` 只看註冊的部分。

Windows 上的 `run.bat` 只做一件事：呼叫 `scripts\install.ps1`。所以在 OmniKeep 資料夾裡按兩下 `run.bat`，和重跑一次安裝腳本一樣。

裝好之後想讓 agent 帶著設定：開一個新的 agent session，說「幫我設定 OmniKeep」。

### 移除自動啟動，或停止服務

這是什麼：安裝腳本設定的自動重啟。想暫時停用 OmniKeep、或要解除安裝時才需要。

Windows（PowerShell）：

```powershell
Unregister-ScheduledTask -TaskName 'OmniKeep Watchdog' -Confirm:$false
```

這只會移除排程工作，之後不再自動啟動與重啟；正在執行的服務不會因此停止。要連服務一起停，還要結束正在執行 `run.py` 的 python 行程。先移除排程工作再結束行程，否則一分鐘內又會被重新啟動。找出行程：

```powershell
Get-CimInstance Win32_Process -Filter "Name like 'python%'" | Where-Object CommandLine -like '*run.py*' | Select-Object ProcessId, CommandLine
```

確認是 OmniKeep 之後，用 `Stop-Process -Id <ProcessId>` 結束，或在工作管理員裡結束。

Linux：`systemctl --user disable --now omnikeep.service`。macOS：`launchctl unload -w ~/Library/LaunchAgents/com.omnikeep.server.plist`。

要重新設定自動啟動，重跑一次安裝腳本就好。資料庫、`.env` 與主金鑰檔都不會因為上面的指令被刪除。

### 方式 A Docker

這是什麼：用容器執行 OmniKeep。主機已經用 Docker 管理服務時才需要；一般桌機用一行安裝比較省事。

**Docker 目前不支援「agent 帶著設定」的流程。** 映像裡只有服務本身，沒有 `mcp_server.py`、`skills/` 與 `scripts/register_agents.py`（見 `Dockerfile`），所以不會註冊 MCP 與設定 Skill。AI 連線、Telegram 等都要在網頁的設定頁自己設定。想讓 agent 帶著設定，請用一行安裝。

一般書籤收藏、匯入與關鍵字搜尋不需要 GPU 或付費 AI API：

```bash
# 1. 複製專案
git clone https://github.com/b40609/OmniKeep.git
cd OmniKeep

# 2. 產生首次設定檔與隨機的 API_KEY（需有 Python 3；已經有 .env 時不會覆寫）
python scripts/bootstrap_env.py

# 3. 檢查 Compose 設定並建置、啟動
docker compose config -q
docker compose up -d --build
```

如果主機**只安裝 Docker、沒有 Python**：Linux／macOS 先執行 `cp .env.example .env`；Windows PowerShell 改用 `Copy-Item .env.example .env`。接著用文字編輯器在 `.env` 的 `API_KEY=` 後填入自己用安全方式產生的隨機存取金鑰（至少 32 個字元，而且至少 12 種不同字元），再執行第 3 步。**不要將 `.env` 提交到 Git 或公開金鑰。**

開啟 `http://localhost:5000`，用 `.env` 裡的 `API_KEY` 登入。Docker 一律要存取金鑰：容器裡看到的連線來源不是本機位址，「這台電腦免登入」不會生效。Docker 預設只在主機本機監聽（`BIND_ADDRESS=127.0.0.1`）。需要手機或其他電腦連線時，才將 `BIND_ADDRESS` 改成適當的受保護網路位址；請勿直接暴露至公網。探索（實驗功能）預設關閉；新安裝附了幾個停用的探索來源範例，要用再自己挑選並啟用。分類可以自訂。

**首次體驗（不需 AI 金鑰）**：登入後按頂部的「新增」，貼上連結，或把瀏覽器匯出的 HTML 書籤檔拖進去（或按「選擇檔案」），匯入方式選「只匯入，不分析」，接著用頂部的搜尋框查找內容。還沒接上 AI 時，貼進來的連結照樣會收藏，卡片標示「尚未分析」。要讓 AI 寫摘要，或匯入時選「匯入後交給 AI 分析」，再接上 AI：右上角頭像選單 ›「設定」› AI，按「新增連線」並儲存，立即生效，不必重啟服務，先前「尚未分析」的收藏會自動補分析。Docker 版資料與備份保存在 `omnikeep_data` volume，更新容器時請保留該 volume。

Docker 映像預設不含本機語音轉錄，也沒有 Chrome；要加入本機語音轉錄，在 `.env` 設定 `LOCAL_STT=true` 後重新建置。見 [選用功能](docs/optional_features.md)。

**手機與捷徑**：手機以網頁方式連線可使用受保護的區網／VPN；PWA 安裝與離線快取通常需要 HTTPS。請參考 [iOS／Android 設定指南](docs/ios_shortcut.md)。每位使用者須自行設定端點與存取金鑰，且應透過 `X-API-Key` 標頭傳送。

### 方式 B 本地環境

這是什麼：不用安裝腳本，自己一步一步建立 Python 與 Node.js 環境。想完全掌握每個步驟、或要改程式時才需要。

#### 1. 安裝環境與依賴
- **後端**：Python 3.12+（CI 測試 3.12 與 3.14）
- **前端建置**：Node.js 20.19+ 或 22.12+（前端用 Vite 8；Python 本地部署也必須建置一次）

```bash
# 建立並啟動 Python 虛擬環境
python -m venv .venv

# Windows:
.venv\Scripts\activate
# Linux / macOS:
source .venv/bin/activate

# 安裝 Python 依賴（Windows 會一併安裝自動化 Chrome 登入用的 playwright）
pip install -r requirements.txt

# 選用：本機語音轉錄（YouTube、Reels、Bilibili、X、Threads），安裝後約多 213 MB
pip install -r requirements-stt.txt
# 選用：長影片的畫面文字（OCR），安裝後約多 165 MB
pip install -r requirements-ocr.txt
```

各選用功能的用途、大小與 GPU 設定見 [選用功能](docs/optional_features.md)。

#### 2. 建立首次設定並建置前端
```bash
python scripts/bootstrap_env.py
cd frontend
npm ci
npm run build
cd ..
```
`scripts/bootstrap_env.py` 從 `.env.example` 複製出 `.env`，並隨機產生 `API_KEY`；`.env` 已經存在時不會覆寫。前端建置產物 `static/dist/` 不納入 Git。

**首次使用不必先申請 AI 金鑰。** 沒接上 AI 時連結照樣能收藏，標示「尚未分析」。要啟用 AI 摘要時，打開右上角頭像選單 ›「設定」› AI，按「新增連線」（位址、金鑰與模型），測試後儲存即可，立即生效、不必重新啟動。Telegram、LINE、GitHub 權杖在「設定 › 收錄管道」，備份在「設定 › 資料與備份」。

這台電腦要不要免登入，在「設定 › 進階」的「這台電腦免登入」切換，見[登入與其他裝置](#登入與其他裝置)。

> [!TIP]
> `scripts/bootstrap_env.py` 是第一次產生 `.env` 用的。已經有 `.env`、想換掉裡面的存取金鑰，用另一支輪替腳本；這會使舊金鑰失效，請同步更新所有 client：
> ```bash
> python scripts/rotate_api_key.py
> ```

#### 3. 啟動服務
```bash
python run.py
```
- **網頁介面**：在這台電腦用瀏覽器打開 `http://127.0.0.1:5000`，直接進主畫面，不用輸入存取金鑰。服務預設只綁定 `HOST=127.0.0.1`；要給其他裝置用，見[安全注意事項](#安全注意事項)。
- **從其他裝置登入**：輸入存取金鑰或配對碼，見[登入與其他裝置](#登入與其他裝置)。登入頁的「記住金鑰」會把金鑰存在那個瀏覽器，請只在自己的裝置勾選。
- **REST API 文件**：`http://localhost:5000/docs`（需帶入 `Authorization: Bearer <API_KEY>`）。

### 從別台裝置連線：Tailscale 與反向代理

這是什麼：讓手機、平板或別台電腦連到這台主機上的 OmniKeep。只在這台電腦上用就不需要。

建議走 Tailscale 這類私有網路，用 `tailscale serve` 提供 HTTPS，步驟見 [Tailscale 部署](docs/tailscale_pwa_deploy.md)。經 Tailscale 或任何反向代理進來的連線一律要存取金鑰或配對碼，不會套用「這台電腦免登入」。不要把整個服務公開到網際網路，見[安全注意事項](#安全注意事項)。

### 讓外部 agent 使用：MCP

這是什麼：讓 Claude Code、Codex、Antigravity 這類 agent 查詢你的收藏、把結論寫回來。不用 agent 就不需要。

安裝腳本已經把同一台電腦的 stdio MCP 註冊好。要手動設定，或從別台電腦連（Streamable HTTP：`/mcp-http`），見 [MCP 整合](docs/mcp_integration.md)。

---

## 系統架構

這是什麼：資料從進來到存好的流程。想了解內部怎麼運作、或要改程式時參考。

```
                          [收錄入口]
   iOS 原生捷徑    Android PWA    Telegram / LINE 機器人    IDE Agent (Cursor/Claude)
        │              │                  │                         │
        └──────────────┴─────────┬────────┴─────────────────────────┘
                                 ▼
                         [FastAPI 統一入口]
           (Bearer Token 驗證 / 限流保護 / 非同步任務排程)
                                 │
           ┌─────────────────────┼─────────────────────┐
           ▼                     ▼                     ▼
      [長影片管線]          [社群短影音管線]          [長文擷取管線]
  • YouTube (Gemini)    • Instagram / TikTok   • Trafilatura 正文清洗
  • Bilibili (CC/DASH)  • 關鍵幀 OCR / Whisper  • HTML 快照
           │                     │                     │
           └─────────────────────┼─────────────────────┘
                                 ▼
                     [AI 連線：依用途與備援順序]
     (OpenAI / DeepSeek / Google Gemini / 本機 Ollama / Groq)
                                 │
                                 ▼
                        [本機儲存與檢索]
        SQLite (WAL Mode) ── FTS5 全文檢索 ── sqlite-vec 向量庫
                                 │
                                 ▼
                  [定時備份: Local / Rclone / Git]
```

前端：**Vite 8 + Vue 3（Composition API）+ Tailwind CSS v4 + Reka UI（shadcn-vue）**。建置產物輸出到 `static/dist/`，由 FastAPI 直接提供。

---

## 環境變數說明

這是什麼：可以寫在 `.env` 的設定。大部分設定不用寫 `.env`；標示「App」的可以在網頁的「設定」頁修改，App 內儲存的值優先於 `.env`。

AI 連線已經改在「設定 › AI」用「AI 連線 + 用途與備援順序」管理。下表的 `PRIMARY_LLM_PROVIDER`、`OPENAI_*`、`PRIMARY_MODEL`、`GEMINI_*` 只是舊設定的相容：已經寫在 `.env` 的會被帶進連線清單，新安裝不用填。

| 變數名稱 | 預設值 | 說明 |
| :--- | :--- | :--- |
| `API_KEY` | *(安裝時隨機產生)* | 存取金鑰（至少 32 個字元，而且至少 12 種不同字元）。其他裝置登入、REST API 與遠端 MCP 用；在這台電腦上用瀏覽器不需要它 |
| `HOST` | `127.0.0.1` | 服務綁定的位址。預設只綁本機；不要改成 `0.0.0.0` 直接對外，其他裝置請走 Tailscale（見[安全注意事項](#安全注意事項)） |
| `PORT` | `5000` | 服務的埠 |
| `BIND_ADDRESS` | `127.0.0.1`（新安裝範例） | Docker 主機監聽位址；要允許區網存取需明確設定 |
| `LOCAL_STT` | `false` | Docker 建置時加入本機語音轉錄，見 [選用功能](docs/optional_features.md) |
| `LOCAL_AUTO_LOGIN` | *(新安裝不用設)* | 這台電腦免登入的舊設定。新安裝預設免登入，由「設定 › 進階」的「這台電腦免登入」開關控制；`.env` 裡已經寫 `false` 的舊安裝行為不變，這台電腦一樣要登入。Docker 一律要存取金鑰 |
| `MCP_ALLOWED_HOSTS` | *(無)* | 遠端 MCP（`/mcp-http`）額外接受的主機名稱，逗號分隔；loopback 與啟動時找到的 Tailscale 名稱不用寫，見 [MCP 整合](docs/mcp_integration.md) |
| `PRIMARY_LLM_PROVIDER` | `openai_compatible` | App｜舊設定相容。主要推理 Provider 類型（`openai_compatible` 或 `gemini`） |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | App｜舊設定相容。OpenAI 相容端點 Base URL |
| `OPENAI_API_KEY` | *(無)* | App｜舊設定相容。對應端點的金鑰 |
| `PRIMARY_MODEL` | `gpt-4o-mini` | App｜舊設定相容。主要分析與摘要所使用的模型名稱 |
| `GEMINI_API_KEYS` | *(無)* | App｜舊設定相容。Gemini 金鑰清單（多把用逗號分隔，輪流使用） |
| `GEMINI_MODEL` | `gemini-2.5-flash` | App｜舊設定相容。Gemini 連線使用的模型 |
| `USER_BACKGROUND` | *(無)* | App｜使用者背景（身分、專長、手上的專案）；AI 分析會據此多寫一段結合背景的建議，留空則維持中性 |
| `LOCAL_HARDWARE` | *(無)* | App｜本機硬體（CPU／GPU／顯存）；分析 AI 模型時評估能否在這台機器上跑，提問的畫面也會顯示 |
| `DATABASE_PATH` | `omnikeep.db` | 本地 SQLite 資料庫路徑（自動開啟 WAL 模式） |
| `OMNIKEEP_SECRET_KEY` | *(無)* | 選填。加密 App 內金鑰的主金鑰；不設時自動產生在資料庫旁的 `omnikeep.secret.key`（也可用 `OMNIKEEP_SECRET_KEY_FILE` 改位置） |
| `RADAR_ENABLED` | *(已停用)* | 探索的背景檢查改在介面開關：開啟實驗功能後，在「探索設定」的「排程與通知」分頁啟用並設定間隔，新安裝預設關閉。這個變數只在升級舊資料庫時讀取一次，沿用原本實際的開關狀態 |
| `BACKUP_SINK` | `local` | App｜備份方式：`local`（本機輪替）、`rclone`（雲端同步）、`git`、`off` |
| `TELEGRAM_BOT_TOKEN` | *(無)* | App｜Telegram 的機器人權杖（選填） |
| `TELEGRAM_ALLOWED_USER_IDS` | *(無)* | App｜可以使用機器人的 Telegram 帳號編號。在「設定 › 收錄管道 › Telegram」用一次性配對連結綁定，存進資料庫 |

---

## 開發

這是什麼：改 OmniKeep 的程式時用的指令。只是使用的話不需要。

前端：

```bash
cd frontend
npm ci            # 安裝依賴
npm run dev       # 啟動 HMR 開發模式 (API 自動代理至 localhost:5000)
npm run build     # 編譯正式版產物 (包含型別檢查與 PWA Service Worker 生成)
```

每次 push 與 Pull Request 都會由 GitHub Actions（`.github/workflows/ci.yml`）跑前端測試與建置、後端 pytest，並實際建置 Docker 映像。本機執行：

```bash
pip install -r requirements-dev.txt
python -m pytest -rs        # 沒裝 ffmpeg 時，兩個短影音測試會自動跳過
cd frontend && npm ci && npm test && npm run build
```

### 參與貢獻

歡迎提交 Issue 與 Pull Request：
1. Fork 本專案
2. 建立新分支 (`git checkout -b feature/amazing-feature`)
3. 提交變更 (`git commit -m 'feat: Add amazing feature'`)
4. 推送分支 (`git push origin feature/amazing-feature`)
5. 發起 Pull Request

---

## 產品路線圖

**已完成**

- [x] 收錄：Telegram 機器人、LINE 官方帳號、iOS 捷徑、PWA、書籤匯入、REST API
- [x] 讀取：網頁（trafilatura 清洗加 HTML 快照）、YouTube、Bilibili、短影音（OCR 加語音）、Threads 與 X 貼文
- [x] 分析：摘要與重點分析兩層，分析深度可調；沒接 AI 時先收藏，接上後補分析
- [x] 搜尋：trigram 分詞的 FTS5 全文檢索、sqlite-vec 語意搜尋
- [x] 提問：對收藏的內容提問，回答附引用
- [x] MCP：同一台電腦用 stdio，別台電腦用 Streamable HTTP
- [x] 設定：App 內設定（金鑰加密儲存）、AI 連線與「用途與備援順序」、由 agent 帶著做的首次設定
- [x] 備份：本機輪替、rclone、git，以及還原腳本
- [x] 網頁介面（Vite + Vue 3 + Tailwind v4 + PWA）

**實驗中**（功能在、可以開，介面與行為還會改）

- 探索：定時檢查探索來源、評分、精選與通知
- 逐則篩選的喜好回饋與 Dream Pass：Dream Pass 目前只能手動觸發，沒有排程
- 專案監看與建議
- 每日回顧

**之後要做**

- [ ] 探索從實驗功能轉為正式功能
- [ ] Chrome／Edge 瀏覽器擴充功能
- [ ] 知識圖譜檢視（Knowledge Graph View）

---

## 開源授權

本專案以 [MIT License](LICENSE) 授權。
