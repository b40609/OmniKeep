# OmniKeep 行動端無縫採集與 PWA 配置指南（iOS (iPhone / iPad) & Android）

本指南提供在手機上將 OmniKeep 打造成等同原生 App 體驗的完整配置（**路線 A：PWA + iOS 捷徑 / LINE Bot 採集**），支援 **網址/影片** 與 **自選段落筆記** 雙軌一鍵收錄。

---

## 方案 1：iOS 原生分享表單捷徑 (Share Sheet)（iOS Shortcut）

透過 iOS 內建「捷徑」，無須安裝任何第三方 App。在 Safari、X (Twitter)、YouTube、Threads 或閱讀長文時選取段落，點擊「分享」即可秒級存入。

### 1. 事前準備
1. **主機伺服器** 啟動 Tailscale / 區域網路，確認你的主機實際 IP，且 OmniKeep 正在執行（Port 5000）。Docker 使用者若要在區網存取，需在 `.env` 設定 `BIND_ADDRESS=0.0.0.0`；直接使用 Python 啟動者則需設定 `HOST=0.0.0.0`。請透過防火牆或受信任 VPN 限制可連線對象。
2. **手機端** 開啟 Tailscale 或連入同一網路 連入同一 Tailnet。

### 2. 建立通用捷徑步驟（支援「分享表單」與「剪貼簿隨手存」）

1. 打開 iPhone 上的 **「捷徑」** App，右上角點擊 **「+」**。
2. 重新命名捷徑為 **「存入 OmniKeep」**，圖示設定為大腦或閃電。
3. 點擊下方 **「(i) 詳細資訊」**：
   * 開啟 **「在分享表單中顯示」**。
   * 「接收的內容類型」確保包含：**URL** 與 **文字**。
4. 設定動作鏈（Action Flow）：

   * **動作 1：條件判斷（有無分享輸入）**
     * 若「快捷方式輸入」沒有內容：
       * 動作：**「取得剪貼簿」**。
     * 設定變數：將輸入（分享內容或剪貼簿）命名為 `TargetContent`。

   * **動作 2：取得 URL 的內容（HTTP POST）**
     * 搜尋並加入：**「取得 URL 的內容」**。
     * **網址**：`http://[你的Tailscale_IP]:5000/api/ingest`
     * 展開「進階」：
       * **方法**：`POST`
       * **標頭 (Headers)**：
         * `Content-Type`: `application/json`
         * `X-API-Key`：從本機 `.env` 私下填入 `API_KEY`；換 key 後同步更新此標頭。
       * **要求主體 (Request Body)**：選擇 `JSON`
         * 新增欄位 1：`url`（文字）= 選擇變數 `TargetContent`
         * 新增欄位 2：`async_mode`（布林值）= `True`（秒級回傳，背景非同步雙層萃取，手機零等待）

   * **动作 3：觸覺震動與通知**
     * 搜尋並加入：**「觸覺回饋」**（選擇「成功」）。
     * 搜尋並加入：**「顯示通知」**：
       * 標題：`OmniKeep`
       * 內文：`⚡ 情報已存入！雙層解構進行中...`

5. 點擊右上角 **「完成」**。

---

## 方案 2：iPhone / Android PWA「加入主畫面」（獨立 App 體驗）

OmniKeep 具備完整 PWA（Progressive Web App）標準支援，安裝後即為獨立全螢幕 App，無瀏覽器網址列干擾。

**安裝條件**：PWA 的 Service Worker 通常要求 HTTPS 安全來源，只有 `localhost` 等開發環境例外。手機使用區網 `http://[IP]:5000` 時，可能無法安裝 PWA 或使用離線功能；請優先透過受信任的 HTTPS 網址連線，確認瀏覽器顯示「加入主畫面／安裝應用程式」後再安裝。HTTP 可供受保護網路的基本網頁操作，但不保證 PWA 安裝能力。

### iOS (iPhone / iPad) 操作步驟：
1. 用 Safari 開啟 `http://[你的Tailscale_IP]:5000`。
2. 點擊 Safari 底部工具列中央的 **「分享（Share）」** 圖示。
3. 向下滾動並點擊 **「加入主畫面 (Add to Home Screen)」**。
4. 名稱確認為 `OmniKeep`，點擊右上角「新增」。
5. **體驗亮點**：
   * **全螢幕獨立視窗**：無頂部網址列與底部導航欄，比照原生 iOS App。
   * **動態島與 Safe Area 自動適配**：黑色沉浸式狀態列（`black-translucent`），完全避開動態島／瀏海與底部安全橫條。
   * **單手回退設計**：點進任何文章，左上角提供醒目「← 清單」大拇指觸控鍵，流暢回退工作台。
   * **離線 App Shell 快取**：內建 Service Worker (`sw.js`)，瞬時秒開。

### Android 手機操作步驟：
1. 用 Chrome 開啟 `http://[你的Tailscale_IP]:5000`。
2. 頁面頂部將自動浮現 **「安裝 App」** 按鈕（或點選 Chrome 右上角選單 ➔「安裝應用程式」）。
3. 確認後，桌面即生成獨立 OmniKeep App 圖示。

---

## 方案 3：LINE 私人 Bot 隨手轉發（免捷徑、跨裝置通用）

如果不便使用 iOS 捷徑，可直接將資訊轉傳給綁定的 **OmniKeep LINE 官方帳號**：

1. 在任何 App 看到想存的網址或文字段落，直接「分享 ➔ 傳送至 LINE」。
2. 選擇「OmniKeep Bot」。
3. 後端 Win11 自動驗證簽章並進行萃取，分析完成後自動回傳暗黑風格 **Flex Message 結構化卡片**（包含白話重點、分類與標籤）。
4. 詳細設定步驟請參考 [LINE Bot 設定指南](line_bot.md)。
