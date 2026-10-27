# 🧠 OmniKeep 專案交接手冊（交接給 ZCode / GLM-5.3）

> 此為舊版開發交接紀錄，環境與測試數字已過時。公開安裝請以 [README](README.md) 和 [iOS 設定指南](docs/ios_shortcut.md) 為準。

> **專案定位**：自託管多模態情報雷達與兩段式第二大腦（Self-hosted Multimodal Information Radar & Second Brain）。  
> **交接目標**：全面進行 UI/UX 頂級精緻化升級，使介面視覺、動效、觸感與操作流暢度達到如 **Linear、Raycast、Readwise Reader、Superhuman** 等開源或商業收費款軟體的頂級水準。

---

## 🏗️ 1. 系統現況與運行環境 (Current Runtime Matrix)

* **專案目錄**：使用目前 Git clone 的專案根目錄；歷史本機路徑及 Junction 不適用於新安裝。
* **後端架構**：FastAPI + SQLite (WAL Mode + Unicode61 FTS5 全文檢索)
* **核心服務端口**：`http://localhost:5000`（API Docs: `http://localhost:5000/docs`）
* **啟動指令**：`python run.py`
* **整合通道**：
  * **PWA & Web 看板**：`static/index.html`（Vue 3 CDN + Tailwind CSS CDN，單檔 SPA 架構）
  * **iOS 分享捷徑（Share Sheet）**：`POST /api/ingest`，在 `X-API-Key` 標頭傳送自己的金鑰，支援 `async_mode=true`。
  * **Telegram Bot**：`python -X utf8 run_bot.py`（長輪詢模式）
  * **LINE Bot**：`app/bot/line_bot.py`（暗黑 Flex Message 卡片）
  * **MCP Server**：`mcp_server.py`（雙模：本機 stdio + 遠端 SSE，支援 8 項 Tools + 2 項 Resources）
  * **情報雷達 (Radar)**：`app/radar/`（定時巡邏 GitHub Trending, YouTube, RSS）
* **測試套件**：全量 32 項單元測試 100% 通過（執行 `pytest` 即可驗證）

---

## 🎨 2. UI/UX 升級核心使命 (Premium Quality Blueprint)

現行前端（`static/index.html`）功能閉環已健全，但視覺層面仍偏向傳統 Dashboard。接下來交由 **ZCode (GLM-5.3)** 進行全方位的「質感昇華」，使其成為業界標竿等級的工程師桌面與行動端應用：

### 2.1 視覺層次與設計語彙 (Design Tokens & Visual Polish)
1. **極致微光邊框 (Subtle 1px Border Glow)**：
   * 告別粗糙的 `border-zinc-800`，全面升級為 Radix / Linear 式的細緻高光邊框（`border-white/[0.08]`、卡片 Hover 時產生微光擴散與 `border-zinc-600/40`）。
2. **深度玻璃態與毛玻璃導航 (Refined Glassmorphism)**：
   * 頂部搜尋列與浮動面板採用高透光微模糊（`backdrop-blur-xl bg-zinc-950/80 border-b border-white/[0.06]`）。
3. **字體排印與標籤膠囊 (Typography & Tag Capsules)**：
   * 中英混排字距微調（Inter / -apple-system + Noto Sans TC），標籤膠囊採用微漸變半透明底色，避免視覺生硬。

### 2.2 全域命令列 (Raycast / Linear Style Command Palette `Cmd+K`)
* **快捷鍵喚起**：按下 `Cmd+K` 或 `Ctrl+K` 即刻叫出居中毛玻璃命令面板。
* **支援動作**：
  * 全域模糊搜尋（Fuzzy Filter 立即跳轉至特定情報）。
  * 快速切換分類（AI、加密貨幣、GitHub、台股等）。
  * 快捷指令：觸發「跨篇 AI 架構綜述」、一鍵將 Inbox 標記為已讀、切換列表密度、開啟匯出對話框。

### 2.3 物理動態與微互動反饋 (Tactile Physics & Micro-interactions)
1. **觸感反饋 (Haptic-like Feedback)**：
   * 所有按鈕、卡片點擊加入彈性微縮放（`active:scale-[0.98]`、平滑彈簧貝茲曲線 `cubic-bezier(0.16, 1, 0.3, 1)`）。
2. **骨架屏動效 (Shimmer Skeleton Loaders)**：
   * 載入列表時使用微光流動骨架屏，徹底取代生硬的「載入中...」文字。
3. **Sonner 風格堆疊式 Toast 系統**：
   * 替換瀏覽器原生 `alert()`，建立右上角/頂部浮動 Toast 通知：支援成功、錯誤、佇列中狀態，附帶進度條與「復原 (Undo)」操作按鈕。

### 2.4 L2 技術閱讀器極致昇華 (Readwise Reader Quality)
1. **目錄導航 (Floating Table of Contents)**：
   * L2 Modal 側邊自動提取 Markdown 標題（H1/H2/H3）生成懸浮目錄，支援滾動高亮（Scrollspy）。
2. **程式碼語法高亮 (Code Syntax Highlighting)**：
   * 整合輕量級 Prism.js 或 Highlight.js，自動高亮 Python、TypeScript、Bash 等代碼，右上角附帶「一鍵複製」與語言徽章。
3. **閱讀舒適度微調 (Reader Ergonomics)**：
   * 閱讀器頂部提供字級放大/縮小、行距切換（寬鬆/緊湊）、一鍵複製 L1 白話重點卡片。

### 2.5 行動端觸控與手勢最佳化 (Mobile Touch & PWA)
1. **手勢滑動操作 (Swipe Actions)**：
   * 卡片支援手機端左右滑動手勢：向右滑動加星標（⭐），向左滑動封存已讀（📥）。
2. **底部浮動微膠囊 (Floating Bottom Navigation Pill)**：
   * 手機直向瀏覽時，底部浮現沉浸式微膠囊導航（快速切換待讀、星標、搜尋、新增）。
3. **動態島與 Safe Area 像素級對齊**：
   * 完美適配 iPhone 17 Pro / 全螢幕手機的頂部瀏海與底部橫條。

---

## 📂 3. 核心檔案索引 (File Index for GLM-5.3)

| 檔案路徑 | 角色定位 | 調整重點 |
| :--- | :--- | :--- |
| `static/index.html` | 前端主介面（Vue 3 + Tailwind） | **主要升級目標**：注入 Cmd+K、Toast、骨架屏、視覺微光、L2 閱讀器增強 |
| `static/manifest.json` | PWA 配置清單 | 確保 `standalone` 顯示、主題色與圖示規格適配 |
| `static/sw.js` | Service Worker 快取 | 離線 App Shell 與靜態資源快取策略 |
| `static/mobile_test.html` | 行動端驗收站 | 手機連線測試站，已適配動態 origin |
| `app/main.py` | FastAPI 路由掛載 | 提供 `/api/items`、`/api/ingest`、`/mcp`、靜態目錄掛載 |
| `app/routers/items.py` | 情報與分類 API | 提供搜尋、過濾、星標與封存切換端點 |

---

## ⚡ 4. 接續開發執行清單 (ZCode Action Checklist)

- [ ] **Step 1: 視覺基礎重塑**
  - 在 `static/index.html` 中注入自訂 CSS 工具類（微光邊框、玻璃態 backdrop-blur、彈簧動畫曲線）。
- [ ] **Step 2: 注入 Sonner 風格 Toast 系統**
  - 取代現有 alert，提供精緻浮動通知與 Undo 支援。
- [ ] **Step 3: 打造 Command Palette (`Cmd+K`)**
  - 建立全域彈窗元件，監聽鍵盤快捷鍵，支援模糊搜尋與功能跳轉。
- [ ] **Step 4: L2 閱讀器升級**
  - 引入 Prism.js / Highlight.js 代碼高亮、自動提取 TOC 目錄與字級調整器。
- [ ] **Step 5: 骨架屏與微互動補強**
  - 為卡片列表、統計數字加上 Shimmer 載入骨架屏與點擊物理回彈。
- [ ] **Step 6: 本地與行動端回歸測試**
  - 於本機瀏覽器（`http://localhost:5000`）與手機端（PWA / Cloudflare Tunnel）驗證流暢度與響應式排版。
