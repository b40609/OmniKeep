# OmniKeep - iPhone 17 Pro 原生捷徑 (iOS Shortcut) 配置指南

透過 iOS 內建的「捷徑（Shortcuts）」App，無需安裝任何第三方 App，即可在 Safari、YouTube、X (Twitter)、Instagram 或任何支援「分享」的 App 中，將網址一鍵送入你的 OmniKeep 進行雙層分析。

---

## 1. 事前準備（連線通暢）

* 確保你的 **Win11 主機** 已安裝並啟動 **Tailscale**。
* 確保你的 **iPhone 17 Pro** 已開啟 **Tailscale** 並登入同一帳號。
* 查看 Win11 主機的 Tailscale 內網 IP（例如：`100.115.88.99`，可在 Tailscale App 或終端機 `tailscale ip -4` 查看）。

---

## 2. 建立 iOS「捷徑」步驟（3 分鐘搞定）

1. 打開 iPhone 上的 **「捷徑」** App。
2. 點擊右上角的 **「+」** 新增捷徑。
3. 命名捷徑為 **「存入 OmniKeep」**，圖示可選大腦或雷達符號。
4. 點擊下方的 **「(i) 詳細資訊」** ➔ 開啟 **「在分享表單中顯示」**。
5. 在「接收」設定中，確保勾選 **「URL」** 與 **「文字」**。

### 加入以下動作鏈（Action Flow）：

* **動作 1：取得 URL**
  * 搜尋並加入動作：**「從輸入中取得 URL」**。
  * 輸入來源選擇：`快捷方式輸入`。

* **動作 2：取得 URL 內容（發送 HTTP POST）**
  * 搜尋並加入動作：**「取得 URL 的內容」**。
  * **網址**：填入 `http://[你的Tailscale內網IP]:5000/api/ingest?token=omnifs888`
    *(例如：`http://100.115.88.99:5000/api/ingest?token=omnifs888`)*
  * 展開「進階」設定：
    * **方法**：`POST`
    * **標頭 (Headers)**：
      * `Content-Type`: `application/json`
      * `X-API-Key`: `omnifs888`
    * **要求主體 (Request Body)**：選擇 `JSON`
      * 新增欄位：
        * 鍵 (Key)：`url`
        * 類型：`文字`
        * 值 (Value)：點擊變數選擇 **「URL」**（動作 1 的輸出）
        * 鍵 (Key)：`async_mode`
        * 類型：`布林值 (Boolean)`
        * 值 (Value)：`True`（秒級回傳，背景非同步運算，手機零等待）

* **動作 3：顯示通知**
  * 搜尋並加入動作：**「顯示通知」**。
  * 內容設定為：`⚡ 已送入 OmniKeep 情報雷達進行雙層分析！`

6. 點擊右上角 **「完成」** 儲存。

---

## 3. 日常使用體驗

1. 在 iPhone 的 **YouTube App**、**Safari** 或 **X** 上看到有價值的技術或內容。
2. 點擊 **「分享（Share）」** 按鈕。
3. 在分享選單清單中點擊 **「存入 OmniKeep」**。
4. 1 秒內頂部跳出橫幅通知，後端 Win11 主機開始自動分層萃取。
5. 手機開啟 Safari 進入 `http://[Tailscale_IP]:5000` 並點擊「分享 ➔ 加入主畫面」（PWA），即可像原生 App 一樣隨時檢索與閱讀。
