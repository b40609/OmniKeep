# 🧠 OmniKeep

> **Self-hosted Multimodal Information Radar & Second Brain for High-Performing Engineers.**  
> 自託管多模態情報雷達與兩段式第二大腦：一鍵收集、雙層速覽、原文封存與智慧檢索。

[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115%2B-009688.svg)](https://fastapi.tiangolo.com)
[![SQLite WAL](https://img.shields.io/badge/SQLite-WAL%20Mode-003B57.svg)](https://sqlite.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

---

## 🌟 核心特色 (Core Features)

1. **零摩擦全通路輸入**：
   - **iPhone 17 Pro**：透過原生 iOS「捷徑（Share Sheet）」一鍵推送到後端，零安裝、零佔用空間。
   - **電腦端（Win11 PC / 筆電）**：響應式 Web 看板（PWA），或直接透過 API / 瀏覽器存入。
2. **兩段式分層速覽（Two-Stage Triage）**：
   - **L1 速覽層**：卡片直觀呈現「直擊本質的標題 + 1-2句白話痛點與核心論點 + 5個新技術項標籤」，告別廢話。
   - **L2 深入層**：點擊卡片秒開深度技術架構解構、規格清單、程式碼細節與 **Markdown 原文純淨閱讀器（Reader View）**。
3. **開源標準化解耦（Open-Source Ready）**：
   - **OpenAI-Compatible Provider**：無縫支援 Agnes AI、原生 OpenAI、DeepSeek 或本機 Ollama。
   - **Google Gemini Provider**：多組 API Key 自動輪詢（Round-Robin），原生秒級解析 YouTube 長影片，主機零下載、零頻寬佔用。
4. **靈活動態分類（Dynamic Taxonomy）**：
   - 預設核心領域（`AI`、`加密貨幣`、`台股`、`Github`、`時事`、`旅遊`、`美食`），支援前端即時新增/刪除分類字典，AI 自動歸流。
5. **超極速全文檢索（FTS5 Search）**：
   - SQLite 內建 WAL 模式與 Unicode61 FTS5 全文索引，毫秒級即時搜尋白話重點與原文。

---

## 🏗️ 系統架構 (System Architecture)

```
[iPhone 17 Pro (iOS 捷徑)]  [筆電/電腦瀏覽器 (PWA)]
           │                            │
           └─────────────┬──────────────┘
                         ▼ (Tailscale 私網直連 / 5G 外網)
          [Win11 PC: OmniKeep FastAPI 服務]
                         │
        ┌────────────────┼────────────────┐
        ▼                ▼                ▼
[YouTube 直連解析] [技術長文/網頁萃取] [SQLite WAL + FTS5]
(Gemini 原生影片)   (trafilatura 清洗)   (雙層結構化存儲)
        │                │
        └───────┬────────┘
                ▼
       [AI Provider 調度]
(Agnes AI / OpenAI / Gemini Pool / Ollama)
```

---

## 🚀 快速啟動 (Quickstart)

### 1. 安裝依賴
```powershell
pip install -r requirements.txt
```

### 2. 設定環境變數
複製 `.env.example` 為 `.env`：
```powershell
cp .env.example .env
```
編輯 `.env` 並填入你的 Key：
```env
# 核心服務設定
PORT=5000
API_KEY=omnifs888

# 主要 LLM (支援 Agnes AI、OpenAI、DeepSeek 等)
PRIMARY_LLM_PROVIDER=openai_compatible
OPENAI_BASE_URL=https://platform.agnes-ai.com/v1
OPENAI_API_KEY=your_key_here
PRIMARY_MODEL=gpt-4o

# Google Gemini (用於 YouTube 免下載原生解析，支援多組 Key 逗號分隔)
GEMINI_API_KEYS=key1,key2,key3
GEMINI_MODEL=gemini-2.5-flash
```

### 3. 啟動服務
```powershell
python run.py
```
* **Web 看板**：`http://localhost:5000`
* **Swagger API 文件**：`http://localhost:5000/docs`

---

## 🎨 前端開發 (Web Workbench)

Web 看板已升級為 **Vite + Vue 3 SFC + Tailwind v4 + Reka UI (shadcn-vue 風格)** 的正規前端工程，位於 `frontend/`，構建產物輸出至 `static/dist/` 由 FastAPI 直接服務。

### 開發流程
```powershell
# 一次性安裝（Node 20+）
cd frontend && npm install

# 開發模式（HMR，API 自動代理到 localhost:8000）
npm run dev

# 生產構建（含型別檢查；輸出 ../static/dist/）
npm run build
```
> 若 `esbuild` 安裝腳本被 npm 安全策略攔截，執行 `npm approve-scripts esbuild` 後 `npm rebuild esbuild`。

### 架構總覽
| 層 | 位置 | 說明 |
|---|---|---|
| Design Tokens | `src/assets/main.css` | 語義化 CSS variables，深色為本＋淺色雙主題 |
| API 客戶端 | `src/lib/api.ts` | 型別化契約層，對齊 FastAPI 路由 |
| 樂觀更新 | `src/composables/useMutations.ts` | 星標/封存/刪除即時反應 + toast 復原（undo） |
| 鍵盤操控 | `src/composables/useKeyboard.ts` | J/K/E/S/Enter/Esc///N/R/?/+/- 全快捷鍵 |
| 虛擬滾動 | `src/components/items/ItemList.vue` | virtua VList（ssrCount 保底渲染） |
| 手機手勢 | `SwipeableRow.vue` / ReaderPane Sheet | 橫滑星標/封存、下滑關閉閱讀器 |
| PWA | vite-plugin-pwa | SW 於 `/static/dist/sw.js`，FastAPI 附 `Service-Worker-Allowed: /` |

### 主題與環境變數
- 主題持久化於 `localStorage`（`omnikeep-theme`: dark / light / system）。
- 存入 API Key 可用 `VITE_INGEST_KEY` 覆寫（預設 `omnifs888`，與後端 `API_KEY` 對應）。

### 回滾
升級前的單檔版 UI 保留於 `static/index-legacy.html`，將 `app/main.py` 的 `serve_dashboard` 指回該檔即可還原。

## 📱 iPhone 17 Pro 捷徑配置

請參閱詳細教學文件：[docs/ios_shortcut.md](docs/ios_shortcut.md)。
只需在 iOS 捷徑中建立一個接收 Share Sheet URL 並發送 HTTP POST 到你的 Tailscale 內網 IP 的捷徑，即可達成隨手存入。

---

## 🗺️ 開發里程碑 (Roadmap)

- [x] **Phase 1: MVP 核心閉環**
  - [x] FastAPI + SQLite WAL 底座與 FTS5 全文檢索
  - [x] 解耦式 Provider 架構 (OpenAI-compatible & Gemini Pool)
  - [x] YouTube 原生影片與技術文章雙層解析流水線
  - [x] 動態分類字典管理
  - [x] 跨端 PWA 響應式卡片看板與 L2 閱讀器
  - [x] iOS 捷徑規格文檔
- [ ] **Phase 2: 智慧進化與主動情報**
  - [ ] 個人興趣向量特徵畫像 (User Interest Profile)
  - [ ] GitHub Trending / HackerNews / RSS 主動巡邏與「為你推薦」專區
  - [ ] 對話式第二大腦 (Chat with your Brain / RAG)
  - [ ] Chrome / Edge 瀏覽器擴充功能

---

## 📄 License
MIT License.
