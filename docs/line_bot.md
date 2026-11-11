# 🟢 OmniKeep LINE 私人隨手採集 Bot

針對台灣用戶最熟悉的 **LINE** 生態，OmniKeep 原生支援 **LINE Messaging API**。
在手機上瀏覽任何 App（Safari、X、YouTube、PTT、臉書、Thread、LINE 群組）時，直接「**分享傳給你的 LINE Bot**」，後端秒級完成 L1/L2 結構化提煉，並以高質感的 **LINE 暗黑 Flex 卡片** 即時回傳！

---

## 🚀 3 步極速配置指南

### 第一步：在 LINE Developers 建立免費 Bot
1. 前往 **[LINE Developers Console](https://developers.line.biz/)** 並以你的 LINE 帳號登入。
2. 建立或選擇一個 Provider（例如：`Example Provider`）。
3. 點擊 **Create a new channel**，選擇 **Messaging API**：
   - Channel name：`OmniKeep`（或任意你喜歡的名稱）
   - Channel description：`My AI Second Brain`
   - Category：`Other`
4. 進入剛建好的 Channel 頁面，取得兩組關鍵憑證：
   - **Basic settings 頁籤**：複製 **`Channel secret`**。
   - **Messaging API 頁籤**：滑到最下方，點擊 Issue 取得 **`Channel access token (long-lived)`**。
5. 把這兩組憑證填進 OmniKeep：打開側欄底部的「設定」，切到「LINE」分頁，貼上 **Channel Secret** 與 **Channel Access Token**，按儲存。
   - 儲存後立即生效，不用重啟。憑證會加密後存進資料庫，之後只顯示末四碼。
   - 同一頁的「測試 LINE Bot」可以確認 Token 有沒有效。
   - 寫在 `.env` 的 `LINE_CHANNEL_SECRET`、`LINE_CHANNEL_ACCESS_TOKEN` 是舊做法，仍然有效；設定頁存的值優先。

---

### 第二步：設定 Webhook URL（只把 webhook 這一條路徑對外）

LINE 平台要從網際網路呼叫你的 webhook。網址必須是 HTTPS，憑證要由一般瀏覽器信任的憑證機構簽發，不接受自簽憑證（[LINE 官方文件](https://developers.line.biz/en/docs/messaging-api/building-bot/)）。

OmniKeep 的 webhook 路徑是 `/api/line/webhook`（`app/routers/line_webhook.py`）。這條路徑不用存取金鑰，改成檢查 LINE 的簽章：簽章不對就回 400。

**只把 `/api/line/webhook` 對外，不要把整個 OmniKeep 對外。** `tailscale funnel 5000`、`ngrok http 5000` 這類寫法會把整個服務（登入頁、API、MCP）公開到網際網路，不要用。

下面兩個方案的指令是照官方文件與 Tailscale 原始碼整理的，**還沒有在實機上完整跑過（待驗證）**。設定後請照各方案最後的檢查步驟確認。

#### 方案 A：Tailscale Funnel，只掛 webhook 路徑

前提：Tailscale 1.38.3 以上，tailnet 已開啟 MagicDNS 與 HTTPS 憑證，tailnet policy 裡有 `funnel` 節點屬性。Funnel 只能用 443、8443、10000 這三個埠。

```powershell
tailscale funnel --bg --https=8443 --set-path=/api/line/webhook http://127.0.0.1:5000/api/line/webhook
```

- `--set-path` 是對外的路徑。目標要寫完整網址（含路徑）：Tailscale 轉送前會把掛載路徑去掉，目標不帶路徑的話，OmniKeep 收到的會是 `/`。
- 用 8443，不要用 443。同一個埠不能同時給 Serve 和 Funnel 用：最後一次設定是 `funnel`，整個埠就會公開。如果你照 [Tailscale 部署文件](tailscale_pwa_deploy.md) 用 `tailscale serve --bg 5000` 把 OmniKeep 開在 443 給自己的裝置，再對 443 下 `funnel`，就會把整個 OmniKeep 公開。
- `--bg` 讓設定常駐。要關掉：`tailscale funnel --https=8443 --set-path=/api/line/webhook off`。
- Webhook URL 是 `https://<主機名>.<tailnet 名>.ts.net:8443/api/line/webhook`。LINE 的文件沒有列出埠號限制；8443 能不能用還沒有實測（待驗證），在 LINE Developers Console 按 **Verify** 就能確認。

檢查：

```powershell
tailscale funnel status
```

確認對網際網路公開的只有 8443 上的 `/api/line/webhook`。再從 tailnet 外面（例如手機關掉 Tailscale、改用行動網路）試：

```bash
curl -i https://<主機名>.<tailnet 名>.ts.net:8443/                          # 預期 404：其他路徑沒有對外
curl -i -X POST https://<主機名>.<tailnet 名>.ts.net:8443/api/line/webhook  # 預期 400：有到 OmniKeep，但簽章不對
```

第一行如果看得到 OmniKeep 的頁面，表示整個服務被公開了：立刻執行 `tailscale funnel reset`，再檢查指令。

#### 方案 B：Cloudflare Tunnel，用 ingress 規則限定路徑

在 `cloudflared` 的設定檔裡，用 `path` 只放行 webhook，其餘一律回 404：

```yaml
tunnel: <Tunnel-UUID>
credentials-file: <憑證檔路徑>

ingress:
  - hostname: line.example.com
    path: ^/api/line/webhook$
    service: http://127.0.0.1:5000
  - service: http_status:404
```

- `path` 是正規表示式。`cloudflared` 只拿它來比對，轉送時路徑原樣送到 OmniKeep，不會去掉前綴。
- 最後一定要有一條不帶條件的規則；`http_status:404` 讓其他路徑直接回 404。
- 檢查設定：`cloudflared tunnel ingress validate`。看某個網址會落到哪一條規則：`cloudflared tunnel ingress rule https://line.example.com/api/line/webhook`，再換成 `https://line.example.com/` 試一次，應該落到 404 那一條。
- 建立通道、把主機名稱指到通道的步驟，請照 Cloudflare 官方文件。
- Webhook URL 是 `https://line.example.com/api/line/webhook`。

#### 其他通道工具

原則一樣：能限定只轉送 `/api/line/webhook` 才用，做不到就不要用。

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
4. 打開「設定」的「LINE」分頁，把這串 ID 填進「允許的 LINE User ID」（多個用逗號分隔），按儲存。立即生效，不用重啟。
   - Bot 回覆的訊息寫的是「填入 `.env` 的 `LINE_ALLOWED_USER_IDS`」，那是舊做法，仍然有效；設定頁存的值優先。
5. 綁定完成。之後只有清單裡的帳號能用這個 Bot，其他人傳訊息會被拒絕，不會用到你的 AI 額度。

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

---

## 參考資料

- LINE：webhook 網址要用 HTTPS、憑證要由受信任的憑證機構簽發、不接受自簽憑證，以及在 Console 設定與 Verify 的步驟：<https://developers.line.biz/en/docs/messaging-api/building-bot/>
- LINE：處理 webhook 事件前要先驗證簽章：<https://developers.line.biz/en/docs/messaging-api/receiving-messages/>
- Tailscale Funnel（公開到網際網路、前提、只能用 443／8443／10000、同一個埠不能同時給 Serve 和 Funnel）：<https://tailscale.com/kb/1223/funnel>
- `tailscale funnel` 指令（`--bg`、`--https`、`--set-path`、目標可以寫含路徑的完整網址、`off`、`status`、`reset`）：<https://tailscale.com/kb/1311/tailscale-funnel>
- Tailscale 轉送前會去掉掛載路徑（`serveWebHandler` 裡的 `http.StripPrefix`）：<https://github.com/tailscale/tailscale/blob/main/ipn/ipnlocal/serve.go>
- Cloudflare Tunnel 設定檔（`ingress` 規則、`path` 是正規表示式、轉送時不改路徑、最後要有 catch-all、`http_status:404`、`cloudflared tunnel ingress validate` 與 `rule`）：<https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/local-management/configuration-file/>
