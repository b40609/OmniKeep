# 用 Tailscale serve 從手機、平板、筆電連到 OmniKeep（PWA）

OmniKeep 跑在一台常開的 Windows 主機上，只綁本機 `127.0.0.1:5000`。iPhone、iPad、筆電透過 Tailscale 以 HTTPS 連線，並把 PWA 加到主畫面。整條路只在你的 tailnet 內，不對網際網路開放。

```
iPhone / iPad / 筆電 ──(tailnet)──> 主機上的 tailscaled :443（HTTPS，*.ts.net 憑證）
                                      └─> http://127.0.0.1:5000（OmniKeep，只綁本機）
```

> 本文件只描述設定步驟。安裝 Tailscale、修改系統設定，請由主機擁有者自行操作。

## 1. 前提

- 每台裝置都安裝 Tailscale，並登入同一個 tailnet。
- 主機已能啟動 OmniKeep（`run.bat`，或 `.venv\Scripts\python.exe run.py`）。
- 主機已建置前端：在 `frontend/` 執行 `npm ci`、`npm run build`。Service Worker 路由只在啟動時 `static/dist/` 已存在才會註冊（`app/main.py:135-146`），`/` 也要有 `static/dist/index.html` 才會回傳介面（`app/main.py:150-156`）。

## 2. OmniKeep 設定（主機的 `.env`）

| 變數 | 建議值 | 說明 |
|---|---|---|
| `HOST` | `127.0.0.1`（預設） | 不要改成 `0.0.0.0`。埠只開在本機，外部一律經 Tailscale。 |
| `PORT` | `5000`（預設） | 下面的 `tailscale serve` 指向這個埠。 |
| `LOCAL_AUTO_LOGIN` | 新安裝預設開啟（在「設定 › 系統」的「這台電腦免登入」切換） | 開啟時，同機瀏覽器可免輸入金鑰。經 Tailscale serve 進來的請求帶有 `X-Forwarded-For`、`Tailscale-*` 等標頭，一律不會自動登入（`app/routers/session.py`）；啟動時也會在 log 留一則警告。 |
| `CORS_ORIGINS` | 不用設 | PWA 與 API 同源。 |

手機第一次登入不必輸入 `API_KEY`：在電腦上已登入的 OmniKeep 開「設定 → 系統 → 手機登入」，用手機相機掃 QR code，或在手機的登入頁輸入畫面上的 8 碼配對碼。配對碼 5 分鐘內有效、只能用一次，裡面不含金鑰；打錯 5 次就作廢，要重新產生（`app/pairing.py`）。也可以照舊貼上 `API_KEY`。

## 3. Tailscale 管理後台（一次性）

1. 開啟 DNS 頁面：<https://console.tailscale.com/admin/dns>。
2. 開啟 **MagicDNS**。HTTPS 憑證需要它。
3. 在 **HTTPS Certificates** 選 **Enable HTTPS**。

注意：憑證會記錄在公開的 Certificate Transparency 帳本，裝置名稱與 tailnet DNS 名稱都會公開。主機名稱若含公司名、真名等敏感資訊，先在 Tailscale 後台改名，再取得憑證。

## 4. 主機設定

以下指令在主機的 PowerShell 或命令提示字元執行。

**讓 Tailscale 在沒人登入時也保持連線。** Windows 預設只在使用者登入期間連線；登出或重開機後，要等有人登入才會恢復。常開主機請開啟 unattended 模式：

```powershell
tailscale set --unattended=true
```

也可以從系統匣圖示操作：Preferences → Run unattended。

**用 serve 提供 HTTPS：**

```powershell
tailscale serve --bg 5000
```

- `5000` 代表反向代理到 `http://127.0.0.1:5000`；Tailscale serve 的代理目標只支援 `127.0.0.1`。
- `--bg` 讓設定常駐，重開機或 `tailscale down`／`up` 之後會自動恢復。
- 網址是 `https://<主機名>.<tailnet 名>.ts.net/`，可用 `tailscale serve status` 查看。
- **要掛在根路徑 `/`，不要加 `--set-path`。** 前端與 API 都用絕對路徑（`/static/...`、`/api/...`），Service Worker 的 scope 也是 `/`。
- **不要用 `tailscale funnel`。** Funnel 會把服務公開到網際網路。
- 要取消，在原指令後加 `off`（`tailscale serve --bg 5000 off`），或用 `tailscale serve reset` 清掉全部設定。

OmniKeep 本身也要保持執行，例如用 `scripts/watchdog.ps1` 搭配工作排程器。這部分不在本文件範圍。

## 5. 驗證

在 tailnet 內的另一台裝置（例如筆電）上執行：

```bash
curl https://<主機名>.<tailnet 名>.ts.net/health
curl https://<主機名>.<tailnet 名>.ts.net/api/session/local-auth
```

- 第一行應回 `{"status":"healthy",...}`。
- 第二行**必須**回 `{"authenticated":false,"api_key":""}`。即使主機的 `LOCAL_AUTO_LOGIN=true` 也一樣。若回傳了金鑰，立刻關掉 serve 並回報。

接著用瀏覽器開網址，用配對碼（第 2 節）或 `API_KEY` 登入。

## 6. 把 PWA 加到主畫面

**iPhone、iPad（Safari）**
1. 用 Safari 開 `https://<主機名>.<tailnet 名>.ts.net/` 並登入（掃手機登入的 QR code 會直接開到這裡並登入）。
2. 點分享按鈕（依分頁列配置，可能在頁面選單裡），選「加入主畫面」。
3. 新版 iOS 會出現以網頁 App 開啟的開關（英文介面是 Open as Web App），保持開啟，再點「加入」。
4. 從主畫面圖示開啟時會是獨立視窗。主畫面 App 和 Safari 不共用登入資料，第一次開啟要再登入一次：在電腦上再產生一組配對碼，輸入到 App 的登入頁。

圖示只會出現在操作的那台裝置；iPad 要另外加一次。

**筆電、桌機（Chrome、Edge）**
- 網址列右側的「安裝」圖示，或選單 ⋮ →「投放、儲存及分享」→「將網頁安裝為應用程式」。
- 瀏覽器提供安裝提示時，OmniKeep 頂部列也會出現安裝按鈕（`frontend/src/components/layout/AppHeader.vue:288-289`）。

## 7. Service Worker 與 manifest 在 ts.net 下能不能運作

可以，條件都符合：

- **先決修正**：`290b783` 之前，靜態檔白名單擋掉了 `sw.js` 載入的 Workbox 執行庫，Service Worker 在任何網址都裝不起來。請確認主機的程式包含這個修正，並重新 `npm run build`。
- **安全來源**：Service Worker 只在 HTTPS（或 localhost）運作。`*.ts.net` 用的是 Let's Encrypt 簽發的公開信任憑證，所以是安全來源。
- **scope**：Service Worker 檔案在 `/static/dist/sw.js`，以 scope `/` 註冊（`frontend/src/main.ts`）。伺服器回應帶 `Service-Worker-Allowed: /`（`app/main.py:136-146`），跟網域名稱無關。
- **確認方式**：在筆電的 Chrome 或 Edge 開 ts.net 網址，DevTools → Application → Service Workers 應看到 `/static/dist/sw.js` 為 activated。
- **manifest**：`static/manifest.json` 的 `start_url`、`scope` 都是 `/`，`display` 是 `standalone`，都是相對於來源的路徑，換成 ts.net 網域不需要修改。
- **圖示**：manifest 圖示與 iOS 的 `apple-touch-icon` 都來自 repo 內的 `frontend/public/`，建置後由 `/static/dist/` 提供，不依賴外部網路。改圖時編輯 `frontend/public/favicon.svg`，再執行 `npm run generate-pwa-assets`。
- **離線行為**：`/api/*` 設為 NetworkOnly（`frontend/vite.config.ts`），私人資料不會留在快取。離線時只開得出外殼，看不到資料，這是刻意的設計。

已知缺口：

- 不同網址是不同來源，`http://localhost:5000` 與 `https://….ts.net` 的登入狀態、主題設定不共用。
- Service Worker 安裝與推播已在本機 headless Chrome（`http://127.0.0.1`）實測；ts.net 網域與 iPhone、iPad 實機還沒有驗證。實際設定後請照第 5、6、8 節操作，確認可以安裝、登入、收到推播。

## 8. 推播通知（Web Push）

**伺服器**
1. 推播金鑰（VAPID）不用自己產生：OmniKeep 第一次啟動時會自動產生一組，私鑰用主金鑰加密後存在 App 設定裡。狀態在「設定 › 推播」。
   - `.env` 已經有 `VAPID_PUBLIC_KEY`、`VAPID_PRIVATE_KEY` 的話會照用，不會另外產生，既有裝置的訂閱不受影響。想讓 `.env` 不再放這兩行，到「設定 › 系統」按「從 .env 匯入」，再刪掉 `.env` 裡那兩行。
   - 主金鑰換過或遺失、推播私鑰解不開時，OmniKeep 不會自動換一組（原本的主金鑰檔放回去就會恢復）；確定找不回來，到「設定 › 推播」按「重新產生推播金鑰」，各裝置再重新開啟推播。
   - `scripts/generate_vapid_keys.py` 只有想把金鑰放在 `.env` 時才需要。
2. 選填「推播聯絡資訊」（`VAPID_SUBJECT`）：在「設定 › 推播」填，必須是 `mailto:` 或 `https://` 開頭；沒填就用專案網址。
3. 主機要能以 HTTPS 連到各家推播服務，例如 Chrome 的 `fcm.googleapis.com`、Apple 的 `*.push.apple.com`。

**每台裝置各自開啟**
- iPhone、iPad：需要 iOS／iPadOS 16.4 以上，而且**一定要先照第 6 節加到主畫面**，再從主畫面圖示開啟。Safari 分頁裡收不到推播。
- 開啟側欄底部的「通知」→「開啟這台裝置的推播」→ 允許通知，再按「傳送測試通知」確認。
- 筆電、桌機的 Chrome、Edge 也是同一個對話框。

**會推播什麼**
- 雷達戰報、雷達自動收藏（VIP），和 Telegram 同一組事件、同樣依雷達設定的通知模式；Telegram 照常發送。
- 新的待決提案：監看掃描發現風險檔、或雷達新情報與監看專案相關時，每產生一筆就推一則「📋 新的待決提案」，內容是提案標題與影響／信心／成本分數，不含檔名。點通知會打開監看中心的「提案」分頁。這是網頁推播獨有的；Telegram 不會主動通知提案，仍需 `/proposals` 查看。同一筆風險或同一則情報 30 天內只會提案一次，所以不會重複推播。
- 裝置解除安裝或撤銷權限後，推播服務回 404／410 時伺服器會自動刪掉那筆訂閱。

## 參考資料

- Tailscale Serve（身分標頭、Funnel 不帶身分標頭、代理到 `127.0.0.1`）：<https://tailscale.com/kb/1312/serve>
- `tailscale serve` 指令（`--bg`、`status`、`reset`、`off`、僅支援 `http://127.0.0.1`）：<https://tailscale.com/kb/1242/tailscale-serve>
- 啟用 HTTPS 憑證（MagicDNS、Let's Encrypt、Certificate Transparency 警告）：<https://tailscale.com/kb/1153/enabling-https>
- Windows unattended 模式：<https://tailscale.com/kb/1088/run-unattended>
- Tailscale serve 轉送時設定的標頭（`addProxyForwardedHeaders`、`addTailscaleIdentityHeaders`）：<https://github.com/tailscale/tailscale/blob/main/ipn/ipnlocal/serve.go>
- iPhone 加入主畫面：<https://support.apple.com/guide/iphone/bookmark-a-website-iph42ab2f3a7/ios>、<https://support.apple.com/guide/iphone/open-as-web-app-iphea86e5236/ios>
- Chrome 安裝 PWA：<https://support.google.com/chrome/answer/9658361>
- Service Worker 需要安全來源、`Service-Worker-Allowed`：<https://developer.mozilla.org/en-US/docs/Web/API/Service_Worker_API/Using_Service_Workers>
- Apple Web Push（iOS 16.4 主畫面 App、手勢授權、不可無聲推播、`*.push.apple.com`、JWT 規定、410 表示訂閱失效）：<https://developer.apple.com/documentation/usernotifications/sending-web-push-notifications-in-web-apps-and-browsers>
- WebKit：iOS／iPadOS 主畫面網頁 App 的 Web Push：<https://webkit.org/blog/13878/web-push-for-web-apps-on-ios-and-ipados/>
