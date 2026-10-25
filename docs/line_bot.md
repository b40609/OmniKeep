# 🟢 OmniKeep LINE 私人隨手採集 Bot

針對台灣用戶最熟悉的 **LINE** 生態，OmniKeep 原生支援 **LINE Messaging API**。
在手機上瀏覽任何 App（Safari、X、YouTube、PTT、臉書、Thread、LINE 群組）時，直接「**分享傳給你的 LINE Bot**」，後端秒級完成 L1/L2 結構化提煉，並以高質感的 **LINE 暗黑 Flex 卡片** 即時回傳！

---

## 🚀 3 步極速配置指南

### 第一步：在 LINE Developers 建立免費 Bot
1. 前往 **[LINE Developers Console](https://developers.line.biz/)** 並以你的 LINE 帳號登入。
2. 建立或選擇一個 Provider（例如：`Ryan Personal`）。
3. 點擊 **Create a new channel**，選擇 **Messaging API**：
   - Channel name：`OmniKeep`（或任意你喜歡的名稱）
   - Channel description：`My AI Second Brain`
   - Category：`Other`
4. 進入剛建好的 Channel 頁面，取得兩組關鍵憑證：
   - **Basic settings 頁籤**：複製 **`Channel secret`**。
   - **Messaging API 頁籤**：滑到最下方，點擊 Issue 取得 **`Channel access token (long-lived)`**。
5. 開啟 `c:\Users\user\Desktop\OmniKeep\.env`，填入：
   ```env
   LINE_CHANNEL_SECRET=你的ChannelSecret
   LINE_CHANNEL_ACCESS_TOKEN=你的ChannelAccessToken
   ```

---

### 第二步：設定 Webhook URL（對外 HTTPS 通道）
LINE 伺服器要求 Webhook 必須為 **公開 HTTPS 網址**。你有以下兩種最推薦的工程師方案：

#### 方案 A：使用 Tailscale Funnel（最推薦，極簡穩定）
若你的 PC 已安裝 Tailscale，直接在 PowerShell 執行：
```powershell
tailscale funnel 5000
```
你會獲得一組專屬 HTTPS 網址（例如：`https://your-node.tailscale.net`）。

#### 方案 B：使用 Cloudflare Tunnel / ngrok
若使用 ngrok：
```powershell
ngrok http 5000
```

取得網址後：
1. 回到 LINE Developers 的 **Messaging API** 頁籤。
2. 在 **Webhook URL** 填入：
   ```
   https://你的公開網址/api/line/webhook
   ```
3. 開啟 **Use webhook** 開關（Toggle 設為 On）。
4. 在同頁面的 **LINE Official Account features**：
   - 點擊 Edit 將「Auto-reply messages（自動回應訊息）」設為 **Disabled**（避免官方預設罐頭訊息干擾）。

---

### 第三步：掃碼加好友並綁定你的 LINE User ID
1. 在 Messaging API 頁籤用手機 LINE 掃描 **QR code** 加入你的 Bot 好友。
2. 對 Bot 發送任何訊息（例如：`Hello` 或 `/help`）。
3. Bot 會自動回傳你的專屬 LINE User ID（以 `U` 開頭的字串，例如 `U1234567890abcdef...`）：
   > ⚠️ **OmniKeep LINE Bot 尚未綁定擁有者**  
   > 你的 LINE User ID 是：`U1234567890abcdef...`
4. 將該字串填入 `.env`：
   ```env
   LINE_ALLOWED_USER_IDS=U1234567890abcdef...
   ```
5. 完成私人綁定！從此該 Bot 僅限你一人專用，其他人傳訊息會被立即拒絕，絕不消耗你的 AI 額度。

---

## 📱 LINE 專屬互動功能

1. **隨手傳送連結或長文**：
   - 傳送 URL 或剪貼簿段落，LINE 頂端會出現載入動畫（跳動三圓點）。
   - 解析完成後以 **LINE Dark Flex Message** 回傳結構化情報卡片。
2. **卡片下方按鈕**：
   - `[☆ 加星標 / ⭐ 已星標]`：即時更新 SQLite 標記。
   - `[📦 封存 / ✅ 已封存]`：看完隨手按「封存」，保持待讀 Inbox 清空。
   - `[🌐 原始頁]`：一鍵在 LINE 內建瀏覽器打開原始網頁。
3. **指令支援**：
   - 輸入「`庫存`」或 `/stats`：查看當前大腦未讀數與總計。
   - 輸入「`待讀`」或 `/inbox`：調出最近未讀情報卡。
   - 輸入「`說明`」或 `/help`：查看使用說明。
