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
| `LOCAL_AUTO_LOGIN` | `false` | 開啟時，同機瀏覽器可免輸入金鑰。經 Tailscale serve 進來的請求帶有 `X-Forwarded-For`、`Tailscale-*` 等標頭，一律不會自動登入（`app/routers/session.py`）；啟動時也會在 log 留一則警告。 |
| `CORS_ORIGINS` | 不用設 | PWA 與 API 同源。 |

手機第一次開啟時，輸入 `API_KEY` 並勾選「記住金鑰」即可。

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

接著用瀏覽器開網址，輸入 `API_KEY` 登入。

## 6. 把 PWA 加到主畫面

**iPhone、iPad（Safari）**
1. 用 Safari 開 `https://<主機名>.<tailnet 名>.ts.net/` 並登入。
2. 點分享按鈕（依分頁列配置，可能在頁面選單裡），選「加入主畫面」。
3. 新版 iOS 會出現以網頁 App 開啟的開關（英文介面是 Open as Web App），保持開啟，再點「加入」。
4. 從主畫面圖示開啟時會是獨立視窗。第一次開啟可能需要再輸入一次金鑰。

圖示只會出現在操作的那台裝置；iPad 要另外加一次。

**筆電、桌機（Chrome、Edge）**
- 網址列右側的「安裝」圖示，或選單 ⋮ →「投放、儲存及分享」→「將網頁安裝為應用程式」。
- 瀏覽器提供安裝提示時，OmniKeep 頂部列也會出現安裝按鈕（`frontend/src/components/layout/AppHeader.vue:288-289`）。

## 7. Service Worker 與 manifest 在 ts.net 下能不能運作

可以，條件都符合：

- **安全來源**：Service Worker 只在 HTTPS（或 localhost）運作。`*.ts.net` 用的是 Let's Encrypt 簽發的公開信任憑證，所以是安全來源。
- **scope**：Service Worker 檔案在 `/static/dist/sw.js`，以 scope `/` 註冊（`frontend/src/main.ts`）。伺服器回應帶 `Service-Worker-Allowed: /`（`app/main.py:136-146`），跟網域名稱無關。
- **manifest**：`static/manifest.json` 的 `start_url`、`scope` 都是 `/`，`display` 是 `standalone`，都是相對於來源的路徑，換成 ts.net 網域不需要修改。
- **離線行為**：`/api/*` 設為 NetworkOnly（`frontend/vite.config.ts`），私人資料不會留在快取。離線時只開得出外殼，看不到資料，這是刻意的設計。

已知缺口：

- `static/manifest.json` 的圖示指向外部 icons8 網址，也還沒有 `apple-touch-icon`，主畫面圖示可能缺失或依賴外部網路。這會在 PWA 打底的第 4 項修正。
- 不同網址是不同來源，`http://localhost:5000` 與 `https://….ts.net` 的登入狀態、主題設定不共用。
- 以上是依規格與程式設定推得的結論，還沒有在實機上驗證過。實際設定後請照第 5、6 節操作，確認可以安裝、可以登入。

## 參考資料

- Tailscale Serve（身分標頭、Funnel 不帶身分標頭、代理到 `127.0.0.1`）：<https://tailscale.com/kb/1312/serve>
- `tailscale serve` 指令（`--bg`、`status`、`reset`、`off`、僅支援 `http://127.0.0.1`）：<https://tailscale.com/kb/1242/tailscale-serve>
- 啟用 HTTPS 憑證（MagicDNS、Let's Encrypt、Certificate Transparency 警告）：<https://tailscale.com/kb/1153/enabling-https>
- Windows unattended 模式：<https://tailscale.com/kb/1088/run-unattended>
- Tailscale serve 轉送時設定的標頭（`addProxyForwardedHeaders`、`addTailscaleIdentityHeaders`）：<https://github.com/tailscale/tailscale/blob/main/ipn/ipnlocal/serve.go>
- iPhone 加入主畫面：<https://support.apple.com/guide/iphone/bookmark-a-website-iph42ab2f3a7/ios>、<https://support.apple.com/guide/iphone/open-as-web-app-iphea86e5236/ios>
- Chrome 安裝 PWA：<https://support.google.com/chrome/answer/9658361>
- Service Worker 需要安全來源、`Service-Worker-Allowed`：<https://developer.mozilla.org/en-US/docs/Web/API/Service_Worker_API/Using_Service_Workers>
