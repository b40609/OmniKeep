# 🧠 OmniKeep

<div align="center">

**Self-hosted link keeper: send a link, it reads it for you, find it or ask about it later.**<br>
**在 Telegram 丟連結，OmniKeep 幫你讀完（網頁、影片、社群貼文），之後找得到、問得到。**

[![Python 3.12+](https://img.shields.io/badge/Python-3.12%2B-3776AB?logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115%2B-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Vue 3](https://img.shields.io/badge/Vue.js-3.5%2B-4FC08D?logo=vuedotjs&logoColor=white)](https://vuejs.org)
[![Tailwind CSS](https://img.shields.io/badge/Tailwind_CSS-v4-06B6D4?logo=tailwindcss&logoColor=white)](https://tailwindcss.com)
[![SQLite WAL](https://img.shields.io/badge/SQLite-WAL%20%2B%20FTS5-003B57?logo=sqlite&logoColor=white)](https://sqlite.org)
[![Docker Ready](https://img.shields.io/badge/Docker-Ready-2496ED?logo=docker&logoColor=white)](Dockerfile)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

[核心亮點](#-核心亮點) •
[系統架構](#-系統架構) •
[快速啟動](#-快速啟動) •
[安全注意事項](#-安全注意事項) •
[收錄管道](#-全通路無摩擦採集) •
[AI 服務商](#-ai-服務商) •
[環境變數](#-環境變數說明) •
[路線圖](#-產品路線圖)

</div>

---

## 💡 為什麼選擇 OmniKeep？

看到值得留的連結，收了常常就沒再看，要用的時候也找不到。OmniKeep 主要做一件事：

1. **丟連結**：在 Telegram 把連結傳給自己的 Bot。
2. **幫你讀完**：網頁、影片（YouTube、Bilibili、短影音）、社群貼文（Threads、X）都會抓下內容，交給你接上的 AI 寫出摘要與重點。
3. **找得到、問得到**：之後用關鍵字或語意搜尋，或用 Ask Brain 直接問，回答會附上引用的收藏。

資料存在你自己的電腦上（SQLite），不放在別人的雲端。

和常見做法的差別：
- **傳統稍後讀（Pocket、Omnivore）**：容易遭遇服務終止、資料被綁定於雲端廠商，且僅能保存靜態文字。
- **第二大腦（Notion、Obsidian）**：收錄流程繁瑣，缺乏對影音（YouTube、Bilibili、Reels）的自動化結構化消化能力。

資訊雷達（定時巡檢來源、主動推薦）是實驗功能，預設關閉，放在[核心亮點的最後一節](#6-實驗功能資訊雷達與專案監看)。

---

## ✨ 核心亮點

### 1. 丟連結就收錄 (Ingestion)
- **Telegram Bot（主要入口）**：把連結傳給自己的私人 Bot，收錄後回覆摘要卡。用一次性配對連結綁定帳號，設定見 [docs/telegram_bot.md](docs/telegram_bot.md)。
- **LINE Bot**：同樣是轉發連結就收錄，見 [docs/line_bot.md](docs/line_bot.md)。
- **手機**：iOS 原生捷徑（Share Sheet）一鍵收錄，或把 PWA 加到主畫面。
- **外部 Agent（MCP）**：同一台電腦用 stdio，別台電腦用 Streamable HTTP（`/mcp-http`，經 Tailscale）；舊的 SSE 端點還保留。安裝腳本會自動註冊到 Claude Code、Codex、Antigravity，見 [docs/mcp_integration.md](docs/mcp_integration.md)。
- **REST API**：提供 Swagger API 介面，方便各類腳本與自動化管線串接。

### 2. 多模態深度消化管線 (Multimodal Cognitive Pipeline)
- **YouTube 影音**：整合 Google Gemini 原生串流解析，主機零下載、零頻寬佔用，秒級提煉數十分鐘長影片結構。沒有 Gemini 時讀字幕，沒字幕就用本機語音轉錄（中文用台灣華語微調的 Breeze-ASR-25），逐字稿帶 `[MM:SS]` 時間與章節；選裝畫面 OCR 後，再補上投影片、圖表上旁白沒講到的字（見 [選用功能](docs/optional_features.md)）。
- **Bilibili 長影片**：雙軌語音抽取技術——首選官方 CC/AI 逐字稿 JSON（0.2 秒完成），回落 DASH 音訊分離串流搭配本機 `faster-whisper`（GPU CUDA / CPU 多執行緒自動切換；選用安裝，見 [選用功能](docs/optional_features.md)）。
- **社群短影音 (Reels / TikTok / Shorts)**：關鍵幀 OCR 視覺文字識別 + 語音轉錄（本機或雲端）雙軌融合成高密度情報。
- **長文閱讀與永久快照**：採用 trafilatura 深度清洗廣告干擾，自動生成 HTML Snapshot 永久留存，徹底免疫網頁失效與連結腐敗（Link-rot Proof）。

### 3. 兩段式分層認知 (Two-Stage Triage)
- **L1 速覽層**：卡片直觀呈現「直擊本質的自定義標題 + 1-2 句核心痛點與解法 + 核心技術標籤」，拒絕廢話。
- **L2 深入層**：秒開深度技術架構解構、規格清單、核心代碼細節與 **Markdown 原文純淨閱讀器（Reader View）**。

### 4. 找得到、問得到 (Search & Ask Brain)
- **全文檢索**：SQLite FTS5，用 trigram 分詞，中文句子裡的子字串也找得到；不到三個字的詞改用 LIKE 比對。
- **語意搜尋**：sqlite-vec 向量索引，和全文檢索的結果用 RRF 合併，關鍵字對不上時也找得到相關內容（索引的檢查與重建見 [向量索引](docs/vector_index.md)）。
- **Ask Brain**：直接對收藏的內容提問。先檢索相關的收藏，再交給 AI 回答，回答裡附上引用的來源編號。

### 5. 本地優先與數據主權 (Local-First & Multi-Sink Backup)
- **SQLite WAL 架構**：資料都在本機的一個 SQLite 資料庫（WAL 模式），全文索引是 trigram 分詞的 FTS5，向量索引是 sqlite-vec。
- **多端自動備份**：內建自動每日備份機制，支援本機多代輪替（Local Retention）、雲端物件同步（Rclone: Google Drive/Dropbox/S3）以及私有 Git 儲庫自動提交。資料庫與 HTML 快照一起備份，用 `scripts/restore_backup.py` 還原，見 [備份與還原](docs/backup_restore.md)。

### 6. 實驗功能：資訊雷達與專案監看
這些功能還在、可以開，但介面與行為還會改，新安裝預設關閉。
- **資訊雷達**：定時巡檢你加的來源（RSS、YouTube 頻道、GitHub 專案、Google News 關鍵字、網頁變動），每輪只挑分數最高的幾篇做 AI 分析，再整理成雷達摘要。在「雷達 › 排程與推播」開啟並設定間隔。
- **通知**：預設不送；可以改成每日摘要，或只在分數到門檻時通知。
- **喜好回饋**：滑卡時的喜歡、不喜歡會調整標籤的權重（14 天半衰期），影響之後的排序。
- **Dream Pass**：依最近的互動提議更新興趣設定檔，你同意才套用。目前只能手動觸發（Telegram 的 `/dreampass`），沒有排程，不會自動發生。
- **專案監看**：掃描你指定的本機資料夾，產生風險與改進的提案卡，見 [監看中心](docs/watch_proposals.md)。

---

## 🧩 系統架構

```
                       [用戶輸入終端層]
   iOS 原生捷徑    Android PWA    Telegram / LINE Bot    IDE Agent (Cursor/Claude)
        │              │                  │                         │
        └──────────────┴─────────┬────────┴─────────────────────────┘
                                 ▼
                     [FastAPI 統一接入閘道]
           (Bearer Token 鑑權 / 限流保護 / 異步任務排程器)
                                 │
           ┌─────────────────────┼─────────────────────┐
           ▼                     ▼                     ▼
   [多模態長影片管線]     [社群短影音管線]       [技術長文萃取管線]
  • YouTube (Gemini)    • Instagram / TikTok   • Trafilatura 正文清洗
  • Bilibili (CC/DASH)  • 關鍵幀 OCR / Whisper  • HTML 抗腐快照存儲
           │                     │                     │
           └─────────────────────┼─────────────────────┘
                                 ▼
                    [動態 LLM 智能調度引擎]
     (OpenAI / DeepSeek / Google Gemini / 本機 Ollama / Groq)
                                 │
                                 ▼
                    [本地持久化與檢索大腦]
        SQLite (WAL Mode) ── FTS5 全文檢索 ── sqlite-vec 向量庫
                                 │
                                 ▼
                  [定時備份池: Local / Rclone / Git]
```

---

## 🚀 快速啟動

三種裝法，建議用第一種：

| 裝法 | 適合 | agent 帶著設定 |
| :--- | :--- | :--- |
| [交給你的 agent：一行安裝](#交給你的-agent一行安裝建議) | 大部分的人 | 有 |
| [方式 A：Docker](#方式-a使用-docker-部署) | 已經在用 Docker 的主機 | 沒有，要在網頁的設定頁自己設定 |
| [方式 B：本地環境](#方式-b本地環境運行-python--nodejs) | 想自己一步一步裝 | 裝完再執行 `scripts/register_agents.py` 就有 |

### 交給你的 agent：一行安裝（建議）

對 Claude Code、Codex 或 Antigravity 說：

> 幫我安裝 OmniKeep：https://github.com/b40609/OmniKeep

agent 會照 [`skills/omnikeep-setup`](skills/omnikeep-setup/SKILL.md) 安裝，再用最多 6 題帶你完成設定：接上 AI 管道、挑關注主題，做到第一篇分析。雷達來源是其中一題，屬於實驗功能，可以一包都不選。AI 金鑰一律在 OmniKeep 的設定頁自己貼，不經過聊天。

也可以自己執行安裝腳本：

```powershell
# Windows（Windows PowerShell 5.1 或 PowerShell 7）
& ([scriptblock]::Create((irm https://raw.githubusercontent.com/b40609/OmniKeep/main/scripts/install.ps1).TrimStart([char]0xFEFF)))
```

`install.ps1` 開頭有 UTF-8 BOM，`.TrimStart([char]0xFEFF)` 先把它去掉；少了這一段，PowerShell 會解析失敗。

```bash
# macOS、Linux
curl -fsSL https://raw.githubusercontent.com/b40609/OmniKeep/main/scripts/install.sh | bash
```

Claude Code 使用者也可以先裝 plugin，取得設定 Skill 後再說「幫我安裝 OmniKeep」：

```bash
claude plugin marketplace add b40609/OmniKeep
claude plugin install omnikeep@omnikeep
```

安裝腳本會做這些事，可以重複執行，已完成的步驟會略過：

1. 檢查 git、Python 3.12+、Node.js 20.19+（Windows 加 `-InstallPrereqs` 會用 winget 補裝）。
2. clone 到 `~/OmniKeep`（從 repo 內執行時就用這個 repo），建立 `.venv` 並安裝依賴。
3. 沒有 `.env` 時用 `scripts/bootstrap_env.py` 產生，存取金鑰隨機產生、不會顯示。只在這台電腦上用的話，不需要知道這把金鑰。
4. 建置前端，啟動服務並設定自動重啟：Windows 是排程工作「OmniKeep Watchdog」（每分鐘檢查、登入時啟動），Linux 是 systemd 使用者服務，macOS 是 launchd。
5. 用 `scripts/register_agents.py` 把 stdio MCP 與 `omnikeep-setup` Skill 註冊到這台電腦的 Claude Code（`claude mcp add -s user`）、Codex（`codex mcp add`）、Antigravity（`~/.gemini/config/mcp_config.json`）。agent 的設定檔裡不放任何金鑰；已經有別的 `omnikeep` 設定時不覆蓋，要加 `--force`。

想先看會做什麼：Windows 加 `-DryRun`，macOS、Linux 加 `--dry-run`；`python scripts/register_agents.py --dry-run` 只看註冊的部分。

裝好之後：

1. 在這台電腦用瀏覽器打開 `http://127.0.0.1:5000`，會直接進主畫面，不用登入。
2. 開一個新的 agent session，說「幫我設定 OmniKeep」。

### 登入與其他裝置

- **這台電腦**：在執行 OmniKeep 的電腦上用瀏覽器打開 `http://127.0.0.1:5000`，直接進主畫面，不用輸入金鑰。
- **其他裝置**（手機、別台電腦，經 Tailscale 或任何反向代理連進來）：要輸入存取金鑰，或一次性配對碼。配對碼在已經登入的 OmniKeep 的「設定 › 系統 › 手機登入」產生（QR code 或 8 碼，5 分鐘內有效、只能用一次）。連線方式見 [Tailscale 部署](docs/tailscale_pwa_deploy.md)。
- **關掉免登入**：「設定 › 系統」的「這台電腦免登入」預設是開的。關掉之後，這台電腦也要輸入金鑰或配對碼。
- **舊安裝**：`.env` 裡已經寫了 `LOCAL_AUTO_LOGIN=false` 的，行為不變，這台電腦一樣要登入。
- **Docker**：一律要金鑰，因為容器裡看到的連線來源不是本機位址。
- **存取金鑰**：安裝時隨機產生，存在 `.env` 的 `API_KEY`，給其他裝置、REST API 與遠端 MCP 用。只在這台電腦上用的話，不需要知道它。

### 方式 A：使用 Docker 部署

**Docker 目前不支援「agent 帶著設定」的流程。** 映像裡只有服務本身，沒有 `mcp_server.py`、`skills/` 與 `scripts/register_agents.py`（見 `Dockerfile`），所以不會註冊 MCP 與設定 Skill。AI 服務商、Telegram 等都要在網頁的設定頁自己設定。想讓 agent 帶著設定，請用上面的一行安裝。

一般書籤收藏、匯入與關鍵字搜尋不需要 GPU 或付費 AI API：

```bash
# 1. 複製專案
git clone https://github.com/b40609/OmniKeep.git
cd OmniKeep

# 2. 安全產生首次設定檔與隨機 API_KEY（需有 Python 3）
python scripts/bootstrap_env.py

# 3. 檢查 Compose 設定並建置、啟動
docker compose config -q
docker compose up -d --build
```

如果主機**只安裝 Docker、沒有 Python**：Linux / macOS 先執行 `cp .env.example .env`；Windows PowerShell 改用 `Copy-Item .env.example .env`。接著用文字編輯器在 `.env` 的 `API_KEY=` 後填入自行安全產生、至少 32 字元且包含至少 12 種不同字元的隨機金鑰，再執行第 3 步。**不要將 `.env` 提交到 Git 或公開金鑰。**

開啟 `http://localhost:5000`，用 `.env` 裡的 `API_KEY` 登入。Docker 一律要金鑰：容器裡看到的連線來源不是本機位址，「這台電腦免登入」不會生效。Docker 預設只在主機本機監聽（`BIND_ADDRESS=127.0.0.1`），資訊雷達預設關閉。需要手機或其他電腦連線時，才將 `BIND_ADDRESS` 改成適當的受保護網路位址；請勿直接暴露至公網。新安裝會提供停用的雷達來源範例，需自行選擇並啟用；分類可自訂。

**首次體驗（不需 AI 金鑰）**：登入後按頂部的「新增」，把瀏覽器匯出的 HTML 書籤檔拖進去（或按「選擇檔案」），匯入方式選「只匯入，不分析」，接著用頂部的搜尋框查找內容。選「匯入後交給 AI 分析」或使用 AI 摘要前，才需要接上 AI：開啟側欄底部的「設定」，在「AI 服務商」新增連線並儲存，立即生效，不必重啟服務。Docker 版資料與備份保存在 `omnikeep_data` volume，更新容器時請保留該 volume。

Docker 映像預設不含本機語音轉錄，也沒有 Chrome；要加入本機語音轉錄，在 `.env` 設定 `LOCAL_STT=true` 後重新建置。見 [選用功能](docs/optional_features.md)。

**手機與捷徑**：手機以網頁方式連線可使用受保護的區網／VPN；PWA 安裝與離線快取通常需要 HTTPS。請參考 [iOS／Android 設定指南](docs/ios_shortcut.md)。每位使用者須自行設定端點與 API Key，且應透過 `X-API-Key` 標頭傳送憑證。

---

### 方式 B：本地環境運行 (Python + Node.js)

#### 1. 安裝環境與依賴
- **後端環境**：Python 3.12+（CI 測試 3.12 與 3.14）
- **前端建置**：Node.js 20.19+ 或 22.12+（Python 本地部署也必須建置一次）

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

#### 2. 建立首次設定並建置工作台
```bash
python scripts/bootstrap_env.py
cd frontend
npm ci
npm run build
cd ..
```
上述工具只在 `.env` 尚未存在時建立檔案，不會覆寫既有設定；前端建置產物 `static/dist/` 不納入 Git。**首次使用不必先申請 LLM 金鑰。**要啟用 AI 摘要時，開啟側欄底部的「設定」，在「AI 服務商」新增連線（API 位址、金鑰與模型），測試後儲存即可，立即生效、不必重新啟動。Telegram、LINE、GitHub Token 與備份也都在這裡設定。

- App 內輸入的金鑰會加密後才存進資料庫，之後只顯示末四碼；解密用的主金鑰是資料庫旁的 `omnikeep.secret.key`（不會進入備份，搬機時要一起帶走；遺失只需重新輸入金鑰）。
- 優先順序：App 內設定 > `.env` > 預設值。已經寫在 `.env` 的值仍然有效，可在「設定 › 系統」一鍵匯入 App。
- `HOST`、`PORT`、`DATABASE_PATH`、`API_KEY` 在服務啟動前就要用到或負責保護登入，仍只能寫在 `.env`。
- 這台電腦要不要免登入，在「設定 › 系統」的「這台電腦免登入」切換，見[登入與其他裝置](#登入與其他裝置)。

> [!TIP]
> 已有 `.env` 的使用者可用獨立的金鑰輪替腳本更新存取金鑰；這會使舊金鑰失效，請同步更新所有客戶端：
> ```bash
> python scripts/rotate_api_key.py
> ```

#### 3. 啟動服務
```bash
python run.py
```
- **Web 工作台**：在這台電腦用瀏覽器打開 `http://127.0.0.1:5000`，直接進主畫面，不用輸入金鑰。服務預設只綁定 `HOST=127.0.0.1`；要給其他裝置用，見[安全注意事項](#-安全注意事項)。
- **從其他裝置登入**：輸入存取金鑰或配對碼，見[登入與其他裝置](#登入與其他裝置)。登入頁的「記住金鑰」會把金鑰存在那個瀏覽器，請只在自己的裝置勾選。
- **REST API 文件**：訪問 `http://localhost:5000/docs`（需帶入 `Authorization: Bearer <API_KEY>`）。

---

## 🔒 安全注意事項

- **預設只綁本機位址**：`HOST=127.0.0.1`（Docker 是 `BIND_ADDRESS=127.0.0.1`），別台裝置連不到。
- **這台電腦免登入的意思**：在執行 OmniKeep 的電腦上打開不用金鑰。同一台電腦上的其他程式、其他使用這台電腦的人，也一樣能使用 OmniKeep。多人共用的電腦，請到「設定 › 系統」關掉「這台電腦免登入」。
- **要給其他裝置用**：走 Tailscale 這類私有網路，見 [Tailscale 部署](docs/tailscale_pwa_deploy.md)。從其他裝置連進來一律要存取金鑰或配對碼。
- **不要把整個服務公開到網際網路**：不要把 `HOST` 改成 `0.0.0.0` 後直接對外，也不要用 `tailscale funnel 5000` 這類把整個服務公開的指令。LINE Bot 需要公開的 webhook 時，只公開那一條路徑，見 [docs/line_bot.md](docs/line_bot.md)。
- **存取金鑰外洩時**：執行 `python scripts/rotate_api_key.py` 換一把，重啟服務，再更新各個 client。
- **不要提交到 Git**：`.env`、`omnikeep.secret.key`、`cookies.txt`、資料庫。`.gitignore` 已經排除這些檔案。

---

## 📱 全通路無摩擦採集

| 通路 | 適用環境 | 特色說明 | 配置文件 |
| :--- | :--- | :--- | :--- |
| **Telegram Bot（主要入口）** | 跨平台 (手機/電腦) | 把網址轉發給私人 Bot，收錄後回覆摘要卡 | [docs/telegram_bot.md](docs/telegram_bot.md) |
| **LINE 官方帳號** | LINE App | 轉發網址或長文給 Bot，回傳 Flex 訊息卡 | [docs/line_bot.md](docs/line_bot.md) |
| **iOS 原生捷徑** | iPhone / iPad | 原生 Share Sheet 一鍵發送到後端，背景處理 | [docs/ios_shortcut.md](docs/ios_shortcut.md) |
| **行動端 PWA** | iOS / Android | 加入主畫面獨立執行 | [docs/ios_shortcut.md](docs/ios_shortcut.md) |
| **MCP (Model Context)** | Claude Code、Codex、Antigravity 等 | 讓外部 agent 檢索 OmniKeep、把結論寫回來 | [docs/mcp_integration.md](docs/mcp_integration.md) |

---

## 🤖 AI 服務商

AI 連線在「設定 › AI 服務商」管理，分成兩層：

- **連線**：一個服務商的位址、金鑰與模型。可以從目錄卡片新增，卡片上有費用與限額、建議模型、申請連結與最後查證日期（資料在 `app/provider_catalog.py`）；也可以自己填任何 OpenAI 相容的 `/v1` 位址。
- **用途**：分析、Ask Brain、雷達評分、向量（語意搜尋）、影片解析各排一串連線，第一個是主要，其餘依序備援。

支援三種協定：OpenAI 相容（`/v1`）、Google Gemini、本機 Ollama。儲存後立即生效，不必重啟。

模型名稱、免費額度變動很快，這裡不列，以設定頁目錄卡片上的內容為準。`.env` 的 `OPENAI_*`、`GEMINI_*` 是舊設定的相容，見下面的環境變數表。

---

## 🎨 現代化 Web 工作台 (Frontend Workbench)

前端採用現代工程化技術棧構建：**Vite + Vue 3 (Composition API) + Tailwind CSS v4 + Reka UI (shadcn-vue)**。

### 鍵盤流操作 (Keyboard Shortcuts)
OmniKeep 設計了符合重度資訊工作者直覺的鍵盤流導航：
- `J` / `K`：向下 / 向上快速移動閱讀項目
- `E`：切換封存狀態（Archive / Unarchive）
- `S`：加星標 / 取消星標（Star / Unstar）
- `Enter`：開啟 L2 深入層閱讀器
- `Esc`：關閉閱讀器 / 彈出對話框
- `/` 或 `Ctrl/Cmd+K`：聚焦頂部的搜尋框（搜尋、提問、篩選與動作都在這一個框）
- `B`：同一個搜尋框，切到提問
- `N`：新增（貼上連結、寫筆記，或把書籤檔拖進來）
- `R`：手動觸發情報雷達即時巡邏

### 前端自訂與建置
構建產物輸出至 `static/dist/`，直接由 FastAPI 高速服務：
```bash
cd frontend
npm install       # 安裝依賴
npm run dev       # 啟動 HMR 開發模式 (API 自動代理至 localhost:5000)
npm run build     # 編譯生產環境產物 (包含型別檢查與 PWA Service Worker 生成)
```

---

## 🔧 環境變數說明

大部分設定不用寫 `.env`。標示「App」的設定可以在網頁的「設定」頁修改；App 內儲存的值優先於 `.env`。

AI 連線已經改在「設定 › AI 服務商」用「連線 + 用途」管理。下表的 `PRIMARY_LLM_PROVIDER`、`OPENAI_*`、`PRIMARY_MODEL`、`GEMINI_*` 只是舊設定的相容：已經寫在 `.env` 的會被帶進連線清單，新安裝不用填。

| 變數名稱 | 預設值 | 說明 |
| :--- | :--- | :--- |
| `API_KEY` | *(安裝時隨機產生)* | 存取金鑰（至少 32 字元、12 種不同字元）。其他裝置登入、REST API 與遠端 MCP 用；在這台電腦上用瀏覽器不需要它 |
| `HOST` | `127.0.0.1` | 服務綁定的位址。預設只綁本機；不要改成 `0.0.0.0` 直接對外，其他裝置請走 Tailscale（見[安全注意事項](#-安全注意事項)） |
| `PORT` | `5000` | 服務的埠 |
| `BIND_ADDRESS` | `127.0.0.1`（新安裝範例） | Docker 主機監聽位址；要允許區網存取需明確設定 |
| `LOCAL_STT` | `false` | Docker 建置時加入本機語音轉錄，見 [選用功能](docs/optional_features.md) |
| `LOCAL_AUTO_LOGIN` | *(新安裝不用設)* | 這台電腦免登入的舊設定。新安裝預設免登入，由「設定 › 系統」的「這台電腦免登入」開關控制；`.env` 裡已經寫 `false` 的舊安裝行為不變，這台電腦一樣要登入。Docker 一律要金鑰 |
| `MCP_ALLOWED_HOSTS` | *(無)* | 遠端 MCP（`/mcp-http`）額外接受的主機名稱，逗號分隔；loopback 與啟動時找到的 Tailscale 名稱不用寫，見 [MCP 整合](docs/mcp_integration.md) |
| `PRIMARY_LLM_PROVIDER` | `openai_compatible` | App｜舊設定相容。主要推理 Provider 類型（`openai_compatible` 或 `gemini`） |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | App｜舊設定相容。OpenAI 相容端點 Base URL |
| `OPENAI_API_KEY` | *(無)* | App｜舊設定相容。對應端點的 API Key |
| `PRIMARY_MODEL` | `gpt-4o-mini` | App｜舊設定相容。主要萃取與摘要所使用的模型名稱 |
| `GEMINI_API_KEYS` | *(無)* | App｜舊設定相容。Gemini API 金鑰清單（多把用逗號分隔，輪流使用） |
| `GEMINI_MODEL` | `gemini-2.5-flash` | App｜舊設定相容。Gemini 連線使用的模型 |
| `USER_BACKGROUND` | *(無)* | App｜使用者背景（身分、專長、手上的專案）；AI 分析會據此多寫一段落地建議，留空則維持中性 |
| `LOCAL_HARDWARE` | *(無)* | App｜本機硬體（CPU／GPU／顯存）；分析 AI 模型時評估能否在這台機器上跑，Ask Brain 也會顯示 |
| `DATABASE_PATH` | `omnikeep.db` | 本地 SQLite 資料庫路徑（自動開啟 WAL 模式） |
| `OMNIKEEP_SECRET_KEY` | *(無)* | 選填。加密 App 內金鑰的主金鑰；不設時自動產生在資料庫旁的 `omnikeep.secret.key`（也可用 `OMNIKEEP_SECRET_KEY_FILE` 改位置） |
| `RADAR_ENABLED` | *(已停用)* | 背景巡檢改在介面的「雷達 › 排程與推播」開關並設定週期，新安裝預設關閉。只在升級舊資料庫時讀取一次，沿用原本實際的開關狀態 |
| `BACKUP_SINK` | `local` | App｜備份方案：`local`（本機輪替）、`rclone`（雲端同步）、`git`、`off` |
| `TELEGRAM_BOT_TOKEN` | *(無)* | App｜Telegram Ingestion Bot Token（選填） |
| `TELEGRAM_ALLOWED_USER_IDS` | *(無)* | App｜授權使用 Bot 的 Telegram 用戶數值 ID。在「設定 › Telegram」用一次性配對連結綁定，存進資料庫 |

---

## 🧭 產品路線圖

**已完成**

- [x] 收錄：Telegram Bot、LINE Bot、iOS 捷徑、PWA、書籤匯入、REST API
- [x] 讀取：網頁（trafilatura 清洗加 HTML 快照）、YouTube、Bilibili、短影音（OCR 加語音）、Threads 與 X 貼文
- [x] 摘要：兩段式（L1 速覽、L2 深入），分析深度可調
- [x] 搜尋：trigram 分詞的 FTS5 全文檢索、sqlite-vec 語意搜尋
- [x] Ask Brain：對收藏的內容提問，回答附引用
- [x] MCP：同一台電腦用 stdio，別台電腦用 Streamable HTTP
- [x] 設定：App 內設定（金鑰加密儲存）、AI 服務商的「連線 + 用途」、由 agent 帶著做的首次設定
- [x] 備份：本機輪替、rclone、git，以及還原腳本
- [x] Web 工作台（Vite + Vue 3 + Tailwind v4 + PWA）

**實驗中**（功能在、可以開，介面與行為還會改）

- 資訊雷達：定時巡檢來源、評分、雷達摘要與通知
- 喜好回饋與 Dream Pass：Dream Pass 目前只能手動觸發，沒有排程
- 專案監看與提案卡

**之後要做**

- [ ] 資訊雷達從實驗功能轉為正式功能
- [ ] Chrome / Edge 瀏覽器擴充功能
- [ ] 知識圖譜檢視（Knowledge Graph View）

---

## 🤝 參與貢獻 (Contributing)

歡迎提交 Issue 與 Pull Request！
1. Fork 本專案
2. 建立新分支 (`git checkout -b feature/amazing-feature`)
3. 提交變更 (`git commit -m 'feat: Add amazing feature'`)
4. 推送分支 (`git push origin feature/amazing-feature`)
5. 發起 Pull Request

每次 push 與 Pull Request 都會由 GitHub Actions（`.github/workflows/ci.yml`）跑前端測試與建置、後端 pytest，並實際建置 Docker 映像。本機執行：

```bash
pip install -r requirements-dev.txt
python -m pytest -rs        # 沒裝 ffmpeg 時，兩個短影音測試會自動跳過
cd frontend && npm ci && npm test && npm run build
```

---

## 📄 開源授權 (License)

本專案基於 [MIT License](LICENSE) 條款開源發布。
