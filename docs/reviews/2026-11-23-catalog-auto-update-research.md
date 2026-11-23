# AI 服務商與模型目錄自動更新、安全防護與 404 自癒業界調研報告

- 調研日期：2026-11-23
- 適用專案：`OmniKeep`（對照檔案：[app/provider_catalog.py](file:///C:/Users/user/Desktop/OmniKeep/app/provider_catalog.py)、[app/providers/chain.py](file:///C:/Users/user/Desktop/OmniKeep/app/providers/chain.py)、[app/connection_checks.py](file:///C:/Users/user/Desktop/OmniKeep/app/connection_checks.py)、[scripts/free_channel_watch.py](file:///C:/Users/user/Desktop/OmniKeep/scripts/free_channel_watch.py)）
- 調研方法：依據 `omnikit-research` 飽和式調研規範，結合 GitHub API（`2026-11-23` 實測星數、授權與最近更新日）、一手指針原始碼與官方 README 查證。未取得一手原始碼／官方文件原文佐證之行為均標註「待驗證」。

---

## 目錄

1. [OmniKeep 現況痛點摘要](#1-omnikeep-現況痛點摘要)
2. [業界與開源專案總覽比較表](#2-業界與開源專案總覽比較表)
3. [問題一：不用升級程式就保持目錄最新的 4 種主流模式](#3-問題一不用升級程式就保持目錄最新的-4-種主流模式)
4. [問題二：遠端更新清單的安全風險與 7 層實戰防護](#4-問題二遠端更新清單的安全風險與-7-層實戰防護)
5. [問題三：執行期 404 / model_not_found 自我修復做法](#5-問題三執行期-404--model_not_found-自我修復做法)
6. [問題四：誰去發現變動（排程、探測與自動 PR / 下架）](#6-問題四誰去發現變動排程探測與自動-pr--下架)
7. [給 OmniKeep 的 3 個架構方案組合與取捨](#7-給-omnikeep-的-3-個架構方案組合與取捨)
8. [飽和式調研過程與管道紀錄](#8-飽和式調研過程與管道紀錄)

---

## 1. OmniKeep 現況痛點摘要

目前 OmniKeep 將免費／公開 AI 服務卡片寫死在 [app/provider_catalog.py](file:///C:/Users/user/Desktop/OmniKeep/app/provider_catalog.py#L27-L402) 的 `CARDS` 清單與 `VERIFIED = "2026-11-05"`：
- 每張卡片同時混合了**路由與憑證邊界欄位**（`id`、`kind`、`base_url`、`key_mode`、`key_url`、`editable_url`、`caps` 含 `extra_body`）與**高變動資料欄位**（`model`、`models`、`limits`、`quota`、`ends`、`verified`、`notes`）。
- 雖然 [app/provider_catalog.py](file:///C:/Users/user/Desktop/OmniKeep/app/provider_catalog.py#L385-L388) 的 `ended()` 能依 `ends` 字串比較自動判斷是否過期，但免費模型改名、下架、額度調整無法在不發版的情況下同步到使用者本機。
- 在執行期容錯方面，[app/providers/chain.py](file:///C:/Users/user/Desktop/OmniKeep/app/providers/chain.py#L43-L47) 的 `COOLDOWNS` 針對 `not_found` 僅會把單一節點冷卻 6 小時（`6 * 3600.0` 秒）並切換至備援鏈下一張卡，不會更新失效模型或重新探測可用替代模型。
- 維護側雖已有 [scripts/free_channel_watch.py](file:///C:/Users/user/Desktop/OmniKeep/scripts/free_channel_watch.py#L1-L169) 協助比對 `freellmapi` 與 `mvalentsev/awesome-free-ai-coding` 快照差異，但仍需維護者手動更新 `CARDS` 並發版（參考 [docs/reviews/2026-11-22-free-channels-refresh.md](file:///C:/Users/user/Desktop/OmniKeep/docs/reviews/2026-11-22-free-channels-refresh.md)）。

---

## 2. 業界與開源專案總覽比較表

> 註：下表所有 GitHub ★ 數與授權皆於 `2026-11-23` 透過 `gh api` 實測取得；標記「（已封存）」表示官方 repo 已 `archived: true`。

| 專案 | ★數（2026-11-23 實測） | 清單／資料從哪來 | 多久更新與同步方式 | 有沒有本地退路與關閉方式 | 安全防護 | 一手證據連結 |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **BerriAI/litellm** | ★63,732（NOASSERTION） | `raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json`（可透過 `LITELLM_MODEL_COST_MAP_URL` 覆寫 `http`/`https`/`s3`/`gs`） | 模組載入／啟動時抓取；CI 檢查同步並由 bot/PR 更新價格表 | 有：`model_prices_and_context_window_backup.json` 與 Rust `include_bytes!`；設 `LITELLM_LOCAL_MODEL_COST_MAP=True` 或離線模式可關閉遠端抓取 | 檢查遠端模型筆數不可 `< 50` 且不可低於內建數量 `0.5` 倍（防縮水）；JSON 本身無簽章 | [policy.rs](https://github.com/BerriAI/litellm/blob/main/litellm/rust/crates/model-catalog-refresh/src/policy.rs#L16-L17) / [get_model_cost_map.py](https://github.com/BerriAI/litellm/blob/main/litellm/litellm_core_utils/get_model_cost_map.py#L4-L99) / [constants.py](https://github.com/BerriAI/litellm/blob/main/litellm/constants.py#L202-L206) |
| **pydantic/genai-prices** | ★419（MIT） | `raw.githubusercontent.com/pydantic/genai-prices/refs/heads/main/prices/new_data/v2/data.json` | 伺服器／SDK 背景執行緒預設每 3600 秒（1 小時）更新；上游 GitHub Actions 每小時／每週開 PR | 有：內建 `data.py` 快照退路；可自訂或停用 `UpdatePrices` 背景更新 | Schema 陣列結構檢查（確認包含 provider 陣列）、10 秒請求逾時與 5 秒連線逾時 | [update_prices.py](https://github.com/pydantic/genai-prices/blob/main/packages/python/genai_prices/update_prices.py#L23-L141) / [update-prices.yml](https://github.com/pydantic/genai-prices/blob/main/.github/workflows/update-prices.yml#L3-L44) |
| **anomalyco/models.dev**（原 `sst/models.dev`） | ★7,727（MIT） | 各家 provider TOML 匯聚產出 `https://models.dev/api.json`（實測 6.91 MB、326 家供應商、含 ETag） | 上游 `sync-models.yml` 每 6 小時執行一次，依供應商拆 PR 並對安全項目自動 merge | 此專案本身是公開目錄伺服器；消費端需自備快取／快照 | CI 刻意切分無 PR 寫權限的 `sync` 與持有 App Token 的 `publish`，且限制僅能改 catalog TOML | [README.md](https://github.com/anomalyco/models.dev/blob/dev/README.md#L22-L70) / [sync-models.yml](https://github.com/anomalyco/models.dev/blob/dev/.github/workflows/sync-models.yml#L4-L11) |
| **anomalyco/opencode** | ★228,650（MIT） | 抓取 `https://models.opencode.ai/experimental/v2.0/api.json`（源於 `models.dev`） | 5 分鐘記憶體 TTL + `If-None-Match` ETag 條件請求（304） | 有：KV 快取 `models-dev:v3:catalog`＋隨程式碼編譯的 `snapshot.txt`；可透過 `Options` 覆寫 URL 或指定靜態檔 | 10 秒逾時 + 2 次暫時錯誤重試；個別無法解析的模型直接略過，避免整包壞掉 | [models-dev.ts](https://github.com/anomalyco/opencode/blob/dev/packages/core/src/models-dev.ts#L564-L740) |
| **openclaw/catalog** | ★14（MIT） | `https://catalog.openclaw.ai/models/{v1,v2,v3}/catalog.json`（CF Workers Static Assets） | 上游每 4 小時產出發布；OpenClaw 用戶端每 6 小時拉取一次 | 有：用戶端退回隨版包裝預設；設 `models.catalogRefresh.enabled: false` 可關閉 | 客戶端強制禁止遠端修改 endpoint、`headers` 或新增未知 provider；發布前檢查縮水 `> 5%` 或整家消失並跑舊版相容測試 | [README.md](https://github.com/openclaw/catalog/blob/main/README.md#L3-L94) |
| **CherryHQ/cherry-studio** | ★53,762（AGPL-3.0） | 鎖定分支 `x-files/provider-registry/v{N}` 的 `manifest.json`、`models.json`、`provider-models.json`（GitHub / CN 切 GitCode 鏡像） | 啟動 30 秒後首次抓取、之後每 6 小時一次；上游每日 `00:00 UTC` 自動產 PR | 有：內建套件 `@cherrystudio/provider-registry/data`；僅在非打包環境 `!app.isPackaged` 跳過（UI 是否有開關：待驗證） | **路由與模型分離**（端點寫死隨版走，註解明確寫明防未簽章資料導向憑證去處）；單調遞增 `revision` 防回滾；`minAppVersion` 相容檢查；`manifest.files` 雜湊防跨 commit 混合＋Zod 驗證 | [ProviderRegistryUpdaterService.ts](https://github.com/CherryHQ/cherry-studio/blob/main/src/main/services/ProviderRegistryUpdaterService.ts#L25-L200) / [auto-update-catalog.yml](https://github.com/CherryHQ/cherry-studio/blob/main/.github/workflows/auto-update-catalog.yml#L4-L80) |
| **tashfeenahmed/freellmapi** | ★56,791（MIT） | `https://api.freellmapi.co/v1/latest?since=<ver>`（付費 Key 每 2–3 天 Live 版；免費約 30 天快照），另對允許名單端點支援 `/v1/models` 發現 | 每 12 小時 + 啟動 10 秒同步一次；自訂端點每 24 小時只增不刪掃 `/v1/models` | 有：隨版 SQLite 種子＋快取；可設定 `CATALOG_BASE_URL`／`CATALOG_PUBKEY` 指向自架，或 `BUILTIN_MODEL_DISCOVERY=off`、`CUSTOM_MODEL_SYNC_INTERVAL_MS=0` 關閉發現 | **Ed25519 公鑰釘選驗證** `x-catalog-signature`；最低版本門檻 `MIN_CATALOG_VERSION` 防降級；保護 `source='user'` 與刪除墓碑；`model-discovery.ts` 限制回傳 `<= 10 MB` 與 `<= 500` 模型 | [05-catalog-sync.md](https://github.com/tashfeenahmed/freellmapi/blob/main/docs/en/architecture/05-catalog-sync.md) / [catalog-sync.ts](https://github.com/tashfeenahmed/freellmapi/blob/main/server/src/services/catalog-sync.ts#L30-L443) / [builtin-model-discovery.ts](https://github.com/tashfeenahmed/freellmapi/blob/main/server/src/services/builtin-model-discovery.ts#L50-L66) |
| **cline/cline** | ★71,832（Apache-2.0） | 主目錄抓 `https://models.dev/api.json` + 部分供應商即時打 `/v1/models` 或 `/v1/model/info` | 記憶體快取 10 分鐘（`models.dev`）／5 分鐘（供應商端點）+ 手動重新整理按鈕 | 有：內建 `MODEL_COLLECTIONS_BY_PROVIDER_ID` 編譯預設（僅 Ollama/LM Studio 跳過）；SDK 選項可控 `failOnError`（IDE UI 獨立關閉遠端選項：待驗證） | 5 秒逾時保護與同時間 in-flight 請求去重；內建服務商路由寫死於各 handler 與設定 | [provider-defaults.ts](https://github.com/cline/cline/blob/main/sdk/packages/core/src/services/llms/provider-defaults.ts#L116-L1015) / [refreshOpenRouterModels.ts](https://github.com/cline/cline/blob/main/apps/vscode/src/core/controller/models/refreshOpenRouterModels.ts#L4-L16) |
| **RooCodeInc/Roo-Code**（已封存） | ★24,239（Apache-2.0） | 直接打各家供應商／路由器 API（例如 OpenRouter `/api/v1/models`、Requesty、LiteLLM、Ollama） | 啟動背景刷新常用路由器 + 5 分鐘 `NodeCache` | 有：本地 `globalStorageUri` 下 `${router}_models.json` 磁碟快取；失敗或空陣列時回退舊快取 | 僅向使用者已設定或內建已知端點拉取模型名稱，不接受跨供應商遠端變更路由 | [modelCache.ts](https://github.com/RooCodeInc/Roo-Code/blob/main/src/api/providers/fetchers/modelCache.ts#L28-L235) / [openrouter.ts](https://github.com/RooCodeInc/Roo-Code/blob/main/src/api/providers/fetchers/openrouter.ts#L97-L115) |
| **continuedev/continue** | ★36,540（Apache-2.0） | `packages/llm-info` 靜態元資料 ＋ 設定 `model: AUTODETECT` 時向供應商打 `listModels()` | 設定檔載入時觸發（或使用者手動重載設定），靜態 meta 隨發版更新 | 有：於 `config.yaml` 寫死明確模型名稱即可不跑 `AUTODETECT` | `AUTODETECT` 僅針對使用者自己設定的端點與本機環境掃描模型列表 | [models.ts](https://github.com/continuedev/continue/blob/main/core/config/yaml/models.ts#L10-L406) / [llm-info README](https://github.com/continuedev/continue/blob/main/packages/llm-info/README.md#L13-L32) |
| **open-webui/open-webui** | ★159,298（NOASSERTION） | 動態向已設定的 OpenAI 相容端點打 `{url}/models` | 請求時依使用者快取（`MODELS_CACHE_TTL`）或開啟 `ENABLE_BASE_MODELS_CACHE` | 無遠端公共免費目錄；可固定寫死模型 ID 或開啟持久化基礎模型快取 | 僅向管理員／使用者設定之端點取樣；無未簽章外部目錄自動改 `base_url` 機制 | [openai.py](https://github.com/open-webui/open-webui/blob/main/backend/open_webui/routers/openai.py#L119-L823) / [utils/models.py](https://github.com/open-webui/open-webui/blob/main/backend/open_webui/utils/models.py#L141-L161) |
| **LibreChat-AI/LibreChat** | ★47,427（MIT） | 設定 `librechat.yaml` 的 `models.fetch: true` 向端點拉取（搭配必備 `models.default`） | 請求快取於 `standardCache` 並做 in-flight 共用 | 有：`models.default` 為靜態退路；不設 `fetch: true` 即完全使用手動設定清單 | 對使用者填寫 `baseURL` 強制套用 `createSSRFSafeAgents` 與 `validateEndpointURL`，且鎖死 `maxRedirects = 0` 防 SSRF／憑證外洩 | [loadDefaultModels.js](https://github.com/LibreChat-AI/LibreChat/blob/main/api/server/services/Config/loadDefaultModels.js) / [endpoints/models.ts](https://github.com/LibreChat-AI/LibreChat/blob/main/packages/api/src/endpoints/models.ts) |
| **janhq/jan**（搭 `janhq/model-catalog`） | ★46,036 / ★12（NOASSERTION） | `https://raw.githubusercontent.com/janhq/model-catalog/main/model_catalog_v2.json` | 前端啟動抓遠端 JSON；`model-catalog` 每日 `02:00 UTC` 自動更新 | 無內建失敗退路（`fetchModelCatalog` 抓失敗直接 throw；雲端 API 仍需另設或待驗證） | 僅含本地 GGUF/MLX 模型權重下載中繼資料，不含雲端 API 金鑰目標端點；JSON 無簽章檢查 | [vite.config.ts](https://github.com/janhq/jan/blob/dev/web-app/vite.config.ts#L117-L119) / [default.ts](https://github.com/janhq/jan/blob/dev/web-app/src/services/models/default.ts#L50-L68) / [update-model-catalog.yml](https://github.com/janhq/model-catalog/blob/main/.github/workflows/update-model-catalog.yml#L4-L6) |
| **lobehub/lobehub**（原 `lobe-chat`） | ★86,010（NOASSERTION） | 內建套件 `packages/model-bank`＋ 執行期呼叫 `ModelsService.getModels(provider)` 打 `/v1/models` | `model-bank` 隨 PR 合入 `canary` 發布 npm（無定時爬取 cron）；執行期手動觸發或環境變數 `OPENAI_MODEL_LIST` 覆寫 | 有：`packages/model-bank` 隨版本內建；可關掉客戶端抓取或手動覆寫模型 | 遠端不控制內建供應商預設 `base_url`；透過環境變數或設定管控清單 | [release-model-bank.yml](https://github.com/lobehub/lobehub/blob/main/.github/workflows/release-model-bank.yml#L1-L40) / [models.ts](https://github.com/lobehub/lobehub/blob/main/src/services/models.ts#L44-L79) |
| **chatboxai/chatbox** | ★42,491（GPL-3.0） | 三層合併（使用者自存 > 後端遠端 manifest／供應商 API > 內建 `curatedModelIds`）＋ `https://models.dev/api.json` | 啟動與背景檢查；`models.dev` 設有 7 天 Blob 快取 | 有：編譯期快照 `snapshot.generated.ts` 與舊快取維持（UI 是否提供完全關閉開關：待驗證） | 內建供應商路由鎖在 `src/shared/providers/registry`；遠端資料不改動現有內建供應商金鑰送出路徑 | [ai-providers.md](https://github.com/chatboxai/chatbox/blob/main/docs/technical/ai-providers.md#L91-L225) |
| **maximhq/bifrost** | ★9,957（Apache-2.0） | `https://getbifrost.ai/datasheet`（預設 `DefaultURL`）與 `/datasheet/model-parameters`＋ 各供應商即時 `list-models` | 價格表預設每 24 小時（可設 `pricing_sync_interval`，最低 3600 秒）；即時模型同步預設 60 分鐘（設 `0` 關閉） | 有：URL 失敗自動退回資料庫既有價格紀錄；`LiveModelsSyncInterval = 0` 與 `MCPLibrarySyncDisabled = 0` 可關背景拉取 | `NewPrivateNetworkHTTPClient` 防 SSRF；`Entry.AdditionalAttributes` 加上 `json:"-"` 防止 URL JSON 反序列化注入管理欄位 | [store.go](https://github.com/maximhq/bifrost/blob/main/framework/modelcatalog/datasheet/store.go#L20-L43) / [sync.go](https://github.com/maximhq/bifrost/blob/main/framework/modelcatalog/datasheet/sync.go#L41-L90) / [types.go](https://github.com/maximhq/bifrost/blob/main/framework/modelcatalog/datasheet/types.go#L53-L58) / [config.go](https://github.com/maximhq/bifrost/blob/main/framework/modelcatalog/config.go#L12-L70) |
| **OpenRouter `/api/v1/models`** | 商業代理服務（公開 API） | `https://openrouter.ai/api/v1/models`（2026-11-23 實測 HTTP 200、927 KB、477 模型、15 個免費模型） | 即時／CDN 邊緣快取（`Cache-Control: public, max-age=120, stale-while-revalidate=3600`） | 由消費端實作快取與過濾；支援 `openrouter/free`、`openrouter/auto` 等虛擬模型（內部挑選細節：待驗證） | 單一可信 API 來源；免費模型明確以 `pricing.prompt == "0"` 且 `pricing.completion == "0"` 辨識，含 `expiration_date` 欄位 | 2026-11-23 實測 GET `https://openrouter.ai/api/v1/models` 回應標頭與 JSON 結構 |
| **mvalentsev/awesome-free-ai-coding** | ★264（MIT） | Repo 內 Markdown 與資料定義（靠探測原廠 + 官方報價頁更新） | `update.yml` 每週一、四 `05:23 UTC` 探測更新並直推 `main`；`expire.yml` 每小時過期下架推 `main` | 此為純靜態資料倉儲；無用戶端自動同步器 | `freetier-quotes` 要求比對官網公開頁面原文驗證限額，減少 LLM 幻覺誤改 | [update.yml](https://github.com/mvalentsev/awesome-free-ai-coding/blob/main/.github/workflows/update.yml#L4-L192) / [expire.yml](https://github.com/mvalentsev/awesome-free-ai-coding/blob/main/.github/workflows/expire.yml#L4-L53) |
| **mnfst/awesome-free-llm-apis** 與 **modeldeprecations.dev** | ★13,997（CC0-1.0）/ ★3（MIT） | `awesome-free-llm-apis`：`data.json`（社群 PR＋外部監控）；`modeldeprecations.dev`：`https://modeldeprecations.dev/api/v1/models.json` | `awesome-free-llm-apis` 無定時 cron（由社群／`okapi.bot` 外部監控）；`modeldeprecations.dev` 每日 `04:00 UTC` 爬原廠棄用頁開 PR | 純靜態清單／靜態 JSON 端點，由用戶端決定如何快取與退回 | `awesome-free-llm-apis` 有 `validate-data.js` 與 `check-sources.js` CI 驗證 `data.json` 合法性 | [awesome-free-llm-apis ci.yml](https://github.com/mnfst/awesome-free-llm-apis/blob/main/.github/workflows/ci.yml) / [sources.yml](https://github.com/mnfst/modeldeprecations.dev/blob/main/.github/workflows/sources.yml#L4-L5) |
| **12britz/awesome-free-models** | ★2,671（NOASSERTION） | Repo 內 `README.md` 與 `docs/` 靜態網頁 | 純人工／社群 PR 更新（repo 無 `.github/workflows` 自動排程） | 靜態文件網站，無用戶端同步器 | 人工審核 PR 合入 | [tree](https://github.com/12britz/awesome-free-models/tree/HEAD) |
| **cheaper-inference/OmniRoute** | ★89,654（MIT） | 內建註冊表＋選用性背景同步 `models.opencode.ai/api.json`（旗標 `OPENCODE_PUBLISHED_CATALOG_ROUTING_ENABLED`） | 背景目錄 6 小時 TTL；上游 `nightly-derived-refresh.yml` 每日 `01:37 UTC` | 有：內建註冊表＋預設關閉遠端目錄覆寫，需顯式啟用旗標 | 別名表／家族手足替補皆受靜態白名單約束；`staleModelPrune` 自動剔除失效步驟預設亦為 opt-in | [FEATURE_FLAGS.md](https://github.com/cheaper-inference/OmniRoute/blob/main/FEATURE_FLAGS.md) / [modelFamilyFallback.ts](https://github.com/cheaper-inference/OmniRoute/blob/main/open-sse/services/modelFamilyFallback.ts) / [nightly-derived-refresh.yml](https://github.com/cheaper-inference/OmniRoute/blob/main/.github/workflows/nightly-derived-refresh.yml) |
| **QuantumNous/new-api** | ★52,364（AGPL-3.0） | 渠道管理介面觸發 `/api/channel/fetch_models/:id` 打上游 `/v1/models` 同步可用模型 | 管理員手動點擊抓取（自動定期掃描依賴外部社群腳本：待驗證） | 有：既有已寫入資料庫之渠道模型清單 | 僅對管理員已建置的指定渠道端點拉取模型 | [channel-router.go](https://github.com/QuantumNous/new-api/blob/main/router/channel-router.go) |
| **Portkey-AI/gateway** | ★13,431（MIT） | 內建 `src/data/models.json`（本地定價／模型資料）或轉發至 Control Plane `ALBUS_BASEPATH` | 隨版更新 `models.json` 或由外部 Control Plane 提供（Control Plane 內部自動同步週期：待驗證） | 有：未設定 `ALBUS_BASEPATH` 時可直接使用 Gateway 本地邏輯與使用者路由設定 | `modelsHandler.ts` 僅在帶有 `ALBUS_BASEPATH` 且未指定單一 provider 時代理目錄請求 | [modelsHandler.ts](https://github.com/Portkey-AI/gateway/blob/main/src/handlers/modelsHandler.ts#L11-L55) |

---

## 3. 問題一：不用升級程式就保持目錄最新的 4 種主流模式

綜合這 20 多個高星專案，業界讓「模型清單、價格、限額、停用狀態」脫離發版週期的方法，收斂為下列 4 種模式：

### 模式 A：版本化遠端靜態檔 ＋ 隨版打包快照退路 ＋ 環境關閉開關
這是最穩健、最適合桌面／自架單機應用的做法：
- **LiteLLM**：透過 `DEFAULT_REGISTRY_URL` 抓單一 `model_prices_and_context_window.json`（[policy.rs:16-17](https://github.com/BerriAI/litellm/blob/main/litellm/rust/crates/model-catalog-refresh/src/policy.rs#L16-L17)），本地備份 `model_prices_and_context_window_backup.json` 並用 `LITELLM_LOCAL_MODEL_COST_MAP=True` 或離線模式一鍵停用（[get_model_cost_map.py:4-5,72-74](https://github.com/BerriAI/litellm/blob/main/litellm/litellm_core_utils/get_model_cost_map.py#L4-L74)）。
- **pydantic/genai-prices**：在背景執行緒 `_SharedUpdater` 每小時拉取 `v2/data.json`（`update_interval=3600`），失敗無縫退回隨套件發行的 `data.py`（[update_prices.py:23-141](https://github.com/pydantic/genai-prices/blob/main/packages/python/genai_prices/update_prices.py#L23-L141)）。
- **Cherry Studio**：把更新目標鎖在**特定釋出分支 + Schema 版本子目錄**（`x-files/provider-registry/v{REGISTRY_SCHEMA_VERSION}`），先讀 `manifest.json` 檢查版本相容範圍與雜湊，再每 6 小時拉取（[ProviderRegistryUpdaterService.ts:31-180](https://github.com/CherryHQ/cherry-studio/blob/main/src/main/services/ProviderRegistryUpdaterService.ts#L31-L180)）。
- **OpenClaw Catalog**：發布端分 `v1/v2/v3/catalog.json` 靜態資產，且發版前自動抓 npm `latest` / `extended-stable` / `beta` 三版本實測讀取通過才推送，避免遠端清單改壞舊版用戶端（[openclaw/catalog README.md:3-68](https://github.com/openclaw/catalog/blob/main/README.md#L3-L68)）。

### 模式 B：接入跨專案共享的公共目錄樞紐（`models.dev` 生態 與 OpenRouter API）
- **`models.dev` 已成為編輯器與桌面客戶端的事實標準**：實測 `https://models.dev/api.json` 免金鑰、支援 HTTP `ETag`（2026-11-23 回傳 326 家供應商、6.91 MB）。`anomalyco/opencode`（5 分鐘 TTL + `If-None-Match` 304 + `snapshot.txt`）、`cline/cline`（10 分鐘 TTL + 編譯預設退路）、`chatboxai/chatbox`（7 天 Blob 快取 + `snapshot.generated.ts`）都直接消費它。
- **OpenRouter `/api/v1/models` 適合作為單一聚合平台即時探測**：2026-11-23 實測無需 API Key 即可取回 477 個模型（含 15 個 `prompt="0"` 且 `completion="0"` 的免費模型），還直接附帶 `expiration_date` 與 `per_request_limits`。
- **對 OmniKeep 的限制**：`models.dev` 與 OpenRouter 不會收錄各種「區域小廠／特殊優惠免費管道／無需註冊免 Key 端點／特定 `extra_body`（如禁用 thinking 的廠商參數）」的限制說明與贈金截止日，因此**不能單靠 `models.dev` 取代 `CARDS`**，只適合當部分供應商的「模型中繼資料／上下架參照來源」。

### 模式 C：執行期由用戶端打供應商 `/v1/models`（按權限或僅作「補充／提示」）
- **全動態路線（Open WebUI、Continue `AUTODETECT`、new-api 手動同步）**：前提是該端點的每個回應都必須是「使用者已確定要用、且格式單一的對話模型」；但實務上免費聚合站或大廠 `/v1/models` 常夾雜 Embedding、TTS、Whisper、付費專用或未開通權限的模型（例如我們看到 `tashfeenahmed/freellmapi` 與 `Cherry Studio` 都特別把遠端／發現的模型和預設可用模型分層管理）。
- **混合謹慎路線（Cline、LibreChat、FreeLLMAPI、Chatbox）**：
  - `LibreChat` 允許在設定中開啟 `models.fetch: true`，但強制要求設定 `models.default` 作為退路（[loadDefaultModels.js](https://github.com/LibreChat-AI/LibreChat/blob/main/api/server/services/Config/loadDefaultModels.js)）。
  - `FreeLLMAPI` 內建端點發現明確**只允許兩個白名單供應商** `['longcat', 'siliconflow']`，且預設模式為 `'manual'` 而非全自動（[builtin-model-discovery.ts:50-66](https://github.com/tashfeenahmed/freellmapi/blob/main/server/src/services/builtin-model-discovery.ts#L50-L66)）；自訂端點同步則套用免費名稱規則過濾並「只增不刪」（[custom-model-sync.ts:27-36](https://github.com/tashfeenahmed/freellmapi/blob/main/server/src/services/custom-model-sync.ts#L27-L36)）。

### 模式 D：免費管道社群目錄（半自動／排程更新上游倉庫）
- **`tashfeenahmed/freellmapi`** 為目前罕見同時具備**用戶端背景拉取＋簽章認證＋本地退路**的免費 API 專案（每 12 小時同步、免費安裝版享約 30 天公版更新，付費版每 2–3 天更新，見 [05-catalog-sync.md](https://github.com/tashfeenahmed/freellmapi/blob/main/docs/en/architecture/05-catalog-sync.md)）。
- **`mvalentsev/awesome-free-ai-coding`**、**`mnfst/awesome-free-llm-apis`**、**`12britz/awesome-free-models`** 本身只維護 GitHub Repo 清單檔案，沒有內建用戶端背景更新器，這類來源最適合由維護端腳本（如 OmniKeep 既有的 `scripts/free_channel_watch.py`）當成上游情報，而不建議讓使用者端直接無審核採信。

---

## 4. 問題二：遠端更新清單的安全風險與 7 層實戰防護

### 為什麼直接從遠端更新整張服務卡很危險？
以 OmniKeep 的結構來說，使用者已把各家 API Key 存在本機，發送請求時會將 Key 送到該張卡設定的 `base_url`（[app/provider_catalog.py](file:///C:/Users/user/Desktop/OmniKeep/app/provider_catalog.py#L29-L382)）。如果允許未經驗證或過寬的遠端 JSON **直接覆寫既有卡片的 `base_url`、`headers`、或動態注入一張偽造的「OpenAI / Gemini 免費卡片」指向攻擊者域名**，一旦使用者帳號被盜、GitHub repo/CDN 遭劫持、或遇到中間人置換：
> 使用者的真實 API Key 會在下一次 AI 摘要或測試連線時，直接被送到攻擊者控制的中轉伺服器。

業界針對此風險有非常明確且一致的防護設計，整理為以下 7 層實戰措施：

1. **嚴格拆分「不可變路由邊界」與「遠端可更新資料欄位」（最關鍵、零密碼學門檻）**
   - **Cherry Studio** 在 [ProviderRegistryUpdaterService.ts:73-74](https://github.com/CherryHQ/cherry-studio/blob/main/src/main/services/ProviderRegistryUpdaterService.ts#L73-L74) 明文寫下原則：「Provider routing remains bundled because unsigned data must never control credential destinations.」（供應商路由必須隨版打包，未簽章資料絕不能決定憑證送往哪裡）。
   - **OpenClaw Catalog** 在 [README.md:92-94](https://github.com/openclaw/catalog/blob/main/README.md#L92-L94) 同樣硬性規定於用戶端邏輯：「遠端目錄只能更新模型中繼資料，絕對不能修改供應商端點（endpoints）、標頭（headers），或新增本機尚未隨版安裝的供應商（providers）。」
   - **對應 OmniKeep**：只允許遠端更新**既有 `card_id`** 下的 `model`、`models`、`limits`、`quota`、`ends`、`verified`、`notes`、`disabled`/`deprecated`、`caps.extra_body`（需為白名單 JSON key）等資料欄位；**禁止遠端改寫或新增任何 `base_url`、`key_mode`、`key_url`、`kind`**。

2. **非對稱加密簽章與用戶端公鑰釘選（Pinning）**
   - 如果未來一定要允許遠端下發新卡片或修改端點，必須學 **FreeLLMAPI**：[catalog-sync.ts:47-52](https://github.com/tashfeenahmed/freellmapi/blob/main/server/src/services/catalog-sync.ts#L47-L52) 將 **Ed25519 公鑰（`PINNED_CATALOG_PUBKEY`）寫死在程式內**，每次遠端回覆必須通過 HTTP Header `x-catalog-signature` 與 `crypto.verify` 驗證才寫入本地資料庫。即使 CDN、GitHub Raw 快取或中間傳輸遭換包，只要私鑰沒外洩就無法通過驗證。

3. **結構化欄位防注入（Anti-Injection / Field Isolation）**
   - **Bifrost** 在 Go 結構體 [types.go:53-58](https://github.com/maximhq/bifrost/blob/main/framework/modelcatalog/datasheet/types.go#L53-L58) 對管理屬性 `AdditionalAttributes` 刻意加上 `json:"-"`，確保遠端 JSON 反序列化時永遠無法覆寫內部信任欄位。
   - **OmniKeep 實作建議**：寫一個明確的 `REMOTE_MUTABLE_FIELDS` 許可集合，合併時明確逐鍵挑選，絕不用 `{**card, **remote_patch}` 整包覆蓋。

4. **單調遞增版本號與最低版本防降級鎖（Anti-Rollback + Atomic Snapshot）**
   - **FreeLLMAPI** 寫死最低門檻 `MIN_CATALOG_VERSION = '2026.06.07'`（[catalog-sync.ts:56](https://github.com/tashfeenahmed/freellmapi/blob/main/server/src/services/catalog-sync.ts#L56)）並帶 `?since=<appliedVersion>`。
   - **Cherry Studio** 實作兩道防線（[ProviderRegistryUpdaterService.ts:146-179](https://github.com/CherryHQ/cherry-studio/blob/main/src/main/services/ProviderRegistryUpdaterService.ts#L146-L179)）：
     - `isCatalogManifestCompatible` 檢查 `schemaVersion` 與 `minAppVersion <= appVersion <= sourceAppVersion`，確保舊版 App 不會吞下破壞性 Schema。
     - 若遠端 `manifest.revision <= activeManifest.revision`，直接拒絕（防攻擊者重放舊版含已下架漏洞/過期條目的目錄）。
     - 比對各檔案雜湊與 manifest 紀錄是否一致，防範抓取期間剛好發布造成「跨 commit 撕裂」。

5. **Schema 校驗與縮水門檻檢查（Sanity & Shrink Guards）**
   - **LiteLLM** 檢查遠端列表模型數 `< 50` 或縮水低於內建版本 `0.5` 倍就拒絕套用（[constants.py:202-206](https://github.com/BerriAI/litellm/blob/main/litellm/constants.py#L202-L206)）。
   - **OpenClaw Catalog** 在發布 CI 擋下「單次縮水 `> 5%`」或「整家供應商被抹除」的異常輸出（[README.md:38-42](https://github.com/openclaw/catalog/blob/main/README.md#L38-L42)）。
   - **OpenCode / Pydantic / Cherry Studio** 均先做 Schema 驗證（如 Pydantic / Zod），不合格則整包拋棄或略過損毀單筆，絕不污染運行中設定。

6. **固定來源網址、禁止開放重定向與 SSRF 防護**
   - 遠端清單 URL 應固定為官方 HTTPS URL（如 GitHub Releases / 專屬分支或受控 CDN），禁止遠端 payload 裡自己指定「下一個 redirect URL」。
   - 發起任何遠端清單或 `/v1/models` 檢查時，複用專案既有的安全 HTTP Client（OmniKeep 在 [app/connection_checks.py](file:///C:/Users/user/Desktop/OmniKeep/app/connection_checks.py) 已有 `public_http_client` / `UnsafeURL` SSRF 防護；Bifrost 透過 `network.NewPrivateNetworkHTTPClient`；LibreChat 強制 `validateEndpointURL` 且 `maxRedirects = 0`）。

7. **使用者覆寫優先權保護、一鍵關閉與本地退路**
   - **FreeLLMAPI** 保護 `source = 'user'` 的使用者自訂項目與手動刪除的 `catalog_model_tombstones`，同步永遠不覆蓋使用者手動決定。
   - **LiteLLM**（`LITELLM_LOCAL_MODEL_COST_MAP=True`）、**OpenClaw**（`models.catalogRefresh.enabled: false`）、**Bifrost**（`interval = 0`）均提供明確關閉遠端連線的開關，讓隱私敏感或離線內網環境能 100% 拒絕向外連線。

---

## 5. 問題三：執行期 404 / model_not_found 自我修復做法

這是調研中最反直覺、但各家架構師高度一致的結論：
> **沒有任何大型開源 Gateway 或聊天客戶端會在正式請求收到 `404 / model_not_found` 時，「自動向未知廠商打 `/v1/models` 並直接挑第一個模型拿來代打」。**

主要原因對照 OmniKeep 尤其明顯：
1. `/v1/models` 回傳常混雜 Embedding、生圖、語音、甚至需要付費扣款的模型，免費或能力不確定（例如 OmniKeep 的卡片有 `caps.json_mode`、`extra_body` 關思考模式等嚴格前提，隨便換一個模型會直接導致輸出壞掉或扣款）。
2. `/v1/models` 並不保證回傳的 ID 在當前帳號下真的沒撞額度或真的免費（例如某些代理站列出全平台數百個模型，但免費帳號僅能呼叫其中幾個）。

因此，業界處理 404／模型下架的執行期自癒分成以下 4 層務實作法：

### 作法 1：404／410 自動退役 ＋ 切換至已驗證的備援鏈（主流、安全最高）
- **tashfeenahmed/freellmapi** 實作最精緻的執行期退役機制（[model-retirement.ts:1-119](https://github.com/tashfeenahmed/freellmapi/blob/main/server/src/services/model-retirement.ts#L1-L119)、[model-state.ts:232-267](https://github.com/tashfeenahmed/freellmapi/blob/main/server/src/services/model-state.ts#L232-L267)）：
  - 若上游回傳明確停產訊號（如 **HTTP 410 Gone**），`noteModelRetirementSignal()` 立刻停用該目錄模型並打上 `upstream_eol` 標籤，請求隨即交給 `fallback_config` 既定備援鏈處理。
  - 若是可能偶發的 **HTTP 404**（`probable` 訊號），設觀察期 `RETIREMENT_OBSERVATION_WINDOW_MS = 60 * 60 * 1000`（1 小時），累計 `RETIREMENT_CONFIRMATIONS_REQUIRED = 2` 次不同請求失敗後才正式自動退役，避免單次上游誤報就把整個模型殺掉。
  - 保留自動恢復入口：若下次簽章遠端目錄更新時該模型仍處於啟用狀態，或使用者手動重開，即自動解除 `upstream_eol`。
- **BerriAI/litellm**：Router 的 `cooldown_handlers.py:83-85` 將 `404` 明確定義為 `_NOT_FOUND = _OnlyStatuses(frozenset({404}))`，觸發該部署冷卻並依 `fallbacks` 清單切換備援部署，而不亂猜新模型名稱。
- **對比 OmniKeep 現況**：OmniKeep 的 [app/providers/chain.py](file:///C:/Users/user/Desktop/OmniKeep/app/providers/chain.py#L43-L47) 目前僅把 `not_found` 冷卻 6 小時（重開服務或 6 小時後又會重踩一次 404）；可借鏡 FreeLLMAPI 將單卡的連續 404（例如 1 小時內 >= 2 次且未成功過）進一步標記為持久降權或「建議更新／已下架」狀態顯示在 UI，先由 `ChainProvider` 切換至下一張卡或同卡內的備用 `models` 清單。

### 作法 2：同家族手足降級與已知棄用別名表（Zero-Discovery 安全改寫）
- **cheaper-inference/OmniRoute**：
  - 維護靜態 + 自訂棄用模型別名對照表 [modelDeprecation.ts](https://github.com/cheaper-inference/OmniRoute/blob/main/open-sse/services/modelDeprecation.ts)，遇到舊版下架 ID 直接靜默轉譯成官方接班模型 ID。
  - 實作 [modelFamilyFallback.ts](https://github.com/cheaper-inference/OmniRoute/blob/main/open-sse/services/modelFamilyFallback.ts)：當特定模型回傳 400／404 時，只在同一條事先校驗過的「同家族手足鏈」內往相鄰版本降級／替代（不跨家族亂跳）。
  - 另有 opt-in 的 [staleModelPrune.ts](https://github.com/cheaper-inference/OmniRoute/blob/main/src/lib/combos/staleModelPrune.ts)，依環境旗標決定是否將屢次失效的節點從組合裡修剪。
- **對應 OmniKeep**：這套完全貼合 OmniKeep `CARDS` 裡的 `model`（主選）與 `models`（預設候選列表）！當主要 `model` 回 404 時，可以先優先試試**同一張卡的 `models` 陣列中剩餘候補**（例如從已被測試過的同卡其他免費模型挑選），全部 404 才把整張卡標記冷卻並切換 `ChainProvider` 下一張卡。

### 作法 3：受白名單／規則嚴格限制的 `/v1/models` 發現 ＋ 使用者確認同步
- **FreeLLMAPI**：
  - 對內建供應商只有白名單 `['longcat', 'siliconflow']` 會查端點模型，且預設要手動執行 `'manual'`（[builtin-model-discovery.ts:50-66](https://github.com/tashfeenahmed/freellmapi/blob/main/server/src/services/builtin-model-discovery.ts#L50-L66)）。
  - 對自訂端點每 24 小時跑 `custom-model-sync.ts`，但也**「只增不刪」**且對 OpenRouter 等聚合端點套用免費字尾過濾（[custom-model-sync.ts:27-36](https://github.com/tashfeenahmed/freellmapi/blob/main/server/src/services/custom-model-sync.ts#L27-L36)）。
- **Cline / Cherry Studio / Chatbox / Open WebUI**：都是在「測試連線按鈕」或「設定頁模型選擇器」中呼叫 `/v1/models` 抓回列表並快取（5 分鐘到數天不等），交由 UI 呈現給使用者點選，或搭配固定清單過濾非聊天模型（embed/whisper/image）。
- **對應 OmniKeep**：當 `not_found` 發生或使用者點擊「連線測試 / 重新整理模型」時，可以打一次 `{base_url}/models`（限制回應 <= 2 MB、只取前 200 筆、過濾明顯的 `embed`/`tts`/`whisper`/`image`），**把結果「推薦列出在設定 UI」或只針對已知 `free` 規則做建議**，不要直接在背景靜默篡改進正式摘要管線。

### 作法 4：採用支援伺服端動態路由的穩定虛擬模型（Meta-Model）
- 2026-11-23 實測 `https://openrouter.ai/api/v1/models` 本身已提供 `openrouter/free`、`openrouter/auto` 等虛擬 model ID。
- 把 OpenRouter 卡片的預設或備援模型之一設為 `openrouter/free`，就把「單一免費模型每週下架改名」的 404 維護成本直接交由聚合端解決（該虛擬模型的內部路由器具體挑選權重與排隊演算法：待驗證）。

---

## 6. 問題四：誰去發現變動（排程、探測與自動 PR / 下架）

從各開源專案的 `.github/workflows` 可看到 3 種非常成熟的變更發現管線：

1. **自動化爬蟲 ＋ 無權限與有權限 Job 分離 ＋ 自動開 PR（主流大廠／目錄專案做法）**
   - **`anomalyco/models.dev`**（[sync-models.yml:4-11](https://github.com/anomalyco/models.dev/blob/dev/.github/workflows/sync-models.yml#L4-L11)）：每 6 小時跑一次 `cron: "17 */6 * * *"`。為了供應鏈安全，先把抓資料（產出 patch artifact）與開 PR（用 GitHub App token 且只准改動目錄 TOML、依供應商各自開 PR、安全變更自動 merge）拆成兩個權限完全隔離的 Job。
   - **`pydantic/genai-prices`**（[update-prices.yml:3-44](https://github.com/pydantic/genai-prices/blob/main/.github/workflows/update-prices.yml#L3-L44)）：每小時 `cron: "17 * * * *"` 同步 32 家直連廠商、每週一 `cron: "47 6 * * 1"` 同步 Hugging Face / OpenRouter，自動開 `automation/hourly-price-update` PR；另配備 `agentic-price-check.lock.yml` 輔助巡檢價目異常。
   - **`CherryHQ/cherry-studio`**（[auto-update-catalog.yml:4-80](https://github.com/CherryHQ/cherry-studio/blob/main/.github/workflows/auto-update-catalog.yml#L4-L80)）：每日 `00:00 UTC` 自動產出模型更新開 PR 至 `main`，待 CI 驗證與合入後，由第二條 `sync-registry-data.yml` 推送到用戶端專門抓取的 `x-files/provider-registry` 靜態分支，讓「PR 審查」和「用戶端線上目錄」之間隔出一道人審／CI 防火牆。
   - **`openclaw/catalog`**（[README.md:38-68](https://github.com/openclaw/catalog/blob/main/README.md#L38-L68)）：每 4 小時自動產製並檢查縮水門檻 `<= 5%`、驗證舊版用戶端 `released-readers.mjs` 全數讀得過才推至靜態託管。
   - **`mnfst/modeldeprecations.dev`**（[sources.yml:4-5](https://github.com/mnfst/modeldeprecations.dev/blob/main/.github/workflows/sources.yml#L4-L5)）：每日 `04:00 UTC` 專門抓取各家原廠棄用通知頁面並開 PR，直接以結構化 JSON 追蹤模型下架與預告日。

2. **定時探測 ＋ 失敗轉交 LLM 偵查兵 ＋ 官方頁面原文比對（最適合免費管道）**
   - **`mvalentsev/awesome-free-ai-coding`**（[update.yml:4-192](https://github.com/mvalentsev/awesome-free-ai-coding/blob/main/.github/workflows/update.yml#L4-L192)）的做法極具參考價值：每週一、四 `05:23 UTC` 先用腳本 `freetier-probe` 真實打各免費服務商；遇到探測失敗的條目才啟動 LLM 偵查兵（`scout_backend`）去搜尋最新公告，再透過 `freetier-quotes` 強制擷取並核對官網頁面原文引用才寫入清單，最後跑完檢查測試才推送更新。這種設計避免了「盲信 LLM 記憶亂改免費模型名稱」的幻覺問題。

3. **專職促銷／限額到期自動下架排程（Low-Cost / High-Value）**
   - **`mvalentsev/awesome-free-ai-coding`**（[expire.yml:4-53](https://github.com/mvalentsev/awesome-free-ai-coding/blob/main/.github/workflows/expire.yml#L4-L53)）：將「抓新聞」和「算到期」拆開！`expire.yml` **每小時執行一次** `cron: "11 * * * *"`，單純檢查有 `ends`／期限欄位的條目是否已過期並下架，計算成本極低卻能防止過期促銷卡長期留在推薦列表誤導使用者。

---

## 7. 給 OmniKeep 的 3 個架構方案組合與取捨

結合 OmniKeep 現有結構（Python FastAPI 服務、單機自架、[app/provider_catalog.py](file:///C:/Users/user/Desktop/OmniKeep/app/provider_catalog.py)、[app/providers/chain.py](file:///C:/Users/user/Desktop/OmniKeep/app/providers/chain.py)、[app/connection_checks.py](file:///C:/Users/user/Desktop/OmniKeep/app/connection_checks.py)、[scripts/free_channel_watch.py](file:///C:/Users/user/Desktop/OmniKeep/scripts/free_channel_watch.py)），建議從簡到繁考慮以下 3 種組合：

### 方案 1：保守穩健型 —「獨立遠端 Data JSON + 不可變路由邊界 + 週排程開 PR」（推薦首選）
- **架構設計**：
  1. **拆出純資料檔 + 不可變端點邊界**：在 repo 新增版本化目錄分支或專屬路徑（例如 `catalog/v1/manifest.json` 與 `catalog/v1/cards_patch.json`），僅包含高變動欄位：`cards[id]` 下的 `model`、`models`、`limits`、`quota`、`ends`、`verified`、`notes`、`status`（如 `active` / `deprecated`）與安全白名單 `caps`。**`base_url`、`kind`、`key_mode`、`key_url` 永遠鎖在隨程式發版的 [app/provider_catalog.py](file:///C:/Users/user/Desktop/OmniKeep/app/provider_catalog.py)**，遵循 Cherry Studio／OpenClaw 安全邊界。
  2. **用戶端背景輕量同步**：OmniKeep 啟動 30 秒後及每 12 小時以既有 `public_http_client`（帶 `ETag` / `If-None-Match`）抓取固定 GitHub Raw／Release JSON，存入本地設定目錄快取；驗證 JSON Schema + `min_app_version` + 單調遞增 `revision` + 筆數不可縮水超過 20% 才套用；失敗靜默退回隨版 `CARDS`。提供設定開關 / 環境變數 `OMNIKEEP_CATALOG_AUTO_UPDATE=0` 讓使用者一鍵關閉。
  3. **自動化變更發現（CI 開 PR）**：將現有 [scripts/free_channel_watch.py](file:///C:/Users/user/Desktop/OmniKeep/scripts/free_channel_watch.py) 升級為 GitHub Actions 排程（例如每日或每週二次），比對 `OpenRouter /api/v1/models`（只篩 `pricing.prompt == "0"` 且 `pricing.completion == "0"`）、`models.dev/api.json`、`freellmapi` 與 `modeldeprecations.dev`；有異動時自動產生 `cards_patch.json` Diff 並開 PR，**經維護者核准 merge 到發布分支後**，所有不升級程式的使用者 12 小時內自動同步。
  4. **執行期自癒增強**：在 `ChainProvider` 遇到 `not_found`（404）時，若同一張卡的 `models` 陣列仍有其他已測試候補模型，優先在同一張卡內嘗試下一個模型；連續 2 次失敗才進入現有 6 小時冷卻並切換備援鏈，同時把該卡 UI 標記「遠端模型可能已下架，請檢查更新或重試連線」。
- **優點**：安全性最高（即使 GitHub 快取或 CDN 異常也偷不到 API Key、零密碼學金鑰管理維運負擔）；與現有 [app/provider_catalog.py](file:///C:/Users/user/Desktop/OmniKeep/app/provider_catalog.py) 和 [scripts/free_channel_watch.py](file:///C:/Users/user/Desktop/OmniKeep/scripts/free_channel_watch.py) 完全相容、改動量最小；所有變動進使用端前仍保有 CI 檢查與維護者一鍵點 merge 的人工品質閥門（保護 `json_mode` 與中文摘要可用性）。
- **取捨／缺點**：上游完全新增一家「程式裡還沒有卡片定義」的新免費廠商時，仍然需要透過升級 OmniKeep 來發放該廠商的 `base_url`；且依賴維護者在 GitHub 上點 merge（除非日後加上嚴格實測 Probe 後改半自動合入）。

### 方案 2：即時自治型 —「方案 1 ＋ OpenRouter/聚合端即時模型同步與 404 受限 `/v1/models` 推薦」
- **架構設計**：
  - 在方案 1 基礎上，新增兩項執行期能力：
    1. **OpenRouter 等聚合卡片**：直接將 `openrouter/free` 列為內建 `models` 首選或最終退路（2026-11-23 實測存在於官方列表），並允許使用者在設定頁一鍵／背景每 24 小時從 `https://openrouter.ai/api/v1/models` 篩出目前 `prompt == "0" & completion == "0"` 的免費文字模型清單更新進選擇器。
    2. **自癒降級與受限 `/v1/models` 探測**：遇到某卡 `not_found`（404）或點擊 UI「檢查更新模型」時，針對該張已知安全的 `base_url`（由本機代碼提供，不受遠端改寫）呼叫 `{base_url}/models`（限制大小 <= 2 MB、只取前 200 筆並過濾掉 embedding/image/audio/tts），若發現既有清單中的同家族接班版本（例如前綴相同、版本遞增）或明顯免費用詞 `:free`，先標記提示給使用者選用；**可選開關「404 時自動試打 `/v1/models` 過濾後僅挑選同家族替代模型」**（預設關閉或僅用於單純文字摘要）。
- **優點**：像 OpenRouter / Groq / Cerebras 這類會即時回報 `/models` 且免費規則清晰的平台，能做到一週內模型改名也能幾乎零維護成本自癒。
- **取捨／缺點**：必須謹慎防範各廠 `/v1/models` 格式差異與誤選到付費／不支援 `json_mode`／開啟昂貴思考消耗大量 token 的模型；實作複雜度高於方案 1，需為每家供應商加寫欄位對齊或安全白名單（就像 FreeLLMAPI 只開 `['longcat', 'siliconflow']`）。

### 方案 3：全開放遠端增刪卡片型 —「Ed25519 簽章遠端完整目錄 ＋ 離線金鑰發佈」（不建議近期直接採用）
- **架構設計**：完全仿照 `tashfeenahmed/freellmapi` 的 `catalog-sync.ts`，讓遠端 JSON 可直接**新增新卡片（包含新的 `base_url`、`key_url`、`extra_body`）或覆寫端點**，並要求維護者建立離線 Ed25519 簽章私鑰與發布管線，在 OmniKeep 用戶端寫死 `PINNED_CATALOG_PUBKEY` 強制驗證 `x-catalog-signature`（或獨立 `.sig` 檔）與防回滾序號。
- **優點**：真正做到「不用升級程式也能上線全新免費 AI 供應商卡片」。
- **取捨／缺點**：資安與維運責任大幅提高（公私鑰輪替、私鑰保護、防止 GitHub Action 權限濫用直接簽發惡意端點），且無法避免新增供應商在使用者舊版 Python 請求器上的 `kind`／協定實作不相容問題（例如需要新的認證標頭或 SSE 格式）。對 OmniKeep 這類小型開源單機專案而言，投資報酬率不如方案 1（或方案 1+2）。

---

## 8. 飽和式調研過程與管道紀錄

本調研依 `omnikit-research` skill 與 [sweep.py](file:///C:/Users/user/.t3/userdata/providers/antigravity/fda30731acda5ac31ffc7ad7cb566f9f1e8dac1aa3f53e7b3dcceb14a888ddb6/config/skills/omnikit-research/scripts/sweep.py) 執行跨管道掃描並登錄於本機帳本：

### 查了哪些管道與關鍵字
- **使用管道**：`github-topic`、`github-keyword`、`awesome`、`skills-sh`、`npm`、`mcp-registry`、`hn`、`exa`、`web-en`（全部 12 組完成）；`web-zh`（第 3 組「free llm api list auto update」補充中文生態）；`producthunt`（第 2 組補充查詢）；`related`（追蹤 `BerriAI/litellm`、`anomalyco/models.dev`、`tashfeenahmed/freellmapi` 相關專案）。
- **查閱的 12 組關鍵字（每組均從前面發現詞彙往外擴展）**：
  1. `llm model catalog auto update`（新增 44）
  2. `model pricing list json fallback`（新增 48）
  3. `free llm api list auto update`（新增 31，含 `web-zh`）
  4. `llm provider models.dev sync`（新增 20）
  5. `free llm router fallback 404`（新增 16）
  6. `llm gateway model discovery`（新增 25）
  7. `signed model catalog json`（新增 3）
  8. `llm pricing database github action`（新增 10）
  9. `openai compatible client v1 models refresh`（新增 7）
  10. `remote json catalog signature verification`（新增 3）
  11. `llm model deprecation 404 fallback`（新增 10）
  12. `ai model registry remote fallback`（新增 7）

### 第幾輪停與飽和狀態說明
- 依據 `sweep.py status --min-stars 1000` 輸出統計：
  - **總計去重項目**：222 個不重複名稱
  - **全名單連續無新名稱組數**：`連續 0 組沒有新名字`（因第 12 組仍有 7 個長尾小專案，且已達 `MAX_GROUPS = 12` 上限）
  - **★1,000 以上 GitHub repo 連續無新名稱組數**：**`連續 3 組沒有新的（要 3 組）`**（第 10、11、12 組出現 `0` 個 ★1,000 以上新 GitHub repo，於第 12 組達標停止）
  - **報告定性**：依 `omnikit-research` 規範標記為 **「長尾未飽和」**（並如上附兩種連續數：`全部名字連續 0 組無新名稱；★1,000 以上 GitHub repo 連續 3 組無新名稱`）。

### 哪些管道查不到或受限
1. **閉源商業產品（例如部分商業桌面／SaaS 客戶端或私有控制台）**：無公開原始碼可讀取遠端刷新策略與簽章設計，本報告不以猜測填入，僅就公開開源代碼與實測 API 回應下結論。
2. **GitHub Code Search API（`gh search code`）**：高頻呼叫會觸發 GitHub 二次速率限制（HTTP 403）；本次調研改以 `gh api repos/<owner>/<repo>/git/trees/<branch>?recursive=1` 搭配直接抓原始檔克服，所有表列專案均取得實質原始碼行號或官方 README 原文。
3. **部分小細節未在公開檔案看見開關或說明**：如 Cherry Studio UI 是否另設隱藏設定頁面關閉 `ProviderRegistryUpdaterService`（僅在程式看到 `!app.isPackaged` 條件）、Chatbox 桌面 UI 是否提供單獨關閉 `models.dev` 同步開關、OpenRouter `openrouter/free` 背後選路權重邏輯、Portkey Control Plane 雲端端內部更新頻率、`QuantumNous/new-api` 外部社群自動抓模型腳本，皆已於比較表與正文逐項標示「待驗證」。
