# OmniKeep — AI Coding Agent Engineering Guardrails

本文件為所有在本倉庫工作的 AI Coding Agent（Claude Code、Codex、Antigravity）必讀之確定性工程底線。視覺與排版細節另見 `DESIGN.md`。

## 1. 改完必跑的確定性驗證閘門（Sensors）

| 修改範圍 | 必跑指令 | 通過標準 |
|---|---|---|
| Python 後端（`app/`、`scripts/`、`tests/`） | `ruff check` ＋ `python scripts/pyright_baseline.py`（CI 僅擋新增）＋ 對應 `pytest` | `ruff check` 0 error、pyright 不得新增超出 `scripts/pyright_baseline.json` 的錯誤（新改檔案另跑 `ruff check --select F,E4,E7,E9,B,ASYNC,BLE,FAST <檔>` 與 `pyright <新檔>`） |
| 前端／行動端（`frontend/`、`static/`） | `cd frontend && npm run lint && npm test && npm run build` | `oxlint` + `stylelint` 0 error、全部單元與行動端契約測試全綠、建置 0 錯誤 |
| 涉及版面、捲動、彈窗、CSS 或路由 | 啟動服務後執行 `python scripts/verify_mobile_webkit.py` | 真實 Playwright **WebKit（Safari 核心）** 手機（iPhone）與桌面巡檢 `ok: true, problems_count: 0` |
| Commit 前門禁（已由 `prek` 自動掛載） | `prek run --all-files`（含 `gitleaks` 金鑰掃描） | 嚴禁使用 `git commit --no-verify` 繞過門禁；嚴禁為求通過而擅自刪除或放寬 lint 規則 |

## 2. iOS Safari / Mobile PWA / 桌面 WebApp 硬性防呆紅線

**嚴禁只看桌面 Chromium 正常就宣告完成。** 所有前端程式碼必須遵守以下機械規則（已由 `frontend/.stylelintrc.json`、`frontend/tests/mobile-guardrails.test.mjs` 與 `scripts/verify_mobile_webkit.py` 自動攔截）：

1. **禁止捲動鎖死與邊界傳遞（iOS 卡住需放手重滑的主因）**：
   - 登入後的全螢幕 App 外層殼固定使用 `fixed inset-0 overflow-hidden`（避免外層 `body` 搶走觸控手勢後卡死）。
   - 所有全頁或主面板垂直捲動容器（`overflow-y-auto`）**必須加上 `.mobile-scroll`**（內含 `-webkit-overflow-scrolling: touch; overscroll-behavior: contain; touch-action: pan-y;`）。
   - **嚴禁**在捲動清單／卡片上使用 `content-visibility: auto`（會導致 iOS WebKit 邊滑邊同步重算高度而斷幀卡死）。
   - **嚴禁**使用 `100vh`（改用 `100dvh` 或 `fixed inset-0`）與 `background-attachment: fixed`。
2. **觸控事件與動畫效能**：
   - 所有 `@touchstart` 監聽器**必須加 `.passive`**（`@touchstart.passive`），避免阻塞 iOS 合成執行緒。
   - 水平滑動手勢（如清單滑動封存）必須在 `|dx| >= 12px` 且 `|dx| > |dy| * 1.5` 時才鎖定攔截，並搭配 `touch-pan-y`，避免單手拇指微斜下滑被搶走捲動權。
   - 在觸控裝置（`@media (hover: none)`）避免對大量列表圖片掛載 CSS `filter: brightness(...)` 與 `:hover` 過渡動畫，改用純色半透明遮罩。
3. **防止 iOS 自動放大與靈動島／頂部系統模糊帶遮擋**：
   - 手機寬度（`max-width: 767px`）所有輸入框（`input`、`textarea`、`select`）必須在 **CSS `@layer` 之外** 強制 `font-size: max(16px, 1rem) !important`，防止被 `.text-sm` 等 utility 覆蓋而觸發 Safari 聚焦自動放大。
   - `frontend/index.html` 的 `apple-mobile-web-app-status-bar-style` 維持 `default`（禁用 `black-translucent`）。
   - 所有頂部導覽列、全螢幕面板與側邊抽屜統一使用 `.safe-top` 或 `var(--safe-top)`（禁止直接寫裸 `env(safe-area-inset-top)`），確保在 iOS 主畫面獨立模式自動加上頂部純色緩衝，避開 iOS 26/27 系統強制漸層模糊帶。

## 3. Python 後端與安全底線
- 非同步函式（`async def`）內禁止直接呼叫阻塞式檔案讀寫或同步網路請求（留意 Ruff `ASYNC` 規則）。
- 繁體中文專案已於 `ruff.toml` 關閉 `RUF001–RUF003`（全形標點誤報），切勿重新開啟。
- 嚴禁讀取、印出或寫死 `.env`、`*.secret.key`、`cookies*.txt` 與任何 API key / token。
