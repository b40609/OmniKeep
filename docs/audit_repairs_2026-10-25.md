# OmniKeep 審查修復紀錄

日期：2026-10-25。範圍：依 `AUDIT_HANDOFF_GPT61.md` 與前次審查結果修復程式、補回歸測試、重新建置 PWA。

程式與測試已完成；正式服務尚未切換。本輪未讀取或修改 `.env`、未操作正式資料庫、未變更 Schema、未重啟服務、未提交 Git，也未刪除既有檔案。既有未追蹤的研究文件保留。

## 修復結果

| 順序 | 問題與修復後行為 | 主要檔案 |
|---|---|---|
| 1 | 測試先設定獨立資料庫，再匯入應用程式；每例各自建庫，拒絕連到隔離目錄外的 DB。清空供應商測試環境憑證並封鎖真實 socket 連線，避免正式佇列、Cookie 與外部服務受到測試影響。 | `tests/conftest.py`、`app/database.py` |
| 2 | 所有 `/api` 與遠端 `/mcp` 路徑共用標頭認證；LINE webhook 保留原本的簽章驗證。未提供認證回 401；未設定合格金鑰回 503。拒絕 URL query token，CORS 改為明列允許來源，私人回應標記 `no-store`。獨立 MCP SSE 啟動入口也經過相同 middleware。 | `app/security.py`、`app/main.py`、`app/mcp_server.py` |
| 3 | 前端移除內建金鑰，改用登入表單與記憶體中的 Bearer 認證；重新整理須再登入。登出後的遲到資料作廢，舊請求的 401 不會清除新登入；未登入時停用全域快捷鍵。 | `frontend/src/lib/api.ts`、`frontend/src/App.vue`、`frontend/src/composables/useKeyboard.ts` |
| 4 | 靜態路由僅供應目前建置的 JS 與必要資產，拒絕舊 UI、舊 JS 與其他靜態檔；保留磁碟上的舊檔。PWA API 改為僅走網路，載入新版時移除舊 API cache，HTML 與 SW 要求重新驗證。 | `app/static_assets.py`、`frontend/vite.config.ts`、`frontend/src/main.ts` |
| 5 | 網頁、RSS、YouTube、GitHub 與 Reel 的 HTTP 存取統一檢查 URL、每次重新導向與 DNS 結果。禁止內網、loopback、metadata IP、特殊協定、URL 帳密與非 80/443 port；解析後直接連線核可的數字 IP，保留原始 TLS server name，避免二次解析造成 DNS rebinding。 | `app/network.py`、`app/parsers/`、`app/radar/adapters/` |
| 6 | yt-dlp 僅允許原生 HTTP/HLS/DASH 下載器，使用同一公開網路傳輸層；單次回應上限 64 MiB。FFmpeg 輸入僅允許 `file,pipe`，防止本機播放清單另開網路。Playwright fallback 預設關閉；啟用時攔截請求並封鎖 service worker 與 WebSocket。 | `app/parsers/media_network.py`、`app/parsers/reel.py`、`app/parsers/web.py` |
| 7 | 監看資料依 summary/docs/deps/code/git 分別取得外送同意。summary 僅含結構統計；雷達關聯不再夾帶歷史指紋內容。輸入與儲存輸出均遮蔽，補大小寫、百分比編碼、JSON 跳脫、字串拼接、多行與巢狀 base64、完整 PEM 區塊。 | `app/watch/scanner.py`、`app/watch/relevance.py`、`app/watch/redact.py` |
| 8 | 動態 UPDATE 欄位採允許清單，值維持 SQL 參數化。30 天提案去重、24 小時 snooze 與行為統計改用 SQLite 時間運算，消除 ISO 字串與日期字串比較造成的延長。 | `app/database.py` |
| 9 | 提案去重、卡片與提案寫入共用 `BEGIN IMMEDIATE`；失敗一併回滾。風險提案改依穩定命中清單去重，雲端呼叫前先排除重複。新增寫入驗證參照，刪除操作會同步處理相關參照。 | `app/database.py`、`app/watch/scanner.py`、`app/watch/relevance.py` |
| 10 | REST 與 Telegram 共用原子滑卡操作；同卡重複決策不重複訓練，權重、事件與已讀／收藏一起提交。snooze 維持非訓練標籤。deck 共用排除與排序，權重讀取及後續調整套用 14 天衰減。 | `app/database.py`、`app/routers/behavior.py`、`app/bot/telegram_bot.py`、`app/radar/recommender.py` |
| 11 | 指紋納入程式碼、Git 訊號、權限，以及檔案大小與奈秒修改時間；同目標掃描與同情報關聯各自序列化，雲端回應後重查權限。略過 symlink/junction、正式 DB/WAL/SHM、備份與測試暫存，避免自身掃描回饋。 | `app/watch/scanner.py`、`app/watch/relevance.py`、`app/watch/locks.py` |
| 12 | 雷達關聯與實體展開改由有限佇列管理，預設 100 筆待處理、2 個消費者。停止時排空或取消並等待完成，避免無限 fire-and-forget。 | `app/background.py`、`app/radar/scheduler.py`、`app/pipeline.py` |
| 13 | worker 的 semaphore 僅由取得名額者釋放；cooldown、claim 失敗、取消均保持並行上限。單機跨程序鎖確保同 DB 只有一個 worker 執行 crash recovery，避免重置其他程序進行中的工作。 | `app/queue/worker.py`、`app/file_lock.py`、`app/database.py` |
| 14 | FastAPI 停止時依序停止 polling／備份與雷達，再排空 worker 與 follow-up，最後關閉 Telegram HTTP client。任一停止步驟失敗仍會執行後續清理；媒體與備份的原生執行緒完成後才清理資源。 | `app/main.py`、`app/bot/telegram_bot.py`、`app/parsers/reel.py`、`app/backup.py` |
| 15 | SQLite 備份採唯讀來源與 online backup API，獨立暫存目錄、唯一檔名、跨程序鎖。遠端成功後才輪替，本機失敗副本保留。修正每日備份的 UTC／本地日期與失敗重試；Git sink 僅加入並提交當次 ZIP。 | `app/backup.py`、`app/file_lock.py` |
| 16 | 補上程式直接使用的 MCP、httpcore、yt-dlp、feedparser、numpy 依賴宣告。 | `requirements.txt` |

## 實際驗證

- Python：`python -B -m pytest -q -p no:cacheprovider --tb=short`，**100 passed in 12.31s**。原有 51 例加上 49 例回歸案例，全部使用隔離 DB；沒有容許失敗項。
- 前端：`npm test`，**4 passed**，驗證標頭認證、未登入拒絕、跨登入的遲到 401、登出後遲到的 JSON。
- 建置：`npm run build`，**vue-tsc 與 Vite 成功**；PWA 產生 3 筆 precache。保留既有產物，未清空輸出目錄。
- 格式：`git -c core.safecrlf=false diff --check` 通過。
- 安全／一致性回歸包含：未認證與編碼路徑、CORS、舊靜態檔拒絕、私有 URL／混合 DNS／redirect、同步與非同步 HTTPS 的 IP 固定及 TLS hostname、媒體傳輸契約、遮蔽、同意範圍、時間邊界、同時提案、滑卡冪等、參照清理、重複 `init_db` 與 FTS 一致性。
- 生命週期／備份回歸包含：claim 失敗後並行上限、cooldown、worker 所有權、follow-up 上限與取消、啟動失敗清理、停止步驟失敗後續清理、WAL 快照解壓後 `quick_check`／FTS、備份互斥、失敗重試、遠端失敗保留歷史、Git 僅操作當次 ZIP、取消時等待原生執行緒。

以上是本機隔離驗證，不能當作新版已部署或真實外部平台已驗證。

## 正式切換仍需執行

1. 在本機私下輪換 API_KEY，使用密碼學安全亂數產生至少 32 字元；目前程式也要求至少 12 種不同字元。`.env` 仍由使用者管理，本輪未替換既有值。維持弱金鑰時，新版私人 API 會回 503。
2. 更新所有 REST／MCP 客戶端，使用 `Authorization: Bearer …` 或 `X-API-Key` 標頭。不同來源的前端需在 `CORS_ORIGINS` 明列來源；同來源部署預設空清單即可。不可把金鑰放入網址或重新編入前端。
3. 先完整停止舊服務及獨立 worker／Telegram polling，再啟動新版，避免新舊程序同時工作。舊程序不會因修改磁碟上的程式而自動取得新防護。確保部署環境安裝 `requirements.txt`。
4. 切換後驗證 `/health` 200、私人 API 未認證 401／有效認證 200、MCP 認證，以及實際 Tunnel 的路由與存取規則。手機端載入新版 SW，確認離線時不會從舊 API cache 顯示私人內容；既有裝置尚未載入新版前，不能宣稱舊快取已清除。

## 保留項與限制

- **正式資料尚未清理。** 前次唯讀審查曾發現 8 筆測試殘留、3 筆失去 item 的提案與 9 筆失去 target 的提案；這是審查當時的觀察，本輪未重新查詢或刪除。修復會約束後續操作，歷史資料另需備份、列出精確 ID 並經確認後清理。
- **未驗證外部實務整合。** 本輪未聯絡真實 LLM、Telegram、LINE、Cloudflare、公用媒體、rclone 或 Git remote，也未等待真實每日備份視窗。現有 Cookie、平台登入及公網暴露程度未做切換後驗證。
- **follow-up 仍是記憶體佇列。** 滿載會記錄警告並拒收，程序結束後不保存待處理工作，失敗也沒有自動重試。若需至少一次交付，應另設持久化工作佇列；新增 Schema 須另經確認。
- **遮蔽不是任意秘密偵測器。** 有界解碼與已知格式可攔截本次案例；自訂加密、任意混淆或未識別格式仍可能漏判。逐類外送同意與不讀高風險檔案仍是主要邊界。
- **網路與媒體相容性收緊。** 私有站台、特殊 port、外部下載器與需要 FFmpeg 直接連網的來源會被拒絕；瀏覽器 fallback 需明確啟用。超過 64 MiB 的單次媒體回應會失敗。
- **停止可能等待 I/O。** 等待原生執行緒可避免資源提早刪除，但實際停止時間可能超過 worker 的排空秒數，取決於媒體、SQLite 與遠端備份的完成／逾時。同步 DNS 仍受作業系統解析行為影響。
- **相依升級需保留契約測試。** 公開網路 transport 使用 httpcore backend 介面與 HTTPX pool 擴充點，媒體路徑擴充 yt-dlp。現有同步／非同步 TLS 與媒體傳輸契約已測；升級套件仍應重跑並做實際媒體抽測。目前靜態 JS 允許清單配合單一入口 bundle，未來若新增動態 chunks，需同步擴充。
- **秘密歷史仍需管理。** 舊 bundle 與 Git 歷史未刪改；新版靜態路由會拒絕舊 JS，但已下載的檔案無法收回，金鑰輪換是必要步驟。
