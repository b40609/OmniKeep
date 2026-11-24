# 全棧確定性護欄（Deterministic Harness）與 AI Coding 輔助工具鏈調研暨雙盲對照報告

日期：2026-11-24　狀態：OmniKeep 已落地（`d28c17e`）＋ OmniKit 已同步落地（`19a580f`、`ef31e7d`）

---

## 1. 背景與核心結論

在實戰開發 iPhone 行動端 App（PWA / Capacitor / Tauri Mobile）、桌面 WebApp 與 Python 全端系統時，「純裸 AI 寫程式（只靠 Prompt / Skill 叮嚀）」無法避免兩類系統性失誤：
1. **機率性遺忘**：模型為求快速完成功能，寫出桌面 Chrome 正常但 iOS Safari WebKit 捲動鎖死（`content-visibility: auto`、缺 `overscroll-behavior: contain`、非被動 `@touchstart`）或 CSS `@layer` 覆蓋導致 `< 16px` 自動放大的程式碼。
2. **缺乏確定性回饋（Sensors）與防繞過機制**：未裝靜態 Linter、型別閘門、Git Hooks 與真 WebKit 引擎巡檢時，錯誤 0 警告直接進 `main`；而只裝門禁不鎖 `PreToolUse` 時，AI 可能嘗試 `git commit --no-verify` 或偷關規則（Reward Hacking）。

依 Martin Fowler〈Harness Engineering〉框架，必須同時具備 **Guides（事前精簡引導）** 與 **Sensors（毫秒至秒級確定性門禁）**。本次透過 **四條飽和式調研子對話（總計掃描逾 400 個不重複項目、130+ 個 GitHub 專案經 `2026-11-24 gh api` 實測星數與授權）＋ Windows 11 本機實裝基準測試**，確立跨專案標準工具鏈。

---

## 2. 雙盲獨立調研交叉比對（`R1+R2+R3` 組 vs `stk824 Neon xhigh` 獨立盲測組）

為驗證調研完整性與模型視角差異，本次將 `R1`（Neon xhigh 前端）、`R2`（Claude Sonnet 5.5 Python 34 組）、`R3`（Claude Sonnet 5.5 Harness/資安 17 組）與完全隔離目錄、禁止互看的 **`stk824`（Gemini 4 Neon xhigh，三本獨立帳本全數達成 `--min-stars 1000` 連續 3 組無新名字飽和）** 進行交叉比對：

### 2.1 雙邊 100% 獨立收斂的鐵證共識
- **`DietrichGebert/ponytail`（★197,556，MIT）定性**：雙方皆獨立拆解 `hooks/claude-codex-hooks.json` 原碼，證實僅掛載 `SessionStart`、`SubagentStart`、`UserPromptSubmit` 注入 YAGNI 提示詞（外加 3 秒 Repo Map），**完全沒有 `PreToolUse` / `PostToolUse` / `Stop` 阻斷力**。只能當「減少廢碼」的 Guide 選配，不能取代 Linter 與測試門禁。
- **`microsoft/pyright`（★15,757）授權真相**：雙方皆獨立讀取 `LICENSE.txt` 原文，確認為 **100% 標準 MIT 授權**（因檔頭多兩行專案說明導致 GitHub API 誤判 `NOASSERTION`；真正閉源鎖非 VS Code 編輯器的是微軟 Pylance 擴充套件，Pyright CLI/LSP 完全開源自由使用）。
- **Python 核心門禁**：`astral-sh/ruff`（★51,399，v0.17.6；繁體中文必關 `RUF001–003` 或設 `allowed-confusables`、FastAPI 專案顯式加 `FAST`、必開 `F/B/ASYNC`）＋ `pyright` / `basedpyright`（`astral-sh/ty` v0.0.109 仍為 beta）＋ `deptry` ＋ `import-linter` / `tach` ＋ `Schemathesis`（FastAPI OpenAPI 自動模糊測試）。
- **前端死碼與瀏覽器 CLI 轉向**：雙方在互不看帳本下，同時挖出死碼雙雄 **`webpro-nl/knip`（★12,711）** 與 Rust 黑馬 **`fallow-rs/fallow`（★5,398）**，並同時確認 2026 年 Microsoft / Google / Vercel 全面轉向省 Token 的 **CLI + Skills**：Windows 本機唯一能跑 `--browser=webkit --device="iPhone 15"` 的是 **`microsoft/playwright-cli`（★15,410）**。

### 2.2 雙邊互補抓出的獨家盲點（雙線盲測價值）

| 領域 | `R1 / R2 / R3` 獨家抓到的關鍵細節 | `stk824`（Neon xhigh 盲測）獨家抓到的關鍵細節 | 主控 Windows 11 本機實裝仲裁結果 |
|---|---|---|---|
| **金鑰掃描（`gitleaks` vs `betterleaks`）** | 讀出 `gitleaks` README 官宣進入維護模式、轉開發 `betterleaks`；並補出 **Agent 讀檔層（擋 `.env` 進對話）＋ Git 提交層**雙層防線概念。 | 查出 `betterleaks` 改用 BPE 分詞降低中文／UUID 誤報，並挖出 Apache-2.0 替代品 `mongodb/kingfisher`（★1,318）。 | **關鍵實測翻盤**：本機實裝 `Betterleaks 1.10.1` 在 Windows 11 跑 `git --pre-commit --staged` 會因 `fatal: error reading /dev/null` 直接崩潰！實測 `Gitleaks 8.30.1` 僅 **227ms** 穩定通過 → **Windows 現階段必須以 `gitleaks` 為預設主力**，`betterleaks` 待上游修好 `/dev/null` 再切。 |
| **前端 Linter（Vue 3 + Tailwind v4）** | 查明 `oxlint` v1.95 尚無 Vue `<template>` 與 CSS、`biome` v2.6.8 的 `.vue` 尚無 GritQL/JS Plugin；挖出 **`@axe-core/playwright` 的 `target-size` 規則預設 `enabled: false`**（須顯式開 `wcag22aa`），以及渲染期幾何 UI Linter **`ngocanhnckh/renderlint`（★689）**。 | 直接讀 `biome` v2.6.8 Rust 原碼挖出已內建 55+ 條 Vue template 規則與 **`css/nursery/useLayeredStyles`**（專抓未包進 `@layer` 壓過 Tailwind v4 的 CSS！）；並抓出 **`chrome-devtools-mcp` 預設開啟 Google Telemetry 與 CrUX 網址外傳**（必加 `--no-usage-statistics --no-performance-crux`）！ | OmniKeep 已落地 **`oxlint`（117 檔 58ms）＋ `stylelint` v18（封殺 `content-visibility` / `100vh` / `background-attachment:fixed`）＋ `mobile-guardrails.test.mjs` ＋ Playwright WebKit 實跑巡檢**（首次跑即抓出 `@layer base` 被 `.text-sm` 蓋回 `14px` 的真 Bug！）。 |
| **Agent Hooks 跨三家引擎相容性** | R3 抓出 **AI Reward Hacking 三大偷吃步**：被門禁擋下後嘗試 `git commit --no-verify`、偷改 linter 設定關規則、偷讀 `.env`。 | 挖出原生支援 **Windows 11 + Claude Code + Codex + Antigravity CLI** 的語法解析級 `PreToolUse` 安全網 **`kenryu42/cc-safety-net`（★2,096，MIT）**，並核對本機 Antigravity `hooks.md` 抓出 **`PostToolUse` 在 Antigravity 僅吃空 `{}` 無法回傳錯誤文字，須改走 `PostInvocation` / `Stop`（含原生 `continuationActive` 防迴圈）**！另確認 `opengrep v2.0.0` 有簽章原生 Windows `.exe`（`semgrep` 無）。 | 已將此跨引擎差異與 `cc-safety-net` / `opengrep` 補充送入 `OmniKit` 升級對話一併落地。 |
| **Python 供應鏈與科學計算** | R2 續查補出 **`pypa/pip-audit`**（掃套件已知 CVE，補 Ruff `S` 盲區）與 **`patrick-kidger/jaxtyping`**（適合科學計算／數值矩陣維度檢查）。 | 查明 **`pyrefly v1.5.0` 已獲 Google 2026-10 正式採用並進駐微軟 Pylance TSP**，可列為高速雙軌候選。 | 本機已透過 `uv tool` 修復與裝妥 `ruff 0.17.6`（掃全 `app/` 僅 **342ms**）、`pyright 1.1.414`、`import-linter 2.17`、`pip-audit 2.10.1`、`prek 0.5.11`。 |

---

## 3. Windows 11 主力機已安裝生效的全域／專案工具清單（2026-11-24 實測）

| 類別 | 工具與實裝版本 | 安裝來源 | 本機實測表現 |
|---|---|---|---|
| Git Hook 執行器 | `prek 0.5.11` | `uv tool install prek` | 已掛載 `.git/hooks/pre-commit`，3 道門禁全跑完約 3 秒 |
| 金鑰防洩漏門禁 | `gitleaks 8.30.1` | `winget install Gitleaks.Gitleaks` | `git --pre-commit --staged` 實測 **227ms** 0 誤報通過 |
| Python 極速 Linter | `ruff 0.17.6` | `uv tool install ruff` | 全 `app/` 掃描實測 **342ms**，已配置 `ruff.toml` |
| Python 型別與架構 | `pyright 1.1.414`、`import-linter 2.17`、`pip-audit 2.10.1` | `uv tool install`（Python 3.14） | 已修復舊 Python 3.13 失效路徑 |
| 前端極速靜態門禁 | `oxlint 1.95.0`、`stylelint 18.1.0`、`postcss-html`、`knip 6.48.0` | `frontend` `npm install -D` | `oxlint` 掃 117 檔僅 **58ms**；`stylelint` 封殺 WebKit 地雷 |
| 真 Safari 核心巡檢 | Playwright `webkit`（v2370 / WebKit 27.2）＋ `@playwright/cli 0.1.25` | `playwright install webkit` ＋ `npm i -g @playwright/cli` | `python scripts/verify_mobile_webkit.py` 巡檢 7 大畫面 `ok: true, problems_count: 0` |

---

## 4. 新開任何 App / WebApp 專案的標準四層防線藍圖（已同步至 OmniKit）

1. **Layer 0（精簡引導 Guide）**：專案根目錄放 `AGENTS.md`（列明必跑指令與平台紅線），吸收 Karpathy 四原則與 `ponytail` 最小實作階梯，不塞冗長廢話。
2. **Layer 1（Agent 執行期 Hooks）**：
   - `PreToolUse`：擋破壞性指令、擋 `git commit --no-verify`、擋讀 `.env`/私鑰進對話、防偷改 linter 設定（可搭配 `cc-safety-net`）。
   - `PostToolUse` / `Stop`：單檔毫秒級跑 `ruff` / `oxlint` / `stylelint` 即時打回自修（Antigravity 走 `Stop` + `continuationActive` 防迴圈）。
3. **Layer 2（Git 本機鐵門 `prek` / `lefthook`）**：`pre-commit` 自動跑 `gitleaks` + `ruff` + `oxlint` + `stylelint` + 行動端契約測試。
4. **Layer 3（真引擎與契約驗收 + CI 重跑）**：前端必跑 **Playwright WebKit（iPhone 視窗：橫向溢位 = 0、捲動前進不鎖死、計算後 `fontSize >= 16px`、`@axe-core` 開 `wcag22aa`）**；FastAPI 後端跑 `pytest` + `Schemathesis`；CI 完整重跑防本機繞過。
