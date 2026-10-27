# P0：全域認證與本機服務切換

使用者裁決順序：P0 安全 → A 最小版 → C（B-lite 內嵌）→ B-full。
本文件只記錄 P0；commit 訊息仍須先由使用者審核。

## 問題與修補

- 切換前，本機正式服務的 `GET /api/watch/targets` 未帶 key 回 200。磁碟上先前已有稽核修補，但舊程序沒有載入。
- `app/security.py:verify_api_key` 掛為 FastAPI 全域 HTTP middleware，預設保護所有路由、未來路由與掛載應用，涵蓋 REST、MCP、文件與 OpenAPI。
- 公開例外限 GET/HEAD 的 `/`、`/health`、`/static/`，以及 POST `/api/line/webhook`。LINE 仍由其 handler 驗證 HMAC 簽章；例外不延伸至其他方法或子路徑。CORS preflight 交由內層 CORS middleware 處理。
- 認證只接受 Bearer 或 X-API-Key；缺少／錯誤憑證回 401，空白或不合格設定回 503，私人回應帶 `Cache-Control: no-store`。
- 新增 `scripts/rotate_api_key.py`，產生 48 bytes 密碼學亂數，轉成 64 字元 URL-safe key，原子更新 `.env` 的 API_KEY。使用 dotenv parser 保留其他設定，處理重複宣告；不匯入應用程式、不印出憑證。偵測到 API_KEY 環境覆寫時拒絕操作。
- `.env.example`、README、MCP 與 iOS 捷徑教學移除舊公開預設 key 與 URL token 認證範例。既有前端登入／Header 認證與靜態檔防護沿用先前稽核修補。

## 已執行的正式切換

- 2026-10-26，私下輪換本機 `.env` 的 API_KEY；憑證未輸出到對話或命令日誌，`.env` 已確認為 ignored 且未追蹤。
- 停止前核對 console 僅含舊服務與其 launcher，送正常 console interrupt；Ctrl+C 未停止程序，後續 Ctrl+Break 正常關閉，沒有強制終止。
- 舊程序 40760 與 launcher 26828 均退出，確認 port 5000 釋放後才啟動替代服務。新版以隱藏視窗執行，PID 47984，監聽 `0.0.0.0:5000`。
- 啟動前以唯讀連線取得正式 DB 的記憶體快照，在快照執行同一 `init_db`，前後 schema 完全相同。未改資料庫 Schema、未清除歷史資料。
- 啟動／錯誤日誌保留於 ignored 的 `scratch/p0-service-20261026-000405-62fbfe.*.log`，沒有將原始服務日誌回傳對話。

## 驗證

Python 基準實際為 **100 passed**（原始 51 例加先前稽核 49 例）。本次新增 5 例，全套 **105 passed in 15.53s**：

```powershell
python -B -m pytest -q -p no:cacheprovider --tb=short
```

新增驗證涵蓋：未來路由與 mount 預設保護、真正 CORS preflight 不執行私人 handler、無 key 時仍可開登入頁、LINE 精確例外與簽章、輪換後舊 key 拒絕／新 key 接受、其他 dotenv 設定保留，以及環境覆寫拒絕。最初兩例使用系統 tmp_path 時遇到 Windows Temp 權限錯誤，改用專案既有隔離 fixture 後全數通過。

本機正式服務 HTTP 探測只記錄狀態，不輸出資料內容或認證標頭：

| 請求 | 結果 |
|---|---|
| 無認證 `/health`、`/` | 200 |
| 無認證 `/api/watch/targets`、`/mcp/auth-probe-not-found`、`/docs` | 401 |
| 錯誤測試 key／舊公開預設 key 存取 REST | 401 |
| 新 key，以 Bearer 或 X-API-Key 存取 REST | 200 |
| 新 key 存取 `/mcp/auth-probe-not-found` | 404，已通過外層認證並進入 mount |
| 新 key 存取 `/docs` | 200 |

MCP 使用不存在的有限端點驗證閘門，未宣稱完成 SSE 工具握手。

## 待審提交

建議訊息：`fix(security): 全域保護 REST 與 MCP，補上私密換 key 流程`

P0 補丁另存於研究者本機的 `p0-security-review-20261026.patch`（未隨本倉庫發布），以當時 HEAD 為基底，納入本次修補及必要的既有認證、登入、測試隔離底座；不含其餘 SSRF、DAO、提案、雷達與備份重構。當時尚未 stage 或 commit。

已在獨立目錄以 HEAD 加上 P0 補丁執行測試，**56 passed in 12.99s**（原始 51 例加本次 5 例），證明不依賴其餘未提交稽核修改。原工作目錄仍為 **105 passed**；前端認證測試 `npm test` 亦為 **4 passed**。補丁已確認可套用目前 index，`git diff --check` 通過。

## 後續與邊界

- REST／MCP 客戶端與手機捷徑需私下更新新 key；新版看板也須重新登入。本次未改其他應用程式內儲存的憑證。
- 尚未由公網 Cloudflare Tunnel 或手機測試，也未驗證真實 LLM、Telegram、LINE 與每日備份的端到端結果。
- 舊裝置的離線快取未逐一驗證；歷史 bundle 與 Git 歷史保留，當前靜態路由拒絕舊 JS。
- 工作目錄原有多項未提交稽核修改；P0 提交須分離認證／登入／測試隔離所需底座，避免混入 SSRF、提案、雷達排序與備份重構。
- P0 訊息審核並提交後，依裁決開始 A 四件事；C 與 B-full 尚未實作。
