# 🧠 OmniKeep

<div align="center">

**Your Self-Hosted Multimodal Knowledge Hub & Autonomous Signal Radar.**<br>
**專屬於每位知識工作者的自託管多模態情報中樞與主動第二大腦。**

[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115%2B-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Vue 3](https://img.shields.io/badge/Vue.js-3.5%2B-4FC08D?logo=vuedotjs&logoColor=white)](https://vuejs.org)
[![Tailwind CSS](https://img.shields.io/badge/Tailwind_CSS-v4-06B6D4?logo=tailwindcss&logoColor=white)](https://tailwindcss.com)
[![SQLite WAL](https://img.shields.io/badge/SQLite-WAL%20%2B%20FTS5-003B57?logo=sqlite&logoColor=white)](https://sqlite.org)
[![Docker Ready](https://img.shields.io/badge/Docker-Ready-2496ED?logo=docker&logoColor=white)](Dockerfile)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

[核心亮點](#-核心亮點) •
[架構解析](#-系統架構) •
[三分鐘快速上手](#-快速啟動) •
[全通路採集](#-全通路無摩擦採集) •
[模型適配矩陣](#-ai-模型適配矩陣) •
[配置說明](#-環境變數說明) •
[路線圖](#-產品路線圖)

</div>

---

## 💡 為什麼選擇 OmniKeep？

現代知識工作者每天面臨嚴重的「資訊過載」與「收藏即遺忘」困境：
- **傳統稍後讀（Pocket、Omnivore）**：容易遭遇服務終止、資料被綁定於雲端廠商，且僅能保存靜態文字。
- **第二大腦（Notion、Obsidian）**：收錄流程繁瑣，缺乏對影音（YouTube、Bilibili、Reels）的自動化結構化消化能力。
- **RSS 閱讀器**：資訊量巨大，未經個人化品味篩選，導致未讀紅點永無止境堆積。

**OmniKeep** 專為解決上述痛點而生：這是一套**100% 本地自託管、多模態解析、具備兩段式認知消化與自主情報雷達**的現代知識作業系統。

---

## ✨ 核心亮點

### 1. 零摩擦全通路收錄 (Universal Ingestion)
- **行動端原生支援**：iOS 原生捷徑（Share Sheet）一鍵收錄、Android PWA 獨立全螢幕體驗。
- **即時通訊機器人**：內建 Telegram 私人雙向 Bot 與 LINE Bot，在通訊軟體內轉發網址即可收錄並取得結構化摘要卡。
- **外部 Agent 直連**：完整支援 **Model Context Protocol (MCP)**（提供 Local stdio 與 Remote SSE 雙模），讓 Cursor、Claude Code、Windsurf 等 IDE Agent 直接存取與回寫大腦。
- **標準 REST API**：提供 Swagger API 介面，方便各類腳本與自動化管線串接。

### 2. 多模態深度消化管線 (Multimodal Cognitive Pipeline)
- **YouTube 影音**：整合 Google Gemini 原生串流解析，主機零下載、零頻寬佔用，秒級提煉數十分鐘長影片結構。
- **Bilibili 長影片**：雙軌語音抽取技術——首選官方 CC/AI 逐字稿 JSON（0.2 秒完成），回落 DASH 音訊分離串流搭配本機 `faster-whisper`（GPU CUDA / CPU 多執行緒自動切換）。
- **社群短影音 (Reels / TikTok / Shorts)**：關鍵幀 OCR 視覺文字識別 + 本地語音轉錄雙軌融合成高密度情報。
- **長文閱讀與永久快照**：採用 trafilatura 深度清洗廣告干擾，自動生成 HTML Snapshot 永久留存，徹底免疫網頁失效與連結腐敗（Link-rot Proof）。

### 3. 兩段式分層認知 (Two-Stage Triage)
- **L1 速覽層**：卡片直觀呈現「直擊本質的自定義標題 + 1-2 句核心痛點與解法 + 核心技術標籤」，拒絕廢話。
- **L2 深入層**：秒開深度技術架構解構、規格清單、核心代碼細節與 **Markdown 原文純淨閱讀器（Reader View）**。

### 4. 自主情報雷達與個人品味學習 (Signal Radar & Taste Learning)
- **主動情報巡邏**：定時巡檢 RSS 訂閱源、GitHub Trending、HackerNews 等情報池。
- **靜默歸檔與過濾**：低價值情報靜默寫入待選庫，不推送干擾通知。
- **個人興趣特徵畫像**：根據用戶加星標、閱讀深度與自定義偏好（Dream Pass）自動計算匹配評分，僅在達到 VIP 門檻時主動推播。

### 5. 本地優先與數據主權 (Local-First & Multi-Sink Backup)
- **高併發 SQLite WAL 架構**：啟用 SQLite WAL 模式與 Unicode61 FTS5 全文索引，毫秒級全文檢索，並支援 sqlite-vec 向量語意檢索。
- **多端自動備份**：內建自動每日備份機制，支援本機多代輪替（Local Retention）、雲端物件同步（Rclone: Google Drive/Dropbox/S3）以及私有 Git 儲庫自動提交。

---

## 🏗️ 系統架構

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

### 方式 A：使用 Docker 部署 (推薦)

建議以 Docker Compose 首次部署。一般書籤收藏、匯入與關鍵字搜尋不需要 GPU 或付費 AI API：

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

開啟 `http://localhost:5000`，使用 `.env` 中的 `API_KEY` 登入。Docker 預設只在主機本機監聽（`BIND_ADDRESS=127.0.0.1`），並關閉自動登入與情報雷達。需要手機或其他電腦連線時，才將 `BIND_ADDRESS` 改成適當的受保護網路位址；請勿直接暴露至公網。新安裝會提供停用的情報來源範例，需自行選擇並啟用；分類可自訂。

**首次體驗（不需 AI 金鑰）**：登入後點選頂部「書籤匯入」，從瀏覽器匯出 HTML 書籤檔並選擇「秒速快速入庫」，接著使用搜尋列查找內容。選擇「排入 AI 深度解析佇列」或使用 AI 摘要前，才需要另外設定 AI Provider 金鑰並重啟服務。Docker 版資料與備份保存在 `omnikeep_data` volume，更新容器時請保留該 volume。

**手機與捷徑**：手機以網頁方式連線可使用受保護的區網／VPN；PWA 安裝與離線快取通常需要 HTTPS。請參考 [iOS／Android 設定指南](docs/ios_shortcut.md)。倉庫保留的 `static/qr_*` 僅導向公開設定文件，並不是你的可用 Webhook；每位使用者須自行設定端點與 API Key，且應透過 `X-API-Key` 標頭傳送憑證。

---

### 方式 B：本地環境運行 (Python + Node.js)

#### 1. 安裝環境與依賴
- **後端環境**：Python 3.10+
- **前端建置**：Node.js 20.19+ 或 22.12+（Python 本地部署也必須建置一次）

```bash
# 建立並啟動 Python 虛擬環境
python -m venv .venv

# Windows:
.venv\Scripts\activate
# Linux / macOS:
source .venv/bin/activate

# 安裝 Python 依賴
pip install -r requirements.txt
```

#### 2. 建立首次設定並建置工作台
```bash
python scripts/bootstrap_env.py
cd frontend
npm ci
npm run build
cd ..
```
上述工具只在 `.env` 尚未存在時建立檔案，不會覆寫既有設定；前端建置產物 `static/dist/` 不納入 Git。**首次使用只需要 `API_KEY`，不必先申請 LLM 金鑰。**要啟用 AI 摘要時，再編輯 `.env`，例如：

```env
# 主要 LLM (支援 OpenAI、DeepSeek、Ollama 等)
PRIMARY_LLM_PROVIDER=openai_compatible
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_API_KEY=your_api_key_here
PRIMARY_MODEL=gpt-4o-mini
```

> [!TIP]
> 已有 `.env` 的使用者可用獨立的金鑰輪替腳本更新存取金鑰；這會使舊金鑰失效，請同步更新所有客戶端：
> ```bash
> python scripts/rotate_api_key.py
> ```

#### 3. 啟動服務
```bash
python run.py
```
- **Web 工作台**：開啟瀏覽器訪問 `http://localhost:5000`。本地 Python 服務預設綁定 `HOST=127.0.0.1`；若要提供其他裝置連線，需明確變更 `HOST`，並先做好存取限制。
- **首次登入**：輸入 `.env` 中的 `API_KEY`；「記住金鑰」會將它保存在此瀏覽器，請只在受信任裝置勾選。
- **REST API 文件**：訪問 `http://localhost:5000/docs`（需帶入 `Authorization: Bearer <API_KEY>`）。

---

## 📱 全通路無摩擦採集

| 通路 | 適用環境 | 特色說明 | 配置文件 |
| :--- | :--- | :--- | :--- |
| **iOS 原生捷徑** | iPhone / iPad | 原生 Share Sheet 一鍵發送到後端，零等待異步萃取 | [docs/ios_shortcut.md](docs/ios_shortcut.md) |
| **行動端 PWA** | iOS / Android | 加入主畫面獨立執行，自動適配瀏海/動態島與全螢幕手勢 | [docs/ios_shortcut.md](docs/ios_shortcut.md) |
| **Telegram Bot** | 跨平台 (手機/電腦) | 隨手轉發網址給私有 Bot，自動回覆高密度雙向互動卡片 | [docs/telegram_bot.md](docs/telegram_bot.md) |
| **LINE 官方帳號** | LINE App | 轉發網址或長文給 Bot，回傳深色風格結構化 Flex 訊息卡 | [docs/line_bot.md](docs/line_bot.md) |
| **MCP (Model Context)** | Cursor / Claude Code | 讓外部 Coding Agent 直連 OmniKeep 進行檢索與總結回寫 | [docs/mcp_integration.md](docs/mcp_integration.md) |

---

## 🤖 AI 模型適配矩陣

OmniKeep 採用完全解耦的 Provider 架構，原生相容任何 OpenAI 相容端點與 Google Gemini：

| 提供商 (Provider) | 推薦模型 | `OPENAI_BASE_URL` 範例 | 特點與適用場景 |
| :--- | :--- | :--- | :--- |
| **OpenAI** | `gpt-4o`, `gpt-4o-mini` | `https://api.openai.com/v1` | 頂級推理與長文架構拆解能力 |
| **DeepSeek** | `deepseek-chat` | `https://api.deepseek.com/v1` | 高性價比、強大中文技術理解力 |
| **Ollama (本機自託管)** | `qwen2.5`, `llama3.1` | `http://localhost:11434/v1` | 100% 離線運行、資料絕對私密不出本機 |
| **Groq** | `llama-3.3-70b-versatile` | `https://api.groq.com/openai/v1` | 極致推理速度（數百 Tokens/秒） |
| **Google Gemini** | `gemini-2.5-flash` | *(使用 `GEMINI_API_KEYS`)* | YouTube 原生免下載串流解析、多 Key 輪詢池 |

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
- `/`：快速聚焦全站即時檢索欄
- `N`：隨手快速建立靈感筆記
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

## ⚙️ 環境變數說明

| 變數名稱 | 預設值 | 說明 |
| :--- | :--- | :--- |
| `API_KEY` | *(無)* | 核心存取主金鑰（長度 >= 32 字元），保護 Web、API 與 MCP |
| `BIND_ADDRESS` | `127.0.0.1`（新安裝範例） | Docker 主機監聽位址；要允許區網存取需明確設定 |
| `LOCAL_AUTO_LOGIN` | `false`（新安裝範例） | 是否允許從 loopback 自動取得存取金鑰；公開部署建議關閉 |
| `PRIMARY_LLM_PROVIDER` | `openai_compatible` | 主要推理 Provider 類型 (`openai_compatible`) |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | OpenAI 相容端點 Base URL |
| `OPENAI_API_KEY` | *(無)* | 對應端點的 API Key |
| `PRIMARY_MODEL` | `gpt-4o-mini` | 主要萃取與摘要所使用的模型名稱 |
| `GEMINI_API_KEYS` | *(無)* | Gemini API 金鑰清單（支援多組 Key 以逗號分隔輪詢） |
| `GEMINI_MODEL` | `gemini-2.5-flash` | 用於 YouTube 原生多模態串流解析的模型 |
| `DATABASE_PATH` | `omnikeep.db` | 本地 SQLite 資料庫路徑（自動開啟 WAL 模式） |
| `RADAR_ENABLED` | `false`（新安裝範例） | 是否啟用情報雷達巡檢排程；準備好資料源後再啟用 |
| `RADAR_INTERVAL_SECONDS` | `10800` | 雷達自動巡檢週期（預設 3 小時） |
| `BACKUP_SINK` | `local` | 備份方案：`local`（本機輪替）、`rclone`（雲端同步）、`git`、`off` |
| `TELEGRAM_BOT_TOKEN` | *(無)* | Telegram Ingestion Bot Token（選填） |
| `TELEGRAM_ALLOWED_USER_IDS` | *(無)* | 授權使用 Bot 的 Telegram 用戶數值 ID（選填） |

---

## 🗺️ 產品路線圖

- [x] **v1.0：全通路採集與兩段式認知閉環**
  - [x] FastAPI + SQLite WAL 高併發儲存與 Unicode61 FTS5 全文檢索
  - [x] YouTube 免下載原生多模態串流解析（Gemini 2.5 Flash 輪詢池）
  - [x] Bilibili 雙軌長影片語音抽取（官方 CC 字幕 + DASH 音訊 本地 Whisper）
  - [x] 社群短影音雙軌識別（Instagram / TikTok / Shorts OCR + 語音）
  - [x] trafilatura 深度清洗與抗腐快照存儲（Link-rot Proof Snapshot）
  - [x] 雙模 Model Context Protocol (MCP stdio & SSE) 直連 IDE Agent
  - [x] Telegram / LINE 私人雙向 Bot 隨手轉發入庫
  - [x] 響應式 Web 看板（Vite + Vue 3 + Tailwind v4 + PWA）
- [x] **v1.5：自主情報雷達與個人化品味**
  - [x] RSS / HackerNews / GitHub Trending 主動巡檢引擎
  - [x] 個人興趣向量特徵畫像（User Interest Profile）與動態評分
  - [x] 雷達自訂巡檢頻率與靜默歸檔策略
  - [x] 本地向量語意檢索（sqlite-vec）
- [ ] **v2.0：對話式第二大腦與多端擴充 (In Progress)**
  - [ ] 知識庫 RAG 對話助手（Chat with your Brain）
  - [ ] Chrome / Edge 官方瀏覽器側邊欄擴充功能
  - [ ] 知識圖譜關聯可視化（Knowledge Graph View）

---

## 🤝 參與貢獻 (Contributing)

歡迎提交 Issue 與 Pull Request！
1. Fork 本專案
2. 建立新分支 (`git checkout -b feature/amazing-feature`)
3. 提交變更 (`git commit -m 'feat: Add amazing feature'`)
4. 推送分支 (`git push origin feature/amazing-feature`)
5. 發起 Pull Request

---

## 📄 開源授權 (License)

本專案基於 [MIT License](LICENSE) 條款開源發布。
