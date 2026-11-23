# OmniKeep 每週免費 LLM 管道查證與目錄更新報告（2026-11-23）

- **執行日期**：2026-11-23
- **Git 提交與推送**：commit `b4456f3`（已 push 至 `origin/main`，更新 [app/provider_catalog.py](file:///C:/Users/user/Desktop/OmniKeep/app/provider_catalog.py) 與 [catalog/omnikeep-catalog.json](file:///C:/Users/user/Desktop/OmniKeep/catalog/omnikeep-catalog.json)，`CATALOG_REVISION = 2026112302`）
- **測試結果**：`python -X utf8 -m pytest -q --basetemp="$env:LOCALAPPDATA/Temp/okpt/weekly" -p no:cacheprovider` -> `1431 passed, 2 skipped, 1 warning in 208.45s (0:03:28)`

---

## 一、前置檢查與週報執行（步驟 0–1）

- **工作區檢查**：執行 `git status --short` 回傳乾淨，`git pull --rebase` 回傳 `Already up to date.`（僅含已知無害 worktree 刪除權限訊息）。
- **腳本執行**：執行 `python scripts/free_channel_watch.py` 回傳 exit code 0。因今天（2026-11-23）稍早已跑過並更新快照，本次輸出比較基準為 `2026-11-23`（現有卡片變動顯示「沒有」；限時活動顯示 **Itera Compute（Qwen3.8 27B）** 將於 `2026-11-24` 結束、剩 1 天）。
- **參考依據**：改讀取 `%LOCALAPPDATA%\OmniKeep\free_channel_watch\` 的最新 `snapshot.json`（與 `report-2026-11-22.md`）以及本次任務點名的 5 家變動（BazaarLink、Groq、NVIDIA NIM、Requesty、Z.ai）與 1 項限時活動（Itera Compute），逐一到官方文件與 `/v1/models` 查證。

---

## 二、現有卡片官方查證與更新明細（步驟 2–3）

本次僅異動現有卡片之資料欄位（`models`、`limits`、`notes`、`verified`）與 `CATALOG_REVISION`；未改動任何 `base_url`、`kind`、`key_mode`、`key_url`，未新增或刪除卡片，且不含「訓練」字樣。所有點名卡片皆為 `key_mode: "required"`，無法不帶金鑰實測，未實測項目均於 `notes` 標明。

### 1. `bazaarlink`（BazaarLink（免費模型））
- **檔案位置**：[app/provider_catalog.py:164-176](file:///C:/Users/user/Desktop/OmniKeep/app/provider_catalog.py#L164-L176)
- **官方查證來源**：
  - `https://bazaarlink.ai/free`、`https://api.bazaarlink.ai/v1/models`、`https://bazaarlink.ai/en/docs/api`、`https://bazaarlink.ai/skill.md`
- **查證發現**：
  - 官網 `/free` 列出 4 個啟用免費模型：`qwen/qwen3.7-flash`、`nvidia/nemotron-3.5-lightning-free`、`stealth/glyph-cluster`、`deepseek/deepseek-v4-flash-0731free`；實際呼叫 `https://api.bazaarlink.ai/v1/models` 查得標價為 `0`（`prompt: "0", completion: "0"`）的路由共有 `auto:free`、`qwen/qwen3.7-flash:free`、`deepseek/deepseek-v4-flash-0731free:free`、`nvidia/nemotron-3.5-lightning-free:free`、`stealth/glyph-cluster:free`（不帶 `:free` 後綴之 `qwen3.7-flash`、`deepseek-v4-flash-0731free` 皆為付費計價；官網 `/en/docs/api` 亦確認 `:free` 為獨立免費變體）。
  - 官網 `/free` 明訂「Site-wide free RPM cap: 20 RPM」（全站免費總上限每分鐘 20 次），併同每帳號沒儲值 10 RPM / 60 加權單位、有儲值 20 RPM / 120 加權單位、每日 UTC 00:00 重置、每帳號同時最多 2 個免費請求。
  - `bazaarlink.ai/skill.md` 確認主推端點為 `https://api.bazaarlink.ai/v1`（與現有卡片相同；舊址 `https://bazaarlink.ai/api/v1` 仍相容，不須修改 `base_url`）。
- **修改內容**：
  - `models` 補入 `"stealth/glyph-cluster:free"`。
  - `limits` 補註「全站免費總上限每分鐘 20 次」。
  - `notes` 提醒不帶 `:free` 後綴的直接模型 ID 多為付費，請用列出的 `:free` 路由或 `auto:free`，並註明「還沒實測」。
  - `verified` 維持 `"2026-11-23"`。

### 2. `groq`（Groq）
- **檔案位置**：[app/provider_catalog.py:68-79](file:///C:/Users/user/Desktop/OmniKeep/app/provider_catalog.py#L68-L79)
- **官方查證來源**：
  - `https://console.groq.com/docs/rate-limits.md`、`https://console.groq.com/docs/models.md`、`https://console.groq.com/docs/deprecations.md`、`https://console.groq.com/docs/structured-outputs.md`
- **查證發現**：
  - Free Plan 通用文字對話模型仍為 `openai/gpt-oss-120b`、`openai/gpt-oss-20b`、`qwen/qwen3.8-27b`，皆為每模型獨立計算 `30 RPM / 1K RPD / 8K TPM / 200K TPD`，且皆列於 `strict: true` JSON schema 支援清單。
  - `qwen/qwen3.8-27b` 屬於 Preview 模型（2026-09-14 取代 `qwen/qwen3.6-27b`），官方文件註明 Preview 模型可能短時間內通知下架；Llama 3.1/3.3 維持 Enterprise（已移出免費方案）。
- **修改內容**：
  - `notes` 補充「`qwen/qwen3.8-27b` 目前為 Preview 模型，可能提前下架」。
  - `verified` 更新為 `"2026-11-23"`。

### 3. `nvidia`（NVIDIA NIM（Free Endpoint））
- **檔案位置**：[app/provider_catalog.py:191-201](file:///C:/Users/user/Desktop/OmniKeep/app/provider_catalog.py#L191-L201)
- **官方查證來源**：
  - `https://integrate.api.nvidia.com/v1/models`、`https://build.nvidia.com/minimaxai/minimax-m3.1-flash`、`https://build.nvidia.com/mistralai/mistral-large-4-1t-a52b`、`https://build.nvidia.com/deepseek-ai/deepseek-v4.1-flash`、`https://forums.developer.nvidia.com/t/388912.json`
- **查證發現**：
  - `/v1/models`（33 個模型）與官網模型專頁證實 `minimaxai/minimax-m3.1-flash` 與 `mistralai/mistral-large-4-1t-a52b` 均標示 `Free Endpoint: Available` 且 `Structured Output: Supported`。
  - `https://build.nvidia.com/deepseek-ai/deepseek-v4.1-flash` 官方模型頁已明確標示 `Free Endpoint: Deprecated`，且已從 `/v1/models` 移除。
  - 官方公開文件未記載固定 RPM 數值（`40 RPM` 來自開發者論壇貼文 `t/388912`，官方統一速率上限數值**待驗證**）。
- **修改內容**：
  - `notes` 更新為「官方模型頁已將 deepseek-ai/deepseek-v4.1-flash 標示為 Deprecated 並移出 /v1/models」。
  - `verified` 更新為 `"2026-11-23"`。

### 4. `requesty`（Requesty（免費模型））
- **檔案位置**：[app/provider_catalog.py:151-162](file:///C:/Users/user/Desktop/OmniKeep/app/provider_catalog.py#L151-L162)
- **官方查證來源**：
  - `https://docs.requesty.ai/features/free-models`、`https://www.requesty.ai/pricing`、`https://docs.requesty.ai/features/in-flight-rate-limits`、`https://router.requesty.ai/v1/models`
- **查證發現**：
  - 官方 `Free Models` 文件明文寫出免費模型設有每分鐘與每日次數上限：新組織每天 `200` 次、每分鐘 `20` 次；付費組織每天 `1,000` 次、每分鐘 `60` 次，所有免費模型共用（先前卡片寫「不限每分鐘次數」為誤，不限 RPM 的規則僅指一般/付費路由的 in-flight 限制）。
  - 即時 `/v1/models` 目前有 8 個 `input_price = 0, output_price = 0` 免費模型（現有預設 `google/gemma-4-31b-it` 與 `novita/ling-3.1-flash` 仍在內；`docs/free-models` 網頁舊表所列之 `nemotron-3-super-120b`、`laguna` 等已非 0 元）。
- **修改內容**：
  - 更正 `limits` 為「新組織每天 200 次、每分鐘 20 次（付費組織每天 1,000 次、每分鐘 60 次），所有免費模型共用；另有依餘額計算的同時請求數上限」。
  - `notes` 補充 `/v1/models` 目前有 8 個免費模型（只實測過這 2 個，其餘還沒實測）。
  - `verified` 更新為 `"2026-11-23"`。

### 5. `zai`（Z.AI（GLM Flash））
- **檔案位置**：[app/provider_catalog.py:110-121](file:///C:/Users/user/Desktop/OmniKeep/app/provider_catalog.py#L110-L121)
- **官方查證來源**：
  - `https://docs.z.ai/guides/overview/pricing.md`、`https://docs.z.ai/guides/llm/glm-4.7.md`、`https://docs.z.ai/guides/vlm/glm-4.6v.md`、`https://docs.z.ai/api-reference/rate-limit.md`、`https://docs.z.ai/devpack/notice/api-key-management.md`
- **查證發現**：
  - `pricing.md` 確認 `GLM-4.7-Flash`、`GLM-4.5-Flash` 與多模態 `GLM-4.6V-Flash` 皆標示 `Free`（`GLM-5.3-Flash` 為付費模型）。
  - `rate-limit.md` 仍直接重導向須登入頁面 `https://z.ai/manage-apikey/rate-limits`，未於公開頁面揭露具體並發或 RPM 數值（官方並發與每分鐘上限**待驗證**）。
  - `api-key-management.md`（2026-10-16 公告）明訂標準模型端點（`api.z.ai/api/paas/v4`）與 Coding Plan 金鑰分開管理，建立標準端點金鑰時須選 `Standard API Key`。
- **修改內容**：
  - `limits` 改為註明官方並發與每分鐘上限須登入控制台查詢（未公開，第三方說法為 1 個並發）。
  - `notes` 補充建金鑰時請選 `Standard API Key`，並提及免費視覺模型另有 `glm-4.6v-flash`（還沒實測）。
  - `verified` 更新為 `"2026-11-23"`。

### 6. `itera`（Itera Compute（Qwen3.8 27B））
- **檔案位置**：[app/provider_catalog.py:229-241](file:///C:/Users/user/Desktop/OmniKeep/app/provider_catalog.py#L229-L241)
- **官方查證來源**：
  - `https://iteracompute.com/free`、`https://iteracompute.com/free-tier-terms/`、`https://api.iteracompute.com/v1/models`
- **查證發現**：
  - 免費促銷將於 **2026-11-24 00:00 太平洋時間（台灣時間 2026-11-24 16:00）** 結束；截止後僅限此前有正數淨儲值或持有有效付費方案之帳號保留共享免費 `Auto` 額度。
  - 免儲值/免費層每月 `30M` token（每月 1 日 `00:00 UTC`／台灣早上 8 點重置），單次 context `128K`、輸出上限 `8,192` token，每帳號同時限 1 個排隊或執行中請求，超額回 429。`/v1/models` 中 `qwen/qwen3.8-27b` 與 `Auto` 目前皆為 `is_free: true`。
- **修改內容**：
  - `limits` 補全每月重置時間、128K context、8,192 輸出上限及同時限 1 個請求。
  - `notes` 補註台灣時間 16:00 截止點與淨儲值帳號保留共享免費 `Auto` 規則。
  - `verified` 更新為 `"2026-11-23"`。

---

## 三、待使用者決定事項（步驟 3）

1. **Itera Compute 明日到期（2026-11-24 16:00 台灣時間）處置**：依 [app/provider_catalog.py:442-445](file:///C:/Users/user/Desktop/OmniKeep/app/provider_catalog.py#L442-L445) 之 `ended()` 機制，過了 `2026-11-24` 後系統會自動標示為 `ended: true`。請決定下週是否保留該卡片（供 cutoff 前曾儲值帳號繼續用共享免費 `Auto`）或整個移除。
2. **BazaarLink 端點確認**：現有卡片 `base_url` 為 `https://api.bazaarlink.ai/v1`，與官網最新文件一致；FreeLLMAPI 舊索引列 `https://bazaarlink.ai/api/v1`（官網註明亦相容），本次維持不變。
3. **下列新增管道是否納入正式卡片**：本次依規則未新增卡片，請自第 5 節清單挑選要測試與收錄的管道。

---

## 四、新增的合格管道清單（步驟 5，不加卡片）

篩選條件：官方 API key 或不用金鑰；Google 或 email 簡單註冊；免費或長期免費；不是閉源旗艦模型的中轉站；OpenAI 相容 chat API。

1. **Inferbase** — 官方連結：`https://inferbase.ai/pricing`（端點 `https://api.inferbase.ai/v1`）｜免費型態：註冊後額度定期自動補回（永久 USD 0 Free 方案：每月 5,000 次、每日 100 次／USD 0.50、10 RPM）｜理由：免卡且永久免費，惟單次託管上限為 8,192 輸入／1,024 輸出 tokens，需實測 OmniKeep 摘要是否會被截斷。
2. **Routeway** — 官方連結：`https://routeway.ai/`（端點 `https://api.routeway.ai/v1`）｜免費型態：註冊後額度定期自動補回（Starter USD 0：每日 200 次 `:free` 路由、單並發）｜理由：免卡提供 `minimax-m3.1-flash:free` 等 7 款開源免費模型，但非瀏覽器 User-Agent 可能遭 Cloudflare 1010 阻擋。
3. **Nous Portal** — 官方連結：`https://portal.nousresearch.com/`（端點 `https://inference-api.nousresearch.com/v1`）｜免費型態：註冊後額度定期自動補回（USD 0 方案開放 `:free` 模型；具體 RPM/RPD 須登入查看，待驗證）｜理由：免卡可使用 `qwen/qwen4-max:free`、`stepfun/step-3.7-flash:free` 等 5 款高階開源免費路由。
4. **MegaNova** — 官方連結：`https://docs.meganova.ai/free-model-quota`｜免費型態：註冊後額度定期自動補回（免卡 Tier 1 每日 00:00 UTC 重置，共 550 次/日）｜理由：免卡提供 `Mistral-Small-3.2` 等開源模型每日各 50 次（`GLM-4.7-Flash` 須 Tier 2；API Base URL 須登入確認，待驗證）。
5. **Merkium** — 官方連結：`https://www.merkium.nl/docs/pricing`（端點 `https://chat.merkium.nl/api/v1`）｜免費型態：註冊後額度定期自動補回（官網明標永久免費、非試用，每把 key 30 RPM）｜理由：荷蘭獨立團隊營運且不限期免費（`ganymede-1.1`、`pluto-1.2-flash` 等自有模型），僅須實測繁體中文 JSON 表現。
6. **AnyAPI** — 官方連結：`https://anyapi.ai/pricing`（端點 `https://api.anyapi.ai/v1`）｜免費型態：註冊後額度定期自動補回（USD 0 Free 方案每日 100K ANY Tokens）｜理由：免卡每日定期補回額度，但 ANY Tokens 換算比與可用免費模型清單須登入確認（待驗證）。
7. **Zro (MoonMath)** — 官方連結：`https://zro.moonmath.ai/pricing`｜免費型態：註冊後額度定期自動補回（每日重置免費 DeepSeek V4.1 Flash 用量）｜理由：免卡提供強開源 Flash 模型並承諾零保留，惟未公開具體每日次數或 token 上限數字（待驗證）。
8. **Aion Labs** — 官方連結：`https://www.aionlabs.ai/docs/rate-limits/`（端點 `https://api.aionlabs.ai/v1`）｜免費型態：註冊後額度定期自動補回（USD 0 Free 方案每日 20,000 tokens、15 RPM）｜理由：免卡且限額透明，但日額度僅 20K tokens 僅適合輕量備援。
9. **Cohere (Trial keys)** — 官方連結：`https://docs.cohere.com/docs/rate-limits`（端點 `https://api.cohere.ai/compatibility/v1`）｜免費型態：註冊後額度定期自動補回（永久免卡 Trial Key，每月 1,000 次、20 RPM）｜理由：官方大廠永不到期之 Trial Key 且支援 OpenAI 相容端點，惟每月 1,000 次且禁止商用。
10. **FreeInference (Harvard SEAS)** — 官方連結：`https://doc.freeinference.org/`（端點 `https://freeinference.org/v1`）｜免費型態：註冊後額度定期自動補回（依實驗室空閒 GPU 浮動限額，無固定公開數字，待驗證）｜理由：哈佛大學研究實驗室免費提供 `glm-5.3-flash` 與 `deepseek-v4-flash` 等強模型，但屬實驗環境且提示將供研究公開使用。
11. **Kiosapi.id** — 官方連結：`https://kiosapi.id/pricing`｜免費型態：註冊後額度定期自動補回（每日免費額度，含 `google/gemma-4-26b`、`aisingapore/sea-lion-27b` 等 4 款；日上限數字待驗證）｜理由：支援 Google/email 註冊且免儲值即可使用開源免費模型，惟日配額數值未公開。
12. **LongCat (Meituan)** — 官方連結：`https://longcat.chat/platform/docs`（端點 `https://api.longcat.chat/openai`）｜免費型態：註冊後額度定期自動補回（FreeLLMAPI 記載提供每日免費額度；官網公開文件未寫出額度數字與註冊是否免手機驗證，待驗證）｜理由：國際站支援 OpenAI 相容格式與 1M context 之 `LongCat-2.5`，實際國際註冊門檻待實測。
13. **Hetzner Inference API** — 官方連結：`https://docs.hetzner.com/general/company-and-policy/experiments/inference/`（端點 `https://inference.hetzner.com/api/v1`）｜免費型態：限時活動（實驗期間免費，每分鐘 10 次、4M 輸入／100K 輸出 tokens）｜理由：德國官方實驗端點提供 `Qwen3.8-27B` 與 `Qwen3.6-35B-A3B`，惟新帳號註冊常觸發 Hetzner 證件或信用卡風控驗證（簡單註冊門檻待驗證）。

> 附註（不符合步驟 5 條件而排除）：**BeatAPI**（兼售折扣閉源旗艦且未儲值僅 1 RPM 限時優惠）、**NovAI**（僅 USD 2 一次性開戶金）、**VLM Run Gateway**（僅 USD 10 一次性開戶金且以視覺文件解析為主）、**Regolo AI**（僅 30 天一次性試用）、**PowerTokens**（官網定價頁未列免費層且 `/v1/models` 須金鑰回 401，免費層實況待驗證）、**OrcaRouter**（須綁定老牌 GitHub 帳號）、**Logfare**（強制綁定 Discord 並留存伺服器）、**Sail Research / Vercel AI Gateway / IBM watsonx.ai Lite / Together AI / Experiential Labs**（均須綁定付款方式或先儲值）。
