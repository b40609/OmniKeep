# OmniKeep 免費 AI 管道查證與更新報告（2026-11-22）

- 查證日期：`2026-11-22`
- 對照基準：
  - 現有卡片定義：`app/provider_catalog.py`（`VERIFIED = "2026-11-05"`，部分卡片為 `2026-11-06` 或 `2026-11-17`）
  - 篩選原則與實測方法：`docs/free_llm_channels_2026-11.md`
  - 週報與完整快照：`C:\Users\user\AppData\Local\OmniKeep\free_channel_watch\report-2026-11-22.md` 與同目錄 `snapshot.json`（因 `scripts/free_channel_watch.py` 僅輸出前 40 筆變動名稱，本報告新候選部分已直接檢視 `snapshot.json` 內全部 117 筆 mvalentsev 與 48 筆 FreeLLMAPI 項目，無漏檢）

---

## 一、現有卡片總表（18 張）

> 註：`vertex` 依本次指派僅查證 Express mode 變化；OmniKeep 的 `vertex` 卡片本身是配合 Google AI Pro 每月 USD 10 抵免額使用（見 `docs/gemini_pro_credit_setup.md`），Express mode 僅作附註參考。

| 卡片 id | 免費型態 | 週期或到期日 | 卡片要不要改 | 一句理由 |
|---|---|---|---|---|
| `agnes` | 限時活動 | 無公告截止日（促銷體驗價 0 美元） | 要改 | `limits` 稱兩把 key 可輪流疊加與官方 FAQ 衝突，且可補 `agnes-2.5-flash`。 |
| `gemini` | 註冊後額度定期自動補回 | 每日（太平洋時間午夜重置） | 要改 | 預設 `gemini-3.5-flash` 已下架選單並自動導向 `gemini-3.6-flash`，且可補 `gemini-3.8-flash`、`gemini-4-hydrogen`。 |
| `vertex` | 限時活動（Express mode）／帳單抵免（本卡） | Express mode 為 90 天試用（新 GCP `@gmail.com` 用戶） | 建議小改 | Express mode 已更名為 Gemini Enterprise Agent Platform；建議檢查 `gemini-3.5-flash` 是否同步導向。 |
| `groq` | 註冊後額度定期自動補回 | 每分鐘＋每日 | **必須改** | 卡片裡的兩款 Llama 已移至 Enterprise，`Free` 僅剩 `gpt-oss-120b/20b` 與 `qwen3.8-27b`，且多了每分鐘 8,000 token 上限。 |
| `cloudflare` | 註冊後額度定期自動補回 | 每日（00:00 UTC 重置） | 可不改（建議更新日期） | 每日 10,000 Neurons 沒變；官網已有更省額度的 `glm-4.7-flash` 與 `qwen3.8-27b` 可考慮增補。 |
| `openrouter` | 註冊後額度定期自動補回 | 每分鐘＋每日 | **必須改** | 預設 `meta-llama/llama-3.3-70b-instruct:free` 已下架不在即時模型清單內，須改用 `google/gemma-4-31b-it:free` 等現存模型。 |
| `zai` | 註冊後額度定期自動補回 | 無公開固定重置週期（官網長期標 Free，待驗證並發限制） | 不急改（更新日期） | `GLM-4.7-Flash`、`GLM-4.5-Flash` 仍標示免費；速率上限頁須登入才能看。 |
| `inception` | 一次性贈送用完就沒（兼具停服期限） | 服務將於 2026-12-28 終止 | **必須改** | 官方已公告 Mercury API 將於 2026-12-28 關停，卡片缺 `ends` 與退場警示。 |
| `tokenharbor` | 註冊後額度定期自動補回 | 每 7 天滾動 | 建議小改 | 7 天滾動額度與實際 429 吻合；官方已明文公布 `60 RPM / 1,800 RPH`，可將「第三方數據」改為官方原句。 |
| `requesty` | 註冊後額度定期自動補回 | 每日 | 可不改（建議小改） | 每日 200 次共用免費限額未變（符合實際 429）；建議更新 `verified` 與即時免費模型列表。 |
| `nvidia` | 註冊後額度定期自動補回 | 每分鐘（社群資料另記每日約 10,000 次） | **必須改** | 卡片所列 `deepseek-ai/deepseek-v4.1-flash` 已不在即時 `/v1/models` 名單內，須移除或替換。 |
| `aihubmix` | 註冊後額度定期自動補回 | 每分鐘＋每日 | 建議小改 | `glm-4.7-flash-free` 仍可用且為 `5 RPM / 500 RPD / 1M TPD`，建議補註每日 100 萬 token 上限。 |
| `sealion` | 註冊後額度定期自動補回 | 每分鐘 | 不急改（更新日期） | 官方仍為每位用戶每分鐘 10 次、Google 登入 1 把 Trial key，與卡片一致。 |
| `itera` | 限時活動 | 2026-11-24 00:00 PT（台灣時間 16:00）結束 | **必須追蹤／準備下架** | 兩天後對無儲值帳號停止免費額度；官網另推 `"model": "Auto"`。 |
| `flm` | 不用註冊 | 每分鐘＋每日（per IP） | 不用改（更新日期） | 官網 `/limits` 與卡片完全一致（60 RPM、20,000 RPD、1,000 萬 TPD）。 |
| `jarvisclaw` | 不用註冊 | 每分鐘（數值未公開，待驗證） | 不用改（更新日期） | 官網仍維持免 key `auto/free`，不可送 `Authorization` 標頭，與卡片一致。 |
| `kilo` | 不用註冊 | 每小時（per IP） | 建議小改 | 官方文件改推新端點 `https://ai-gateway.kilo.ai/api/v1`（舊址仍通），另 `reflection/beam-free` 仍出現在即時 `/models`（可用性待驗證）。 |
| `ovh` | 不用註冊 | 每分鐘（per IP 每模型） | 建議小改 | 匿名每 IP 每模型 2 RPM 未變；即時模型清單已新增 `Qwen3.8-27B` 與 `DeepSeek-V4.1-Flash-1017`。 |

---

## 二、現有卡片逐張查證明細

### 1. `agnes`（Agnes AI）
- **免費型態**：`限時活動`（無公告截止日；核心模型標示長期免費但同時掛體驗促銷價 0 美元）
- **官方頁面與原文**：
  - `https://agnes-ai.com/zh-Hans/docs/agnes-30-flash`：「刊例价：输入 `$0.05` / 1M tokens；输出 `$0.15` / 1M tokens；体验价：`$0`」、「三项天使用户体验价均为 `$0`」
  - `https://wiki.agnes-ai.com/en/docs/faqs`：「Our core AI models are free to use indefinitely.」、「Free users receive a dynamic RPM limit, which can be viewed inside the API Console after signing in.」、「Creating multiple keys of the same type does not stack RPM or subscription quota.」
  - `https://wiki.agnes-ai.com/en/docs/pricing`（經 mvalentsev 快照轉引原句）：`"Promotional end dates are subject to Agnes AI platform announcements and your account bill"`
- **與現有卡片不一致處**：
  - `app/provider_catalog.py:34` 寫「兩把金鑰可以各建一條連線輪流用，但單條仍會撞」，與官方 FAQ 明文 `Creating multiple keys of the same type does not stack RPM or subscription quota` 矛盾（同類型 key 共用 RPM 配額池）。
  - `models` 僅列 `["agnes-3.0-flash"]`，官網同步有免費的 `agnes-2.5-flash`。
- **建議修改**：
  - 移除 `limits` 中「兩把金鑰可以各建一條連線輪流用」的誤導說法，改註為「免費帳號為動態 RPM，同類型多把金鑰共用配額不疊加；體驗價 0 美元截止日依官方公告」。
  - `models` 可補入 `"agnes-2.5-flash"`；`verified` 更新為 `"2026-11-22"`。

---

### 2. `gemini`（Google Gemini）
- **免費型態**：`註冊後額度定期自動補回`（每日，太平洋時間午夜重置）
- **官方頁面與原文**：
  - `https://aistudio.google.com/docs/pricing`：`gemini-3.8-flash`、`gemini-3.6-flash`、`gemini-4-hydrogen`、`gemini-3.5-flash-lite` 均在 Free Tier 欄標示 `Free of charge`（且 `Used to improve our products: Yes`）。
  - `https://aistudio.google.com/docs/rate-limits`：「Quotas reset at midnight Pacific time.」；頁面上已移除固定靜態 RPM/TPM/RPD 數字對照表，改為導向 AI Studio Rate Limit console 依帳號專案檢視（個別固定 RPD/RPM 數字標為「待驗證」）。
  - `https://aistudio.google.com/docs/deprecations` 與 `https://aistudio.google.com/docs/models`：明載 `gemini-3.5-flash` 已不可在 AI Studio 選用且「automatically routes API requests to `gemini-3.6-flash`」；`gemini-3.1-flash-lite` 公告將於 `May 7, 2027` 停用。
- **與現有卡片不一致處**：
  - `app/provider_catalog.py:45-46` 仍以 `gemini-3.5-flash` 為預設模型（實際已自動轉導至 `gemini-3.6-flash`），且未列入目前可免費呼叫的 `gemini-3.8-flash`、`gemini-3.6-flash`、`gemini-4-hydrogen`。
  - `limits` 引用的特定靜態 RPM/RPD 數字目前無法從公開 `docs/rate-limits` 查得，須於 AI Studio 控制台檢視。
- **建議修改**：
  - `model` 改為 `"gemini-3.8-flash"`（或 `"gemini-3.6-flash"`），`models` 更新為 `["gemini-3.8-flash", "gemini-3.6-flash", "gemini-4-hydrogen", "gemini-3.5-flash-lite", "gemini-3.1-flash-lite"]`（並加註 `gemini-3.1-flash-lite` 預計 2027-05-07 停用）。
  - `limits` 補註免費層依 AI Studio 控制台為準（太平洋時間午夜重置），避免寫死可能浮動的舊 RPM/RPD 數字；`verified` 更新為 `"2026-11-22"`。

---

### 3. `vertex`（Google Vertex AI / Agent Platform）
- **免費型態**：`限時活動`（Express mode 為新 GCP `@gmail.com` 用戶 90 天試用；註：OmniKeep 現有卡片實為 Google AI Pro 每月 USD 10 抵免額之帳單專案用法，非無帳單 Express mode）
- **Express mode 查證原文**（`https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/start/express-mode/overview`）：
  - 產品名稱已正式改為 **Gemini Enterprise Agent Platform (express mode)**（原 Vertex AI express mode 路徑已更名）。
  - 針對首次使用 Google Cloud 的 `@gmail.com` 帳號，仍提供免綁信用卡 90 天免費試用；清單列出 `gemini-3-pro-image`、`gemini-3.1-flash-image`、`gemini-3.1-pro-preview`、`gemini-3-flash-preview`（Dynamic throughput）以及 `gemini-2.5-pro` / `gemini-2.5-flash` / `gemini-2.5-flash-lite`（10 RPM）。
- **與現有卡片不一致處**：
  - `label` 與說明可順手補註 Express mode 已更名；至於卡片內 `gemini-3.5-flash` 在 Vertex Agent Platform 端點是否也同步自動導向 `gemini-3.6-flash`，無公開 Express mode 文件載明（**待驗證**）。
- **建議修改**：
  - `notes` 補記 Google Cloud Express mode 已更名為 Gemini Enterprise Agent Platform；`verified` 更新為 `"2026-11-22"`。

---

### 4. `groq`（Groq）
- **免費型態**：`註冊後額度定期自動補回`（每分鐘＋每日）
- **官方頁面與原文**（`https://console.groq.com/docs/rate-limits.md`、`https://console.groq.com/docs/models.md`）：
  - 原文：「Rate limits are enforced at the organization level for each model independently.」
  - Free Plan 限流表內目前已無 `llama-3.3-70b-versatile` 與 `llama-3.1-8b-instant`（兩者在現表改標為 `Enterprise` / `ContactSales`）。
  - Free Plan 目前僅存 3 個通用文字模型：`openai/gpt-oss-120b`、`openai/gpt-oss-20b`、`qwen/qwen3.8-27b`，三者限額皆為：`30 RPM` / `1,000 RPD` / `8,000 TPM` / `200,000 TPD`。
- **與現有卡片不一致處**：
  - `model: "llama-3.3-70b-versatile"` 與 `models: ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"]` 皆已移出免費層表單！
  - `limits` 未寫出極易觸發的 **`8,000 TPM`（每分鐘 8,000 token）** 限制——對長文分析容易單次或連續兩次請求就超限，且卡片沒寫清 200,000 TPD 是「每模型獨立計算」。
- **建議修改**：
  - `model` 改為 `"openai/gpt-oss-120b"`，`models` 改為 `["openai/gpt-oss-120b", "qwen/qwen3.8-27b", "openai/gpt-oss-20b"]`。
  - `limits` 改為：「每個模型獨立計算：每分鐘 30 次、8,000 token（長文易撞 8K TPM），每日 1,000 次、20 萬 token；沒有向量。」；`verified` 更新為 `"2026-11-22"`。

---

### 5. `cloudflare`（Cloudflare Workers AI）
- **免費型態**：`註冊後額度定期自動補回`（每日 `00:00 UTC` 重置）
- **官方頁面與原文**：
  - `https://developers.cloudflare.com/workers-ai/platform/pricing/`：「10,000 Neurons per day at no charge」（每日 `00:00 UTC` 重置）；另定價表列有較省 Neurons 的 `@cf/zai-org/glm-4.7-flash`（5,500 input / 36,400 output Neurons/M），遠低於 `@cf/openai/gpt-oss-120b`（31,818 input / 68,182 output Neurons/M），以及 `@cf/qwen/qwen3.8-27b`、`@cf/google/gemma-4-26b-a4b-it`。
  - `https://developers.cloudflare.com/workers-ai/platform/limits/`：一般文字生成預設為 `300 requests per minute`（僅標為 Paid plan 前沿模型的特定路線降為 20 或 50 RPM）。
- **與現有卡片不一致處**：
  - `cost`、`limits`、`quota`、`base_url` 無誤；僅 `models` 未列入更省 Neurons 的新款免費可選模型。
- **建議修改**：
  - `models` 可考慮補入 `"@cf/zai-org/glm-4.7-flash"`、"`@cf/qwen/qwen3.8-27b"` 與 `"@cf/google/gemma-4-26b-a4b-it"`；`verified` 更新為 `"2026-11-22"`。

---

### 6. `openrouter`（OpenRouter）
- **免費型態**：`註冊後額度定期自動補回`（每分鐘＋每日）
- **官方頁面與原文**：
  - `https://openrouter.ai/docs/api/reference/limits`：免費模型維持 `20 requests per minute`；帳戶餘額低於 USD 10（或未購買 credits）為 `50 free model requests per day`，購買至少 USD 10 credits 後提升至 `1,000 free model requests per day`。
  - `https://openrouter.ai/api/v1/models`（2026-11-22 即時查詢）：目前共有 11 個 `:free` 模型（包含 `google/gemma-4-31b-it:free`、`google/gemma-4-26b-a4b-it:free`、`inclusionai/ling-3.2-flash:free`、`baidu/ernie-5.5-flash-preview:free`、`nvidia/nemotron-3.5-super-vl:free`、`nvidia/nemotron-3.5-lightning:free`、`nvidia/nemotron-3-ultra-550b-a55b:free` 等）。
- **與現有卡片不一致處**：
  - 卡片預設的 `"meta-llama/llama-3.3-70b-instruct:free"` 已從即時 `:free` 模型列表移除！
- **建議修改**：
  - `model` 建議改為 `"google/gemma-4-31b-it:free"`，`models` 更新為 `["google/gemma-4-31b-it:free", "google/gemma-4-26b-a4b-it:free", "inclusionai/ling-3.2-flash:free", "nvidia/nemotron-3.5-lightning:free"]`；`verified` 更新為 `"2026-11-22"`。

---

### 7. `zai`（Z.ai 智譜國際站）
- **免費型態**：`註冊後額度定期自動補回`（官網長期將 Flash 系列標為 `Free`，無固定月/日數額公布，並發配額登入後查看）
- **官方頁面與原文**：
  - `https://docs.z.ai/guides/overview/pricing.md`：`GLM-4.7-Flash`、`GLM-4.5-Flash`、`GLM-4.6V-Flash` 在計價表中均明確標註 `Free`。
  - `https://docs.z.ai/api-reference/rate-limit.md`：轉導向登入頁面 `https://z.ai/manage-apikey/rate-limits`，未於未登入公開文件列出並發/RPM 數字（**具體並發數字待驗證**）。
  - `https://docs.z.ai/legal-agreement/privacy-policy.md`：API 商業／開發者 DPA 第 4(b) 條載明不存儲客戶透過 API 傳輸或生成的內容（`The Company do not store any of the content the Customer or its End Users provide or generate while using our Services`）。
- **與現有卡片不一致處**：
  - 模型與免費狀態一致；卡片「同時最多約 1 條連線」屬先前實測值，官網靜態頁面無記載（「待驗證」）。
- **建議修改**：
  - 維持現行模型與配額描述，更新 `verified` 為 `"2026-11-22"`，並在 `limits` 註明官網並發上限須登入控制台查詢。

---

### 8. `inception`（Inception Labs Mercury）
- **免費型態**：`一次性贈送用完就沒`（兼具明確終止期限：`2026-12-28`）
- **官方頁面與原文**：
  - `https://docs.inceptionlabs.ai/get-started.md` & `https://docs.inceptionlabs.ai/support/wind-down.md`：「The Mercury API is winding down. It remains fully available through December 28, 2026」（新帳號一次贈送 `100M` token 的條件仍有效，但服務將於 `2026-12-28` 全面關閉，之後停止存取）。
- **與現有卡片不一致處**：
  - `app/provider_catalog.py:120-131` 完全沒有 `"ends"` 欄位，也沒有標明 2026-12-28 即將停服。
- **建議修改**：
  - 新增 `"ends": "2026-12-28"`，`cost` 與 `notes` 明確標示將於 `2026-12-28` 結束營運；建議從主力推薦排序中下移，並於 `verified` 更新 `"2026-11-22"`。

---

### 9. `tokenharbor`（Token Harbor）
- **免費型態**：`註冊後額度定期自動補回`（**每 7 天滾動**）
- **官方頁面與原文**：
  - `https://tokenharbor.ai/pricing` & `https://tokenharbor.ai/faq`：「Your first free request starts a personal rolling 7-day period. The allowance is value-based rather than a fixed request count」（與本次實測收到的 429 原句 `"You've used this period's free allowance. Your next rolling 7-day period starts on 27 Nov 2026"` 完全相符）。
  - `https://tokenharbor.ai/docs/api/rate-limits`：明確公布帳號上限為 `60 requests/minute and 1,800 requests/hour per account`（每 IP 為 `100/min, 3,000/hr`），不限制同時並發請求數。
  - `https://tokenharbor.ai/models?category=free`：目前免費類僅列 `mimo-v2.6-flash:free` 與 `deepseek-v4.1-flash:free`。
  - `https://tokenharbor.ai/terms`：免費路線採 opt-in，條款載明工作人員及合作第三方 AI 工具可存取與分析免費路由對話，上游供應商亦可能用於模型訓練。
- **與現有卡片不一致處**：
  - `limits` 原寫「約每分鐘 60 次（第三方數據）」，現在官方文件已有正式明文數字（`60 req/min`、`1,800 req/hr`，無並發上限），且滾動週期額度以「美元價值」計而非次數。
- **建議修改**：
  - 更新 `limits` 為官方標準敘述（每帳號 60 RPM / 1,800 RPH、無並發限制，7 天滾動以美金價值計算且具體金額不公開）；`verified` 更新為 `"2026-11-22"`。

---

### 10. `requesty`（Requesty）
- **免費型態**：`註冊後額度定期自動補回`（每日）
- **官方頁面與原文**：
  - `https://www.requesty.ai/pricing` & `https://docs.requesty.ai/features/free-models`：`200 requests per day`（所有免費模型共用）；超額即回應 rate limit 錯誤（吻合本次實測 `"You've hit the rate limit for free models"`）。
  - `https://docs.requesty.ai/features/api-limits`：免費層不採傳統 RPM 限制，而是以系統層的進行中（in-flight）並發數進行控管。
  - `https://router.requesty.ai/v1/models`（即時檢查）：目前價格為 0 的模型有 8 款（包含 `google/gemma-4-31b-it`、`novita/ling-3.1-flash`、`nvidia/nemotron-3-ultra-550b-a55b`、`mistral/leanstral-1-5` 等）。
- **與現有卡片不一致處**：
  - 主要規則皆吻合（免費方案依 Requesty 隱私條款內容可用於模型訓練），僅模型選項可補註更多 0 元選項。
- **建議修改**：
  - 可保持預設 `google/gemma-4-31b-it` 與 `novita/ling-3.1-flash`，選擇性補入 `nvidia/nemotron-3-ultra-550b-a55b`；`limits` 註明採並發控管；`verified` 更新為 `"2026-11-22"`。

---

### 11. `nvidia`（NVIDIA NIM）
- **免費型態**：`註冊後額度定期自動補回`（每分鐘，社群資料另有每日約 10,000 次紀錄；官方歸類試用條款）
- **官方頁面與原文**：
  - `https://docs.api.nvidia.com/nim/docs/api-quickstart` 與 `https://assets.ngc.nvidia.com/products/api-catalog/legal/NVIDIA%20API%20Trial%20Terms%20of%20Service.pdf`（Section 1.2, 1.4, 3.3）：明定免費端點僅供測試評估、禁止上線營運（production），且輸入輸出會記錄供改進 NVIDIA AI 模型。
  - `https://forums.developer.nvidia.com/t/388912`：官方討論區確認預設限流為 `40 requests per minute`（每分鐘 40 次）。
  - `https://integrate.api.nvidia.com/v1/models`（2026-11-22 即時查詢）：`minimaxai/minimax-m3.1-flash`、`mistralai/mistral-large-4-1t-a52b`、`z-ai/glm-5.3-flash` 仍在列表中；但 **`deepseek-ai/deepseek-v4.1-flash` 已不存在於即時名單**。
- **與現有卡片不一致處**：
  - `models` 與 `model_extra_body` 內的 `"deepseek-ai/deepseek-v4.1-flash"` 已下架不可用！
- **建議修改**：
  - 從 `models` 與 `model_extra_body` 移除 `"deepseek-ai/deepseek-v4.1-flash"`，可考慮替換為目前線上的 `"z-ai/glm-5.3-flash"`（需確認 `extra_body` 關閉 thinking 參數）；`verified` 更新為 `"2026-11-22"`。

---

### 12. `aihubmix`（AIHubMix）
- **免費型態**：`註冊後額度定期自動補回`（每分鐘＋每日）
- **官方頁面與原文**：
  - `https://aihubmix.com/model/glm-4.7-flash-free`：定價標為 `0 美元 / 1M`。
  - `https://aihubmix.com/v1/models`（即時查詢）：共有 43 個 `-free` / `:free` 模型。
  - `https://docs.aihubmix.com/cn/api/Data-Pravicy`：載明平台不主動存儲提示與回應（依各上游供應商政策）。
  - 注：AIHubMix 未見統一的公開 RPM/RPD 限流總表（確切全站官方靜態限額原句**待驗證**，各模型限額散見模型卡及 mvalentsev 2026-11-19 實測紀錄：`glm-4.7-flash-free` 為 `5 RPM / 500 RPD / 1,000,000 tokens/day`；部分新版 `-free` 如 `coding-glm-5.3-flash-free` 為 `100 RPD`）。另有 `https://docs.aihubmix.com/cn/blogs/free-ai-models` 提到閉源模型僅贈送一次性 10 次體驗呼叫，不納入此開源免費卡範圍。
- **與現有卡片不一致處**：
  - 卡片描述與實際大致相符，缺少「每日 100 萬 token 上限」資訊與「官方無集中限額總表」說明。
- **建議修改**：
  - `limits` 補充 `glm-4.7-flash-free` 含每日 100 萬 token 上限（來自第三方追蹤），並更新 `verified` 為 `"2026-11-22"`。

---

### 13. `sealion`（SEA-LION / AI Singapore）
- **免費型態**：`註冊後額度定期自動補回`（每分鐘）
- **官方頁面與原文**：
  - `https://docs.sea-lion.ai/guides/inferencing/api`：「As of 04 Jun 2026, our rate limits is set to 10 requests per minute per user」；使用 Google 帳號登入並限定建立 1 把 Trial API Key，沒有設到期日或每日次數/token 配額限制。
  - 另查 `https://sea-lion.ai/terms-of-use/`：AI Singapore 保留使用所提交內容（Content）以提供、維護及改進服務之權利。
  - 註：`https://docs.sea-lion.ai/guides/inferencing/models` 目前 404，可用模型以帶 Key 查詢 `https://api.sea-lion.ai/v1/models` 為準（未帶 Key 回 401）。
- **與現有卡片不一致處**：
  - 無明顯錯誤；官方檔案路徑與限制皆和卡片一致。
- **建議修改**：
  - 維持原有卡片設定，僅將 `verified` 更新為 `"2026-11-22"`。

---

### 14. `itera`（Itera Compute）
- **免費型態**：`限時活動`（**2026-11-24 00:00 PT 結束**，台灣時間 2026-11-24 16:00）
- **官方頁面與原文**：
  - `https://iteracompute.com/free` & `https://iteracompute.com/free-tier-terms/`：免費層（每月 3,000 萬 token）於 `2026-11-24 00:00 PT` 停止對未儲值用戶提供；僅有在截止前達成淨儲值大於 0 的帳號才會保留原有層級（含 Free 30M/mo）。
  - `https://api.iteracompute.com/v1/models`（即時查詢）：`Auto` 與 `qwen/qwen3.8-27b` 皆標示 `is_free: true`，官網範例現已改推薦 `"model": "Auto"`。
- **與現有卡片不一致處**：
  - `ends: "2026-11-24"` 即將於 2 天後到期（屆時未儲值帳號將停用免費額度）；`models` 僅列 `qwen/qwen3.8-27b`，未附現推的 `Auto`。
- **建議修改**：
  - 2026-11-24 到期後依系統 `ended` 狀態處理或下架；這兩天內可於 `models` 補註 `"Auto"` 並更新 `verified` 至 `"2026-11-22"`。

---

### 15. `flm`（FreeLLMAPI / stonech.at）
- **免費型態**：`不用註冊`
- **官方頁面與原文**：
  - `https://flm.stonech.at/`、`https://flm.stonech.at/limits`、`https://flm.stonech.at/docs.txt`：公開註明每 IP `60 requests per minute`、`20,000 requests per day`、`10,000,000 tokens per day`；最大輸入 `64K`、最大輸出 `8K`（未帶 `max_tokens` 時預設 `2048`）。
- **與現有卡片不一致處**：
  - 無，所有數字與設定完全吻合。
- **建議修改**：
  - 卡片無須改動，更新 `verified` 至 `"2026-11-22"`。

---

### 16. `jarvisclaw`（JarvisClaw）
- **免費型態**：`不用註冊`
- **官方頁面與原文**：
  - `https://jarvisclaw.ai/en/free-llm-api`：免註冊、免 API key、使用 `"model": "auto/free"`；不可攜帶 `Authorization` 標頭（帶了會回 401）；套用動態每 IP 限流，但官網未公布確切每分鐘次數數字（具體 RPM 上限**待驗證**）。
- **與現有卡片不一致處**：
  - 無，與現有卡片完全相符。
- **建議修改**：
  - 卡片無須改動，更新 `verified` 至 `"2026-11-22"`。

---

### 17. `kilo`（Kilo Gateway）
- **免費型態**：`不用註冊`
- **官方頁面與原文**：
  - `https://kilo.ai/docs/gateway`：匿名呼叫維持每個 IP 每小時 200 次；官方文件現已主推新 Base URL `https://ai-gateway.kilo.ai/api/v1`（實測舊址 `https://api.kilo.ai/api/gateway/v1/models` 仍可回應）。
  - 即時 `/models` 查得 9 個 `:free` 結尾模型（包含 `kilo-auto/free`、`inclusionai/ling-3.2-flash:free` 等），且 **`reflection/beam-free` 目前仍在即時 `/models` 列表並標價 0**（與 2026-11-17 實測回 404 不一致，實際 chat 請求是否已恢復或仍會 404 須實測，標**待驗證**）。
- **與現有卡片不一致處**：
  - 文件主推的新 Base URL 已更新；`reflection/beam-free` 狀態需再實測確認。
- **建議修改**：
  - 可測試後決定是否改將 `base_url` 更新為 `https://ai-gateway.kilo.ai/api/v1`，並覆測 `reflection/beam-free` 或替換成 `inclusionai/ling-3.2-flash:free`；`verified` 更新為 `"2026-11-22"`。

---

### 18. `ovh`（OVHcloud AI Endpoints）
- **免費型態**：`不用註冊`
- **官方頁面與原文**：
  - `https://docs.ovhcloud.com/en/guides/public-cloud/ai-machine-learning/ai-endpoints-capabilities/`：「Anonymous: 2 requests per minute, per IP and per model」
  - `https://oai.endpoints.kepler.ai.cloud.ovh.net/v1/models`（即時查詢）：現已提供 `Qwen3.8-27B`、`DeepSeek-V4.1-Flash-1017`、`gemma-4-26b-a4b`、`Qwen3.6-27B`、`gpt-oss-120b`、`Meta-Llama-3_3-70B-Instruct`、`Qwen3-Embedding-8B`。
- **與現有卡片不一致處**：
  - 舊限額與能力皆正確，唯 `models` 僅列較舊的 `gpt-oss-120b` 與 `Meta-Llama-3_3-70B-Instruct`，未列目前最強的新免費模型。
- **建議修改**：
  - 建議於 `models` 補入 `"Qwen3.8-27B"`、`"DeepSeek-V4.1-Flash-1017"`（或調整預設 `model` 實測）；`verified` 更新為 `"2026-11-22"`。

---

## 三、新候選管道評估（來自 2026-11-22 週報「新增」與「有變」）

以下僅列出符合「官方 API key 或不用金鑰＋Google/email 簡單註冊（無須實名/+86/台胞證/先儲值或綁卡）＋免費或長期免費額度＋非免費閉源旗艦模型中轉＋OpenAI 相容 chat API」之候選。

### A. 優先建議納入／測試之高價值候選

#### 1. BlockRun（free models）
- **來源**：mvalentsev 新增（2026-11-19）
- **官方連結**：`https://blockrun.ai/free`、`https://blockrun.ai/docs/api-reference/rate-limits`
- **Base URL**：`https://blockrun.ai/api/v1`
- **免費型態**：`不用註冊`（無需 API key、無需錢包）
- **限額原文**（`rate-limits`）：`30 req / minute and 300 req / hour per IP`（`POST /v1/chat/completions`, `billing_mode: "free"`）。官網同時明示：共有 9 個免費開源模型（如 `nvidia/nemotron-3.5-lightning`、`nvidia/nemotron-3-ultra`），當指定模型滿載時會自動導向另一可用的免費模型並於回應 `model` 欄位揭露實際服務模型名稱，請求仍會回傳 `200`。
- **資料與訓練**：官網說明免費模型走免費用層，該上游條款可能允許用提示改進其服務（`Free models run on free tiers whose terms may let the host use prompts to improve its service`）。
- **建議**：**值得加卡片** — 免註冊免 Key 且給到每 IP 每分鐘 30 次、每小時 300 次與強開源推理模型，非常契合 OmniKeep 零設定門檻需求（實測須確認繁中輸出與自動 fallback 表現）。

#### 2. BazaarLink
- **來源**：mvalentsev 有變（2026-11-19；FreeLLMAPI 已收錄 `auto:free`）
- **官方連結**：`https://bazaarlink.ai/free`、`https://bazaarlink.ai/en/docs`、`https://bazaarlink.ai/en/privacy`
- **Base URL**：`https://api.bazaarlink.ai/v1`
- **免費型態**：`註冊後額度定期自動補回`（每日 `00:00 UTC` 重置）
- **限額原文**（`bazaarlink.ai/free`）：`No credit: 10 RPM and 60 weighted units/day. With credit: 20 RPM and 120 weighted units/day. Shared across free models. Daily; resets at 00:00 UTC.`（並發限制 2，另有限制長輸入會消耗較多 weighted units；目前提供 `qwen/qwen3.7-flash`、`deepseek/deepseek-v4-flash-0731free`、`nvidia/nemotron-3.5-lightning-free`、`stealth/glyph-cluster` 等）。
- **資料與訓練**：集聯科技（台灣）營運；隱私權政策載明平台本身不用請求內容訓練模型且正常請求不保存內容（失敗請求除錯、安全審核樣本或非 ZDR 金鑰例外），但上游供應商政策各異。
- **建議**：**值得加卡片** — 台灣團隊維運、繁中友好、提供 `qwen/qwen3.7-flash` 與 `deepseek-v4-flash` 等強模型，且免卡即可日用，適合列入主力備援。

#### 3. cheapllm.shop
- **來源**：FreeLLMAPI 新增（含 adapter）＋ mvalentsev 新增
- **官方連結**：`https://cheapllm.shop/docs`、`https://cheapllm.shop/privacy`
- **Base URL**：`https://cheapllm.shop/v1`
- **免費型態**：`註冊後額度定期自動補回`（公測後為每滾動小時；目前 Beta 期不限量）
- **限額原文**（`cheapllm.shop/docs`）：`During the beta every account is free, with no rate limit. When the beta ends, every account keeps a permanent free tier, with no card: at least 5,000 input tokens and 1,000 output tokens per hour (5,000 and 1,000 today), counted per account over a rolling hour, all keys together.`（單一模型：`deepseek-v4.1-flash-1017`；429 僅限同時 1 個執行中請求）。
- **資料與訓練**：隱私條款明確承諾提示與回應不寫入磁碟、不送其他公司、且不用於任何模型訓練（`they are not used to train any model`）。
- **建議**：**值得加卡片** — 公測期間免費無限流對比品質極佳；但須先註記未來 Beta 結束後每小時 5,000 input / 1,000 output token 僅足夠少數幾篇短文分析。

#### 4. Inferbase
- **來源**：mvalentsev 有變（2026-11-19）
- **官方連結**：`https://inferbase.ai/pricing`、`https://inferbase.ai/privacy`
- **Base URL**：`https://api.inferbase.ai/v1`
- **免費型態**：`註冊後額度定期自動補回`（每日＋每月）
- **限額原文**（`inferbase.ai/pricing`）：`5,000 requests a month, on any model and any key`、`100 managed requests and $0.50 of model usage a day, free`、`Managed requests per minute, per organization: 10`（60 RPM per key）、`Tokens per managed request: 8,192 in, 1,024 out`。
- **資料與訓練**：隱私條款載明預設儲存請求內容 30 天供除錯（可在帳戶/金鑰開啟 Zero Data Retention 關閉），並明確承諾不用客戶內容訓練 AI 模型且不授權託管上游訓練（`We do not use your content to train AI models`）。
- **建議**：**觀察** — 每日 100 次免費額度相當實用，但單次受限 `8,192 in / 1,024 out` tokens，OmniKeep 若分析長網頁或要求詳細 JSON 輸出可能觸及 1,024 output token 上限，須實測確認是否夠用。

#### 5. Routeway
- **來源**：mvalentsev 有變（2026-11-19；FreeLLMAPI 舊有收錄）
- **官方連結**：`https://routeway.ai/`、`https://routeway.ai/models`、`https://routeway.ai/privacy`
- **Base URL**：`https://api.routeway.ai/v1`
- **免費型態**：`註冊後額度定期自動補回`（每日）
- **限額原文**（`routeway.ai/`）：Starter 方案 `$0` 標示 `200 requests per day`、`Single concurrent request`、`Shared low-priority queue`。`models` 頁面目前列出 `MiniMax M3.1 Flash (Free)`、`Glimmer 30B (Free)` 及多款 `Gemma 4 26b` 免費變體。
- **資料與訓練**：隱私政策聲明 Routeway 不存儲用戶提示或回應，但轉送給上游 AI 模型供應商時適用該上游各自政策。
- **建議**：**觀察** — 每日 200 次與免費模型陣容不俗，但 FreeLLMAPI 備註曾提過 Cloudflare 會以錯誤碼 `1010` 阻擋非瀏覽器 User-Agent，納入前須測試 OmniKeep HTTP 標頭相容性。

#### 6. Nous Portal（Hermes Agent）
- **來源**：mvalentsev 有變（2026-11-19）
- **官方連結**：`https://portal.nousresearch.com/`、`https://portal.nousresearch.com/privacy`、`https://inference-api.nousresearch.com/v1/models`
- **Base URL**：`https://inference-api.nousresearch.com/v1`
- **免費型態**：`註冊後額度定期自動補回`（具體週期與次數數字未於未登入公開文件列出，**待驗證**）
- **限額原文**：主頁與即時 `/v1/models` 明確顯示多款標價 `0` 元之 `:free` 路由（2026-11-22 查得 `qwen/qwen4-max:free`、`stepfun/step-3.7-flash:free`、`tencent/hy4-flash:free`、`upstage/solar-mini4:free`、`meituan/longcat-2.5:free`），無須綁卡即可從 `$0` 方案起步；惟 `/api-docs` 與 `/plans` 皆須登入存取，確切 RPM/RPD 數字**待驗證**。
- **資料與訓練**：隱私政策說明用戶可在帳戶 Privacy Settings 開啟「Privacy Mode」，開啟後不存儲推論 payload 且不用於自有訓練或改進（未開啟時預設可能用於改進與支援）。
- **建議**：**觀察** — 即時免費清單竟包含 `qwen/qwen4-max:free` 與 `step-3.7-flash:free`，極具潛力；建議實際申請試打確認未儲值帳號的速率限制與可用穩定度後，再決定是否加卡片。

#### 7. MegaNova
- **來源**：mvalentsev 有變（2026-11-19）
- **官方連結**：`https://www.meganova.ai/pricing`、`https://docs.meganova.ai/free-model-quota`、`https://www.meganova.ai/privacy`
- **Base URL**：公開 `pricing` 頁與文件未於未登入摘要寫出完整端點 URL（依社群整合常用模式需於控制台確認，**端點 URL 與實測待驗證**）
- **免費型態**：`註冊後額度定期自動補回`（每日 `00:00 UTC` 重置）
- **限額原文**（`free-model-quota`）：免卡 Tier 1 帳號每日總計 `550` 次免費額度（按模型分開計算，例如 `Mistral-Small-3.2-24B-Instruct-2506`、`meganova-ai/manta-mini-1.0`、`meganova-ai/manta-flash-1.0` 各 `50/day`；`GLM-4.7-Flash` 在免費表寫 Tier 1 = `0`、Tier 2 起才開放 50/day）。註：該平台付費區亦有販售 Claude/GPT，但免費額度僅限開源／Manta 模型。
- **資料與訓練**：隱私條款寬泛涵蓋可用於開發與改進服務，未見針對免費 API payload 的零訓練承諾。
- **建議**：**觀察** — 免卡每模型日有 50 次但熱門強模型（如 GLM-4.7-Flash）需 Tier 2 才開，優先度低於 BazaarLink 與 BlockRun。

---

### B. 條件受限／透明度不足之次要候選（暫列「觀察」或「不加」）

#### 8. Zro（MoonMath）
- **官方連結**：`https://zro.moonmath.ai/pricing`、`https://zro.moonmath.ai/docs`、`https://zro.moonmath.ai/privacy`（`https://docs.zro.moonmath.ai/` 無法連線，文件均在 `zro.moonmath.ai/docs`）
- **免費型態**：`註冊後額度定期自動補回`（每日重置）
- **限額原文**（`zro.moonmath.ai/pricing`）：`Free plan for Flash models. $0 per month. Free daily usage on DeepSeek V4.1 Flash. Resets every day.`（具體每日次數或 token 上限數字未公開，**待驗證**）。
- **資料與訓練**：隱私條款承諾 Zero request retention 且不用於客戶請求訓練（`We do not use customer requests or logs for training`）。
- **建議**：**觀察** — 模型強（DeepSeek V4.1 Flash）且零保留不訓練，但因具體每日免費上限未揭露，暫不急著建卡片。

#### 9. Aion Labs
- **官方連結**：`https://www.aionlabs.ai/pricing/`、`https://www.aionlabs.ai/docs/rate-limits/`、`https://www.aionlabs.ai/terms/`
- **免費型態**：`註冊後額度定期自動補回`（每日）
- **限額原文**（經 mvalentsev 2026-11-19 轉錄官方頁，官網為 SPA 未展開）：`15 requests/minute; 20,000 tokens/minute; 20,000 tokens/day per account`（無須綁卡，但有極低的日 20,000 token 天花板；服務條款並註明免費使用屬於 courtesy，可能調整或收回）。
- **資料與訓練**：官方服務條款明定不用輸入或輸出訓練模型且不販售（`We do not use your Input or Output to train models and we do not sell them`）。
- **建議**：**觀察** — 日配額僅 20,000 token 對 OmniKeep 長文章分析容易兩三篇就見底，僅適合輕量備用。

#### 10. Merkium
- **官方連結**：`https://www.merkium.nl/docs/pricing`、`https://www.merkium.nl/privacy`
- **免費型態**：`註冊後額度定期自動補回`（每分鐘，官網宣稱非試用且清單內現有模型永久免費）
- **限額原文**（`merkium.nl/docs/pricing`）：`Permanent for the models listed below. This is not a trial and the free tier does not expire.`、`30 requests per minute per API key`（`https://chat.merkium.nl/api/v1`，模型含 `ganymede-1.1`、`pluto-1.2-pro`、`pluto-1.2-flash`、`ceres-1.0`）。
- **資料與訓練**：荷蘭獨立團隊營運；隱私條款明確承諾從不用對話訓練或微調模型（`Your conversations are never used to train, fine-tune or evaluate Merkium models`）。
- **建議**：**觀察** — 永久免費＋30 RPM＋零訓練誠意高，惟其自研小眾模型對繁體中文網頁與結構化 JSON 的表現尚待實測。

#### 11. AnyAPI
- **官方連結**：`https://anyapi.ai/pricing`、`https://docs.anyapi.ai/features/privacy-logging.md`
- **免費型態**：`註冊後額度定期自動補回`（每日）
- **限額原文**：FreeLLMAPI 追蹤記載「capped at 100K tokens/day over free and basic models; no RPM」；官網 `/pricing` 頁面為互動元件（**免費層詳細限額原文與具體免費模型清單待驗證**）。
- **資料與訓練**：官網隱私文件承諾 AnyAPI 不存儲提示、不訓練自有模型，並支援請求層級設定 `training_allowed: false` 過濾上游供應商。
- **建議**：**觀察** — 具體免費模型陣容待註冊確認，目前證據尚不足以直接加卡片。

#### 12. Cohere（Trial keys）
- **官方連結**：`https://docs.cohere.com/docs/rate-limits`、`https://docs.cohere.com/docs/compatibility-api`
- **免費型態**：`註冊後額度定期自動補回`（每月）
- **限額原文**（`rate-limits`）：`Trial keys (and prod keys on newer Chat model variants) are limited to 1,000 API calls a month.`（不限期 Trial Key，支援 OpenAI 相容 API）。
- **資料與訓練**：Cohere Trial API 資料默認政策不在本輪頁面直接展開（相關保留／改進條款須查 Cohere Terms，**待驗證**；一般免費試用層依 Cohere 慣例會用於改進）。
- **建議**：**觀察** — 每月限 1,000 次且非通用開源多模型路由器，僅作為穩定低頻備援考量。

#### 13. FreeInference（Harvard SEAS）
- **官方連結**：`https://doc.freeinference.org/models`、`https://freeinference.org/terms`
- **免費型態**：`註冊後額度定期自動補回`（依實驗室 GPU 負載浮動限額，無公布固定週期數字）
- **限額原文**：官網明確列出 `glm-5.3-flash`、`deepseek-v4-flash`、`minimax-m3`、`qwen3.6-35b` 標為 `Free`；惟 `/terms` 抓取僅見基礎資訊（mvalentsev 記錄其屬於實驗性質，`Usage allowance: amount varies`，容量視負載而定）。
- **資料與訓練**：哈佛大學 SEAS MadSys Lab 實驗服務，會記錄提示與回應供研究用途，並可能將去識別化後的內容、使用數據與路由指標公開或開源。
- **建議**：**觀察** — 模型強但屬學術實驗環境，穩定度不可預期且公開研究語料風險較高，不建議做 OmniKeep 主力預設卡。

#### 14. Kiosapi.id
- **官方連結**：`https://kiosapi.id/`、`https://kiosapi.id/pricing`、`https://kiosapi.id/privacy`
- **免費型態**：`註冊後額度定期自動補回`（每日）
- **限額原文**（`kiosapi.id/pricing`）：`Model Gratis tak memotong saldo (kuota harian)`、`Tier gratis harian`，標示為 `Gratis` 的模型共 4 款：`Gemma 4 26B`、`SEA-LION 27B`、`Qwen3 30B`、`GLM-4.7 Flash`（支持 Google 或 email 登入；但官網未公布具體每日次數或 token 數字，**確切每日限額待驗證**）。
- **資料與訓練**：隱私條款載明請求會轉發給上游 AI 供應商且不應傳送機密資料；API 僅做 gateway 轉送（使用 Redis 追蹤免費配額，使用日誌保留 5 年作稅務與稽核）。
- **建議**：**觀察** — 支援不用先儲值即可呼叫 4 款免費開源模型，但因缺乏公開配額數字且定位偏印尼預付市場，暫先觀察。

#### 15. LongCat（美團 LongCat API）
- **官方連結**：`https://longcat.chat/platform/docs`、`https://longcat.chat/en`
- **免費型態**：`註冊後額度定期自動補回`（每日；依據 FreeLLMAPI 紀錄為 email 註冊每日免費額度，**官網文件未見公開數字待驗證**）
- **限額原文**：`https://longcat.chat/platform/docs` 僅說明註冊後可取 Key 並以 `https://api.longcat.chat/openai` 呼叫 `LongCat-2.5`（1M context / 256K output）及 429 範例，未公布免費配額數量及註冊欄位是否完全免中國手機（**註冊流程與每日配額數字待驗證**）。
- **資料與訓練**：已查網址未展開英文版 API 資料訓練政策（**待驗證**）。
- **建議**：**觀察** — 須先驗證註冊流程是否不卡 +86 手機／實名，再決定是否納入測試。

#### 16. Bytez
- **官方連結**：`https://docs.bytez.com/model-api/docs/billing`、`https://bytez.com`
- **免費型態**：`註冊後額度定期自動補回`（每 4 週發放 USD 1）
- **限額原文**（mvalentsev 轉錄 `billing.md`）：`Open models up to 7B: $1/4 weeks; 1 request at once per account`（額度 4 週後到期，僅支援 7B 參數以下開源模型，同時限 1 個請求）。
- **資料與訓練**：未於本輪讀取頁面明確列出訓練政策（**待驗證**）。
- **建議**：**不加** — 僅限 7B 以下小模型且單並發，不適合 OmniKeep 文章品質與摘要要求。

#### 17. LLMTR
- **官方連結**：`https://llmtr.com/privacy`、`https://llmtr.com/v1/models`（詳情與 mvalentsev 追蹤）
- **免費型態**：`註冊後額度定期自動補回`（每日／部分為 2026-11-24 到期之限時模型）
- **限額原文**：免費帳號免儲值可呼叫 `qwen/qwen3.8-27b-free`、`nvidia/nemotron-3-ultra-550b-a55b`、`nvidia/nemotron-3.5-super-vl-free` 等，但具體每日上限數值未公開（**待驗證**），且新帳號首 24 小時額度更低；多款 `creekside` 免費模型將於 `2026-11-24` 結束免費。
- **資料與訓練**：土耳其供應商營運；隱私與模型頁明言特定免費模型（如 `Nemotron3.5 Super VL`）之文字與多模態輸入可能由供應商留存並用於改進模型。
- **建議**：**不加** — 免費配額數值不公開、多數強模型兩天後到期，穩定度不足。

#### 18. SimpleLLM（EU）
- **官方連結**：`https://simplellm.eu/`、`https://simplellm.eu/models`、`https://simplellm.eu/datenschutz`
- **免費型態**：`註冊後額度定期自動補回`（具體 RPM／每日次數上限未公布，**待驗證**）
- **限額原文**（`simplellm.eu/models`）：僅列兩款 `FREE` 模型（`free-gemma-4-E4B` 與 `free-Llama-3.1-8B-Instruct`，計價為 0 SC），具體使用限額未寫在公開定價頁。
- **資料與訓練**：德國公司營運，GDPR 隱私政策載明請求僅暫存於 RAM 處理，不永久儲存內容且不用用戶資料進行訓練（`No training is performed on user data`）。
- **建議**：**不加** — 僅提供 4B/8B 偏小模型，且未公布速率配額。

#### 19. LLM.kiwi
- **官方連結**：`https://llm.kiwi/`、`https://docs.llm.kiwi/limits`
- **免費型態**：`註冊後額度定期自動補回`（免卡，Google/GitHub 登入，動態限流）
- **限額原文**（`docs.llm.kiwi/limits`）：`LLM.kiwi is currently free to use without a credit card... Limits can change as capacity and model availability change.`（無公布固定 RPM/RPD 數字，採 `model="auto"` 自動路由）。
- **資料與訓練**：未見獨立公開訓練政策說明（**待驗證**）。
- **建議**：**不加** — 強制 `auto` 黑盒路由且無公開配額保障。

#### 20. LLM7.io
- **官方連結**：`https://llm7.io/`、`https://docs.llm7.io/quickstart`、`https://docs.llm7.io/guides/models`
- **免費型態**：`註冊後額度定期自動補回`（第三方列 `100 req/hr` 或 `100K tokens/day`，但官網現況不明）
- **限額原文**：官網首頁目前已改為主打 Pay-as-you-go（Top up from USD 5），且原本的 `https://docs.llm7.io/guides/rate-limits` 回傳 `404 Page Not Found`（官方最新免費額度數字**待驗證**）。
- **資料與訓練**：`llm7.io` 免責聲明記載可能收集並分析匿名使用數據以改進未來模型，不保存個人識別資訊。
- **建議**：**不加** — 官方免費規則文件 404 且頁面已轉向儲值計費導向。

#### 21. Regolo AI
- **官方連結**：`https://regolo.ai/pricing`、`https://regolo.ai/privacy-policy/`
- **免費型態**：`一次性贈送用完就沒`／`限時活動`（新帳號 30 天免費試用）
- **限額原文**（`regolo.ai/pricing`）：`START YOUR 30-DAY FREE TRIAL... No credit card required, no commitment... 1 month duration. Full access for 30 days, then choose a plan. 1M tokens per day.`
- **資料與訓練**：義大利 Seeweb 營運，標榜 Zero Data Retention，不拿請求訓練。
- **建議**：**不加** — 僅限註冊起 30 天試用，之後即須選購付費方案，不符合長期免費需求。

#### 22. Dahl Inference
- **官方連結**：`https://inference.dahl.global/`、`https://inference.dahl.global/docs/tokens/`
- **免費型態**：`一次性贈送用完就沒`
- **限額原文**（`docs/tokens/`）：`New account: 100 million tokens as a gift at signup. They burn after 7 days without a request; accounts that have topped up keep everything.`
- **資料與訓練**：未在已讀文件中看到獨立的提示詞訓練聲明（**待驗證**）。
- **建議**：**不加** — 屬一次性贈送且 7 天未發送請求即清空，不利低頻使用。

#### 23. BeatAPI
- **官方連結**：`https://beatapi.io/`、`https://beatapi.io/pricing`（`https://beatapi.io/privacy` 404）
- **免費型態**：`限時活動`（無公告截止日）
- **限額原文**（`beatapi.io/`）：`3 models, free for a limited time`、`Each account gets 1 successful free request per minute before its first top-up and up to 10 afterward. Free access is available for a limited time and may be restricted or withdrawn.`
- **資料與訓練**：隱私頁 404，資料訓練條款**待驗證**。
- **建議**：**不加** — 未儲值前限每分鐘僅 1 次且屬隨時可撤回的限時優惠。

#### 24. Arli AI
- **官方連結**：`https://www.arliai.com/`、`https://www.arliai.com/pricing`
- **免費型態**：`一次性贈送用完就沒`（或無免費層；主頁直接推 USD 15/月訂閱，mvalentsev 註記舊方案每模型限試用 5 次）
- **限額原文**（`arliai.com/`）：`Sign up for a subscription and unlock unlimited inference, starting at just $15/month.`（官網免費額度未見公開頁面，**待驗證**）。
- **資料與訓練**：主頁 FAQ 明確宣稱 Zero-log，不儲存提示詞與生成結果。
- **建議**：**不加** — 沒有可長期使用的免費推論額度。

#### 25. Novita AI / Pollinations.AI / TokenRouter / OpenTyphoon / MIAPI
- **Novita AI**（`https://novita.ai/pricing`）：免費類型**待驗證**（定價表全數列出單價，未見長期 0 元模型與免儲值固定配額，僅寫 `Free to start`），**不加**。
- **Pollinations.AI**（`https://enter.pollinations.ai/`、`https://gen.pollinations.ai/docs`）：轉向 Pollen 點數經濟與授權登入模式，舊匿名免金鑰端點屬遺留通道，具體永久免費聊天限額**待驗證**，**不加**。
- **TokenRouter**（`https://www.tokenrouter.com/pricing`）：官方網頁僅產品介紹，無公開免費模型與限額文件（**待驗證**），**不加**。
- **OpenTyphoon**（`https://opentyphoon.ai/`）：專精泰語開源模型官網，未公開對一般外部開發者的免費額度表（**待驗證**），**不加**。
- **MIAPI**（`https://miapi.uk/`）：`註冊後額度定期自動補回`（每月 100 次免費查詢，`100 free queries a month`），但它定位為即時網頁搜尋加引用引擎（`miapi-grounded`），非通用文本分析閘道，**不加**。

---

## 四、本輪報告「新增」與「有變」未入選／排除項目對照

下列為 2026-11-22 週報（及 `snapshot.json`）出現、但依篩選規則不列入正式候選的原因彙整：

| 排除原因分類 | 項目清單 | 具體說明（查證依據） |
|---|---|---|
| **無免費額度／純付費或僅極少贈金** | PowerTokens、Teapot Router、Impossibl、RouterPlex、Standard Compute、Liquid Inference、Wallaby、Fireworks AI、HPC-AI Model APIs、Ollama Cloud、Hugging Face Router、NoTrack API、abliteration.ai、AINative | `powertokens.ai/pricing` 目前全模型皆標示 credits 計價無免費表；`teapotrouter.com` 主打 Claude/GPT 折扣（最低儲值 USD 1）且預設無註冊贈金；`huggingface.co/docs/inference-providers/pricing` 已明確寫 `Free Users: Monthly Credits: None`；`ollama.com/pricing` 僅列付費與訂閱；其餘屬一次性微額開戶金（USD 0.05–USD 4）。 |
| **須先儲值／綁信用卡／帳號風控證件** | Together AI、JZS Token、Experiential Labs、Infron、Sail Research、Vercel AI Gateway、IBM watsonx.ai (Lite)、Hetzner Inference API、OrcaRouter | `Together AI` 須儲值 USD 15；`JZS Token` 須 USD 1.5；`Experiential Labs` 須 USD 1 驗卡；`Infron` 須 USD 5 儲值；`Sail Research`、`Vercel AI Gateway`、`IBM Lite` 均標示需綁付款方式；`Hetzner` 註冊風控常要求護照/證件或信用卡預付驗證；`OrcaRouter` 官方 `/free` 已 404，`/pricing` 未公開免費額度且限老牌 GitHub 綁定。 |
| **須實名驗證／中國手機／特定地區或身分資格** | ModelScope、SiliconFlow (China)、Volcengine Ark、Baidu Qianfan、iFlytek Spark Lite、SenseNova、Tencent Cloud TokenHub、Alibaba Cloud Model Studio、AMD Radeon Token Factory、PLaMo API、Upstage (教育/非營利)、NaraRouter (Telegram)、Logfare (須綁 Discord) | 中國站點多須實名或 +86 手機（其中 `developer.amd.com.cn/radeon` 直接連線失敗回錯誤無法驗證）；`PLaMo` 限日本合資格用戶；`Upstage` 僅限學校/醫院/非營利；`Logfare` 強制綁定單一 Discord 帳號且須全程留在其 Discord 伺服器內方可使用（`logfare.ai/tos` 第 4 條）；`NaraRouter` 強制 Telegram 驗證；`Alibaba intl` 為一次性 90 天新用戶配額且部分模型限資格。 |
| **屬 IDE／Coding Agent／PR Review／非通用聊天 API** | Cline、Cursor、Devin Desktop (Windsurf)、GitHub Copilot、Google Antigravity、Google Jules、Codex (ChatGPT Free)、CodeBuddy、CodeGPT、CodeRabbit、Codacy、CodeAnt AI、DeepSource、Graphite、Greptile、Qoder、Qoder CN、Qodo、Sourcery、TRAE、Zed、ZCode、Kiro、JetBrains AI、MiniMax Code、AtomCode、Autohand Code、Baidu Comate、Freebuff、cubic、opencode、VLM Run Gateway、Mixedbread、Puter、xKiro、NavyAI、Bai | 多數為終端或編輯器內綁定使用（例如 `opencode Zen` 限 OpenCode 客戶端、`VLM Run` 主打視覺 OCR/PDF/Video 解析、`Mixedbread` 為知識搜尋、`Puter` 須用主帳號認證 token 而非獨立 API key）。註：`xKiro`、`NavyAI`、`B.AI`、`Mixlayer`、`Opper`、`Sarvam AI`、`The Grid` 未列為本輪主力追蹤或缺乏符合條件之通用穩定 OpenAI 相容端點，維持排除。 |
| **已有 OmniKeep 卡片** | Agnes AI、AIHubMix、Cloudflare Workers AI、Gemini Enterprise Agent Platform (Vertex)、Google AI Studio、Groq、Inception Labs、IteraCompute、Kilo Code、NVIDIA NIM、OVHcloud、OpenRouter、Requesty、SEA-LION、Token Harbor、Z.ai | 見第一、二節逐張查證。 |

---

## 五、本輪尚待後續驗證項目清單（`待驗證`）

下列項目因官方頁面須登入、動態載入或回傳錯誤，未於本次猜測填補，列明已查網址如下：
1. **Gemini 免費具體 RPD/RPM 數字**：已查 `https://aistudio.google.com/docs/rate-limits`（已改至控制台動態檢視）。
2. **Vertex (`gemini-3.5-flash`) 是否自動導向 `gemini-3.6-flash`**：已查 `https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/start/express-mode/overview`。
3. **Z.ai 官方確切並發上限數字**：已查 `https://docs.z.ai/api-reference/rate-limit.md`（導向須登入頁面 `z.ai/manage-apikey/rate-limits`）。
4. **AIHubMix 官方集中 RPM/RPD 總表**：已查 `https://aihubmix.com/model/glm-4.7-flash-free`、`https://docs.aihubmix.com/cn/blogs/free-ai-models`。
5. **JarvisClaw 每 IP 具體限流數值**：已查 `https://jarvisclaw.ai/en/free-llm-api`。
6. **Kilo `reflection/beam-free` 實際推理狀態**（即時 `/models` 還在名單內但 11-17 曾回 404）：已查 `https://api.kilo.ai/api/gateway/v1/models` 與 `https://ai-gateway.kilo.ai/api/v1/models`。
7. **Nous Portal / MegaNova / Zro / AnyAPI / Kiosapi.id / LongCat / LLMTR / SimpleLLM / LLM7.io / BeatAPI 具體未登入公開限額、端點或訓練細則**：已查前述各小節所列對應官方網址，皆因須登入後端查詢、頁面 404 或為未展開動態元件而標註「待驗證」。
