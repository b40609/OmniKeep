# App 內設定（取代手改 .env）提案

日期：2026-11-04　狀態：已決定採用方案 3，優先順序「App > .env > 預設」；第一、二階段已實作（見第 8 節）

## 1. 問題

目前所有 AI 服務商、金鑰、Bot、備份設定都只能寫在 `.env`，改完還要重啟服務。2026-11-04 的實例：`OPENAI_API_KEY` 在服務商端失效，從早上起每次 LLM 與 embeddings 呼叫都回 401，但只寫進 service log，介面上完全看不到；要修也只能開檔案改值再重啟。

目標：之後每個安裝 OmniKeep 的人，都能在 App 裡輸入、測試、更換這些設定，不必碰檔案。

「所有用戶」的解讀：OmniKeep 目前是單一擁有者（一把 `API_KEY` 登入，`app/security.py:11-24`），沒有帳號系統。所以這裡指「每個安裝的擁有者」，設定是整台實例共用。若要每個使用者各自帶金鑰（LibreChat 的 user_provided 模式），得先有帳號系統，不在本提案範圍。

## 2. 開源專案做法比較

資料於 2026-11-04 從官方文件與 GitHub 原始碼（釘在 commit）查證，完整來源見第 9 節。

| 專案 | 金鑰存放 | 靜態加密／主金鑰 | env 與 App 誰優先 | 會不會把金鑰回給瀏覽器 | 測試連線 | 生效 |
|---|---|---|---|---|---|---|
| Open WebUI | DB `config` 表，JSON [1] | 不加密 [1] | env 只在首次啟動種進 DB，之後 DB 優先 [2][3] | 會，admin 拿得到完整 key [4] | 有 [4] | 即時 [4] |
| LibreChat | MongoDB [7] | AES-256-CTR；`CREDS_KEY/IV` 由 env 提供 [8][9] | yaml/env 是底層，DB 覆寫疊上去 [10] | 不會，只回到期時間；改 URL 須重填 key [7][10] | 未查證 | 即時 [10] |
| AnythingLLM | 直接改寫 `.env` [12][13] | LLM key 明文 [16] | 只有 .env 一個來源 | 不會，只回 boolean，UI 顯示 `*` [14][15] | 只檢查前綴 [19] | 即時 [12] |
| Dify | DB `encrypted_config` [22] | 每 workspace 一組 RSA＋AES 混合加密 [21]；私鑰遺失只能清空重填 [23] | 以 App 為主 | 不會，遮罩顯示；送回哨兵值代表沿用 [20][22] | 存檔時強制驗證 [22] | 未查證 |
| LobeHub | DB，每位使用者一份 [28] | AES-GCM；`KEY_VAULTS_SECRET` 必須由 env 提供 [26] | env 是共用 key，使用者可另填 [29] | 會，解密後回給本人 [27] | 有 [27] | 即時 |
| n8n | DB credentials [31][32] | AES；主金鑰未設定時首次啟動自動產生，存 `~/.n8n/config`，env 與檔案不一致就拒絕啟動 [30] | 憑證只在 App | 不會，敏感欄位換成空白哨兵，存檔時還原 [32] | 有 [33] | 未查證 |
| Karakeep | 只有 env [34] | 不適用 | 只有 env | 不會 [35] | 無 | 要重啟 [35] |
| Linkwarden | 只有 env [36] | 不適用 | 只有 env | 不適用 | 無 | 未查證 |
| Khoj | DB，Django admin [38] | 明文 [38] | env 首次種進 DB，之後 admin 為主 [39] | 未查證 | 未查證 | 首次需重啟 [40] |
| Home Assistant | `.storage` JSON [41] | 不加密 [41] | 以 UI 為主 | 未查證 | 建立前先驗證 [42] | 免重啟、可單獨 reload [42] |

和 OmniKeep 同類的書籤／第二大腦專案（Karakeep、Linkwarden）都還停在只有 env；AI 平台類（n8n、Dify、LibreChat、Open WebUI）才做到 App 內設定。

### 值得照抄

- 兩層設定：host、port、DB 路徑、主金鑰這類「開 DB 前就要用」的留 env，其餘進 DB [10][30]。
- 主金鑰首次啟動自動產生、存在資料目錄、env 可覆寫，並存指紋偵測不一致 [30][9]。
- 金鑰只寫不讀：API 只回「已設定」與遮罩，用哨兵值代表「不變」，清除是另一個明確動作 [14][22][32][7]。
- 改了 base URL 就要求重填 key，避免舊 key 被送到新主機 [10]。
- 儲存前測試連線 [22][4][33][42]。
- 用有完整性驗證的加密（AEAD），並預留輪替 [26]。
- 寫入後清快取，立即生效 [4]。
- 設定變更寫稽核紀錄，不記值 [12][11]。

### 別人踩過的坑

- Open WebUI：首次啟動後再改 env 會被靜默忽略，官方另寫了排除疑難的文件；關掉持久化又變成 UI 的修改在重啟後消失 [3][2]。
- Open WebUI、Khoj 明文存放；LobeHub 加密了卻把明文回傳給瀏覽器 [1][4][38][27]。
- AnythingLLM 從 UI 整檔改寫 `.env`：得自己防換行與引號注入，原有註解會遺失 [13]。
- 主金鑰遺失：Dify 只能清空重填 [23]；LobeHub 解不開時靜默變成空值 [26]。
- 不帶完整性驗證的加密模式（AES-CBC、AES-CTR）[8][16]。

## 3. OmniKeep 現況盤點

- `settings` 是 import 時建立一次的全域物件（`app/config.py:147`）。多數程式在呼叫當下才讀 `settings.X`（例：`app/vector.py:157`、`app/radar/dreampass.py:133`、`app/bot/line_bot.py:30`），換值後下一次呼叫就會用新值。
- 不會自動跟著變、需要額外處理的三處：
  - LLM provider 單例快取（`app/providers/__init__.py:10-23`），建立後就不再讀設定。
  - Telegram bot 只在啟動時依 token 決定要不要開 polling（`app/main.py:76-78`）。
  - 備份迴圈只在啟動時 `BACKUP_SINK != "off"` 才建立（`app/main.py:74-75`）。
- 備份會把整個 `omnikeep.db` 打包，推到 rclone 雲端或 git repo（`app/backup.py:3-6`、`:39-58`）。金鑰若以明文存在 DB，就會跟著備份外流。所以金鑰一定要加密，而且解密用的主金鑰不能放在 DB 裡。
- 已經有「設定存 DB、介面編輯、立即生效」的先例：雷達設定（`radar_settings` 表、`app/routers/radar.py:187-191`、`RadarDialog.vue`）、Web Push 訂閱、Telegram 網頁配對。
- `cryptography` 已是 1.5.0 的依賴（`requirements.txt`），加密不需要新套件。

## 4. 設定分層

| 層級 | 設定 | 處理方式 |
|---|---|---|
| A. 啟動層 | `HOST`、`PORT`、`DATABASE_PATH`、`SNAPSHOT_DIR`、`BACKUP_DIR`、`CORS_ORIGINS`、`BACKGROUND_SERVICES_ENABLED`、`BROWSER_CDP_PORT`、`BROWSER_CDP_PROFILE_DIR` | 開 DB 之前就要用到，留在 `.env`；App 內唯讀顯示 |
| A'. 安全開關 | `API_KEY`、`LOCAL_AUTO_LOGIN` | 留在 `.env`。`API_KEY` 是登入本身（沒登入進不了設定頁）；`LOCAL_AUTO_LOGIN` 不該能從網頁遠端打開 |
| B. 金鑰 | `OPENAI_API_KEY`、`GEMINI_API_KEYS`、`TELEGRAM_BOT_TOKEN`、`LINE_CHANNEL_SECRET`、`LINE_CHANNEL_ACCESS_TOKEN`、`GITHUB_TOKEN` | App 內輸入，加密存 DB，只寫不讀 |
| C. 一般設定 | `PRIMARY_LLM_PROVIDER`、`OPENAI_BASE_URL`、`PRIMARY_MODEL`、`GEMINI_MODEL`、`EMBEDDING_MODEL`、`LLM_MIN_REQUEST_INTERVAL`、`LLM_MAX_CONCURRENCY`、`LINE_ALLOWED_USER_IDS`、`VAPID_SUBJECT`、`BACKUP_SINK`、`BACKUP_KEEP`、`BACKUP_HOUR`、`BACKUP_RCLONE_REMOTE`、`BACKUP_GIT_REPO_DIR`、`RADAR_MAX_ANALYZE_PER_CYCLE`、`RADAR_AUTOSTAR_ENABLED`、`RADAR_AUTOSTAR_THRESHOLD`、`ENABLE_BROWSER_FALLBACK`、`BROWSER_CDP_AUTOLAUNCH`、`BROWSER_CDP_HEADLESS` | App 內編輯，明文存 DB |
| D. 自動產生 | `VAPID_PUBLIC_KEY`、`VAPID_PRIVATE_KEY` | 首次啟動自動產生，私鑰加密存 DB；介面只顯示「已就緒」，不需要輸入 |

`TELEGRAM_ALLOWED_USER_IDS` 已被 1.5.0 的網頁一次性配對取代，介面不再提供手動輸入。

## 5. 三個方案

| | 方案 1：App 改寫 `.env` | 方案 2：DB 明文，env 首次種入 | 方案 3：DB 加密，兩層設定（建議） |
|---|---|---|---|
| 參考對象 | AnythingLLM | Open WebUI、Khoj | n8n、Dify、LibreChat 綜合 |
| 金鑰隨備份外流 | 不會（.env 不在備份） | **會**（DB 推到雲端／git） | 不會（加密，主金鑰不在 DB） |
| env 與 App 衝突 | 無（同一份檔） | **會**：改 env 被靜默忽略 | 明確規則＋介面標示來源 |
| 實作量 | 小 | 中 | 中偏大 |
| 主要風險 | 整檔重寫丟註解、注入、Windows 檔案鎖、Docker 唯讀掛載寫不進去 | 明文外流 | 主金鑰遺失要重填金鑰 |

## 6. 建議：方案 3 的具體設計

1. **儲存**：新表 `app_settings(key, value, is_secret, updated_at)`。金鑰用 `cryptography` 的 Fernet（AES-128-CBC＋HMAC-SHA256，有完整性驗證）加密，值加版本前綴，之後可用 `MultiFernet` 輪替。
2. **主金鑰**：第一次儲存金鑰時自動產生，存在資料庫旁的 `omnikeep.secret.key`（實作時由原訂的 `%LOCALAPPDATA%` 改過來，原因見第 8 節），檔案權限限本人；可用 env `OMNIKEEP_SECRET_KEY` 覆寫。DB 存主金鑰指紋：不一致時**不擋啟動、不靜默變空**，介面明確顯示「這幾個金鑰無法解密，請重新輸入」。
3. **優先順序**：App 內設定 > `.env` > 程式預設。每個欄位標示目前值的來源（App／.env／預設），可一鍵「改回使用 .env」。第一次開設定頁時，提供「把目前 .env 的值匯入 App」。
4. **只寫不讀**：API 只回 `configured`、末 4 碼與來源，永遠不回完整金鑰。欄位留空代表不變，清除是獨立按鈕。改了 `OPENAI_BASE_URL` 就要求重新輸入 key。
5. **測試連線**：儲存前可測：
   - LLM：`/models` 或最小 chat。
   - embeddings：打一次 `/embeddings`。
   - Gemini：列模型。
   - Telegram：`getMe`。
   - LINE：bot info。
   - GitHub：`/user`。
   錯誤原文（例如今天的 `This token status is unavailable`）直接顯示在欄位下方。
6. **立即生效**：存檔後更新執行中的設定、清 provider 單例，Telegram polling 與備份迴圈依新值啟停，不必重啟服務。
7. **AI 服務狀態提示**：記錄最近一次 LLM／embeddings 呼叫的失敗（401、429、連不上），在頂部顯示提示並連到設定頁。今天這種「金鑰失效一整天沒人知道」會直接被看到。
8. **權限**：只有已登入的擁有者能讀寫設定；`LOCAL_AUTO_LOGIN`、`API_KEY` 不開放網頁修改。設定變更寫稽核紀錄（時間、欄位名稱，不記值）。
9. **更換 embeddings 模型**：提示既有向量會失效，並提供「重建向量索引」按鈕（呼叫既有的 `app/reindex.py` 邏輯）。

### 分階段

- **第一階段**：
  - 後端：設定表、加密、主金鑰、優先順序、設定 API、測試連線、立即生效。
  - 前端：「設定」對話框，分「AI 服務商」「Telegram／LINE」「GitHub」「備份」四區；AI 服務錯誤提示；`.env` 匯入。
  - 測試：加密往返、遮罩、優先順序、主金鑰不一致、立即生效。
- **第二階段**：首次啟動精靈（沒有可用 LLM 時引導填寫）、VAPID 自動產生、稽核紀錄頁、主金鑰輪替指令、搬機時匯出主金鑰的說明。

### 開發方式

- 在獨立 worktree 從 `main`（1.5.0）開分支開發，不動伺服器正在跑的工作目錄，不 push。
- 另一個 session 正在把 `local/pre-upgrade-20261104` 合併進 1.5.0，兩邊都會改 `app/config.py`、前端 `App.vue`、`api.ts`。後合併的那邊需要處理衝突。

## 7. 決定

1. 採用方案 3。（2026-11-04 決定）
2. 優先順序「App > .env > 預設」。（隨方案 3 一併採用；另一種是 .env 永遠優先、App 內唯讀，比較保守，但違背「不碰檔案」的目標。）
3. 第一階段做完先在伺服器部署，還是先推分支開 PR：待決定。

## 8. 第一階段實作紀錄

| 項目 | 位置 |
|---|---|
| 主金鑰與加密（Fernet） | `app/secret_box.py` |
| 設定清單、驗證、優先順序、儲存、匯入 | `app/app_settings.py`（`SPECS`） |
| 資料表 `app_settings`、`app_settings_audit` | `app/database.py` init_db 第 24、25 項 |
| 設定 API（讀、存、測試、匯入、狀態） | `app/routers/settings.py`、`app/connection_checks.py` |
| AI 服務最近一次成功或失敗 | `app/ai_status.py`；寫入點在 `providers/openai_compatible.py`、`providers/gemini.py`、`vector.py` |
| 立即生效 | provider 單例重建、`limiter.reconfigure()`、`app/services.py`（Telegram polling 重啟）、備份迴圈改為常駐並逐輪讀 `BACKUP_SINK` |
| Telegram 綁定改存資料庫 | `app/bot/telegram_pairing.py`（不再寫 `.env`） |
| 前端 | `SettingsDialog.vue`、`ServiceStatusBanner.vue`、側欄「設定」 |

和第 6 節不同的地方：

- **主金鑰位置**：改為資料庫旁的 `omnikeep.secret.key`，而不是 `%LOCALAPPDATA%`。原因是 Docker 版的資料庫在 `/data` volume，容器內沒有 `%LOCALAPPDATA%`，放在家目錄會在重建容器時遺失。備份壓縮檔只含 `omnikeep.db`、快照與 `backup.json`，所以金鑰檔仍不會進入備份；`.gitignore`、`.dockerignore` 已排除 `*.secret.key`。需要放別處時用 `OMNIKEEP_SECRET_KEY_FILE`。
- **稽核紀錄**：第一階段就寫入 `app_settings_audit`（欄位名稱、動作、時間，不含值），檢視頁面留到第二階段。

順手修正：`RadarScheduler` 的 `asyncio.Event` 原本在模組載入時建立，會綁定第一次等待它的 event loop。現在每次 `start()` 都重新建立，避免重啟排程器後在另一個 loop 出錯（測試中可重現）。

### 第二階段（2026-11-04）

| 項目 | 位置 |
|---|---|
| 首次啟動精靈 | 前端 `SetupWizard.vue`、預設清單與要存的值 `frontend/src/lib/setup.ts`；`ServiceStatusBanner.vue` 的「開始設定」改開精靈 |
| VAPID 自動產生 | `app/vapid.py`（`ensure`、`regenerate`、`status`）；啟動點在 `app/main.py` lifespan；`SPECS` 新增 `VAPID_PUBLIC_KEY`、`VAPID_PRIVATE_KEY`（`generated=True`） |
| 推播金鑰 API | `POST /api/settings/push/regenerate`；`GET /api/settings` 多一個 `push` 狀態區塊 |
| 稽核紀錄 | `app_settings.audit_log()`、`GET /api/settings/audit?limit=&before=`；「設定 › 系統」的「變更紀錄」 |
| 主金鑰輪替 | `app_settings.rotate_master_key()`、`scripts/rotate_secret_key.py`；`secret_box` 改成多把金鑰的 keyring（`MultiFernet`） |
| 搬機與還原說明 | `docs/backup_restore.md` 第 1 節「主金鑰」、第 3 節「換到新機器」；`docs/tailscale_pwa_deploy.md` 第 8 節 |
| 測試 | `tests/test_vapid_auto.py`、`tests/test_secret_rotation.py`、`tests/test_settings_audit.py`；前端 `tests/setup-wizard.test.mjs`、`tests/settings-api.test.mjs` |

設計決定：

- **精靈何時出現**：登入後 `/api/settings/status` 的 `needs_setup` 為真、而且沒有「無法解密」的金鑰時自動打開（無法解密是另一個問題，由橫幅處理）。「稍後再說」只在這個瀏覽器分頁的工作階段內有效，下次開啟還會再問；橫幅的「開始設定」隨時可以再開。
- **精靈的流程**：仿 AnythingLLM OnboardingFlow 的 LLMPreference 步驟，分「選服務商 → 連線與測試 → 完成」。預設有 OpenAI、本機 Ollama、Google Gemini、OpenRouter、DeepSeek、其他 OpenAI 相容服務。**測試成功、而且測試的值和要存的值完全相同**才能儲存；測試後再改任何欄位，就要重新測試。
- **本機伺服器不需要金鑰**：精靈選 OpenAI 相容服務時一定會送出 `OPENAI_API_KEY`（Ollama 送空字串）。空字串代表「這台不需要金鑰」，也讓伺服器知道舊金鑰不該跟著換到新位址。測試連線配合調整：位址不是 `api.openai.com` 而且沒有金鑰時，改用 provider 原本就在用的佔位值 `dummy-key`；只有「已經存了金鑰、而且這次沒有送 `OPENAI_API_KEY`」時，才擋下換位址的測試。
- **VAPID 什麼時候產生**：只在執行背景服務的主程序啟動時產生（`BACKGROUND_SERVICES_ENABLED`），另外跑的 Bot、MCP 程序只讀不產生，避免兩邊各產一組。
- **`.env` 優先沿用**：`.env` 有完整的一組就不產生，也不寫進資料庫；只有半組（只有公鑰或只有私鑰）時視同沒有，直接產生完整的一組。想讓 `.env` 不再放金鑰，用「從 .env 匯入」整組搬進 App，訂閱不受影響；只有半組時不匯入。
- **兩把推播金鑰只能一起生效**：任何一把解不開或缺一把，兩把都不套用，避免瀏覽器訂閱到伺服器無法簽章的公鑰。
- **解不開時不自動重產**：主金鑰換過時，推播私鑰解不開。OmniKeep 不會自動換一組，因為原本的主金鑰檔可能找得回來，一換就讓所有訂閱失效。介面上提供「重新產生推播金鑰」，同時刪掉綁在舊公鑰上的訂閱。設定頁的推播區在金鑰正常時不顯示這個按鈕，避免誤按。
- **推播金鑰不出現在表單**：`generated=True` 的欄位不出現在 `describe()` 的欄位清單，`PUT /api/settings` 設定或改回都會被拒絕；只有 `save(..., system=True)` 能寫入。
- **主金鑰輪替的順序**：(1) 舊金鑰檔另存 `.bak`；(2) 金鑰檔改成「新金鑰、舊金鑰」兩行，所有值都還讀得到，執行中的伺服器也開始用新金鑰加密；(3) 一個交易內（`BEGIN IMMEDIATE`）把所有加密欄位改用新金鑰重新加密，並更新指紋、寫稽核紀錄；(4) 金鑰檔只留新金鑰。任一步驟中斷都還讀得到所有值，再執行一次即可。
- **不重啟就換金鑰**：`secret_box` 的快取除了路徑，也比對金鑰檔的 inode、修改時間與大小，檔案一換就重新載入。
- **只輪替金鑰檔**：主金鑰來自 `OMNIKEEP_SECRET_KEY` 環境變數時，指令拒絕執行，因為它改不了環境變數。
- **稽核紀錄**：沿用第一階段的 `app_settings_audit`，動作有 `set`、`clear`、`reset`、`import`、`pair`（Telegram 配對）、`generate`、`regenerate`、`rotate`（欄位名稱記為 `_secret_key`，顯示為「主金鑰」）。API 只回欄位、群組、動作、時間，最新的在前，用 `before` 往前翻頁。

順手修正：

- **沒設 `VAPID_SUBJECT` 時每則推播都送不出去**：py-vapid 1.9.6 的 `sub` 檢查只接受不帶路徑的 `https://` 網址，預設值 `https://github.com/b40609/OmniKeep` 會被拒絕，簽章直接丟例外，推播計為失敗。RFC 8292 允許任何 https URI，設定頁也已經檢查只能填 `mailto:` 或 `https://`，所以簽章時關掉 py-vapid 自己的檢查（`app/push.py`）。之前的測試都有設 `VAPID_SUBJECT`，所以沒抓到。
- **「無法解密」的原因說錯**：重新輸入其中一把金鑰後，指紋會更新成目前的主金鑰，提示就變成「找不到主金鑰」，但金鑰檔其實在。改成依金鑰檔是否存在來判斷。
- `.gitignore`、`.dockerignore` 加上 `*.secret.key.*`，輪替留下的 `.bak` 也不會被 commit 或打包進映像。

沒有做的：

- 主金鑰來自 `OMNIKEEP_SECRET_KEY` 環境變數時的輪替。
- 從網頁觸發輪替。輪替會在伺服器上留下舊金鑰備份檔，放在指令裡比較清楚；網頁只有說明。
- `scripts/generate_vapid_keys.py` 沒有刪除，改成「選用」：想把推播金鑰放在 `.env` 的人仍然可以用。

## 9. 來源

1. https://github.com/open-webui/open-webui/blob/c38885a/backend/open_webui/models/config.py#L107-L110
2. https://github.com/open-webui/open-webui/blob/c38885a/backend/open_webui/models/config.py#L201-L253
3. https://docs.openwebui.com/reference/env-configuration#enable_persistent_config
4. https://github.com/open-webui/open-webui/blob/c38885a/backend/open_webui/routers/openai.py#L455-L488
5. https://github.com/open-webui/open-webui/blob/c38885a/backend/start.sh#L29-L47
6. https://docs.openwebui.com/features/chat-conversations/direct-connections
7. https://github.com/danny-avila/LibreChat/blob/f4154b6/api/server/routes/keys.js#L7-L45
8. https://github.com/danny-avila/LibreChat/blob/f4154b6/packages/data-schemas/src/crypto/index.ts#L9-L147
9. https://www.librechat.ai/docs/configuration/dotenv#credentials-configuration
10. https://www.librechat.ai/docs/features/admin_panel
11. https://github.com/danny-avila/LibreChat/blob/f4154b6/api/server/routes/admin/config.js#L37-L108
12. https://github.com/Mintplex-Labs/anything-llm/blob/eda0eb5/server/utils/helpers/updateENV.js#L1519-L1573
13. https://github.com/Mintplex-Labs/anything-llm/blob/eda0eb5/server/utils/helpers/updateENV.js#L1711-L1732
14. https://github.com/Mintplex-Labs/anything-llm/blob/eda0eb5/server/models/systemSettings.js#L898
15. https://github.com/Mintplex-Labs/anything-llm/blob/eda0eb5/frontend/src/components/LLMSelection/OpenAiOptions/index.jsx#L19-L43
16. https://github.com/Mintplex-Labs/anything-llm/blob/eda0eb5/server/utils/EncryptionManager/index.js#L1-L40
17. https://github.com/Mintplex-Labs/anything-llm/blob/eda0eb5/server/endpoints/system.js#L600-L601
18. https://github.com/Mintplex-Labs/anything-llm/tree/eda0eb5/frontend/src/pages/OnboardingFlow/Steps
19. https://github.com/Mintplex-Labs/anything-llm/blob/eda0eb5/server/utils/helpers/updateENV.js#L1169-L1171
20. https://github.com/langgenius/dify/blob/7de3c29/api/core/helper/encrypter.py#L4-L10
21. https://github.com/langgenius/dify/blob/7de3c29/api/libs/rsa.py#L29-L60
22. https://github.com/langgenius/dify/blob/7de3c29/api/core/entities/provider_configuration.py#L388-L434
23. https://github.com/langgenius/dify/blob/7de3c29/api/commands/system.py#L25-L40
24. https://github.com/langgenius/dify/blob/7de3c29/api/controllers/console/workspace/model_providers.py#L213
25. https://github.com/langgenius/dify/blob/7de3c29/api/libs/key_providers/key_provider_type.py
26. https://github.com/lobehub/lobehub/blob/192766c/apps/server/src/modules/KeyVaultsEncrypt/index.ts#L9-L147
27. https://github.com/lobehub/lobehub/blob/192766c/apps/server/src/routers/lambda/aiProvider.ts#L76-L178
28. https://github.com/lobehub/lobehub/blob/192766c/packages/database/src/schemas/aiInfra.ts#L34-L46
29. https://github.com/lobehub/lobehub/blob/192766c/docs/self-hosting/environment-variables/model-provider.mdx#L75
30. https://github.com/n8n-io/n8n/blob/d5e7db2/packages/core/src/instance-settings/instance-settings.ts#L319-L358
31. https://github.com/n8n-io/n8n/blob/d5e7db2/packages/core/src/encryption/cipher.ts#L173-L192
32. https://github.com/n8n-io/n8n/blob/d5e7db2/packages/cli/src/credentials/credentials.service.ts#L1740-L1776
33. https://github.com/n8n-io/n8n/blob/d5e7db2/packages/cli/src/credentials/credentials.controller.ts#L141-L187
34. https://docs.karakeep.com/configuration/environment-variables
35. https://github.com/karakeep-app/karakeep/blob/6a1e71d/packages/shared/config.ts#L661-L670
36. https://docs.linkwarden.app/self-hosting/ai-worker
37. https://github.com/linkwarden/linkwarden/blob/eff7c6b/packages/prisma/schema.prisma#L53-L55
38. https://github.com/khoj-ai/khoj/blob/ae229ca/src/khoj/database/models/__init__.py#L206-L209
39. https://github.com/khoj-ai/khoj/blob/ae229ca/src/khoj/utils/initialization.py#L174-L292
40. https://docs.khoj.dev/get-started/setup
41. https://github.com/home-assistant/core/blob/d210604/homeassistant/helpers/storage.py#L41
42. https://contributors.home-assistant.io/core/integrations/config-flow/
