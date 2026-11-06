# 免費線上 LLM 管道調查與實測（2026-11）

日期：2026-11-06　狀態：第一輪完成：文件查證、免金鑰端點實測，以及使用者提供金鑰的 9 家實測。
這份文件補充 `docs/ai_provider_options_2026-11.md` 第 1 節的選項清單；該文件的設計原則照用。

## 0. 結論

**實測排名**：用 OmniKeep 真實的分析 prompt，完整分析通過、而且夠快的（詳見第 2 節）。

| 名次 | 管道與模型 | 時間 | 適合的用途 |
|---|---|---|---|
| 1 | Inception `mercury-3` | 5 秒 | 主力，但額度是一次性 100M token |
| 2 | Agnes `agnes-3.0-flash` | 16 秒 | 主力，也是保底 |
| 3 | Token Harbor `deepseek-v4.1-flash:free` | 19 秒 | 主力或備援 |
| 4 | OVHcloud `gpt-oss-120b`（不用金鑰） | 32 秒 | 備援，每分鐘只有 2 次 |
| 5 | Kilo `kilo-auto/free`（不用金鑰）、Token Harbor `mimo-v2.6-flash:free`、Requesty `gemma-4-31b-it` | 45 到 57 秒 | 備援 |
| — | 推理型模型（AIHubMix GLM-4.7-Flash、SEA-LION、Itera Qwen3.8、NVIDIA 的 DeepSeek V4.1 Flash、MiniMax、Mistral Large 4） | 80 到 190 秒 | 通過但很慢、很耗額度；適合不趕時間的夜間批次 |
| — | 關閉推理後：Z.ai `glm-4.7-flash`、Kilo `reflection/beam-free`、AIHubMix、SEA-LION | 14 到 76 秒 | 備援；見第 2 節「關閉推理後重測」 |
| 不通過 | NVIDIA `glm-5.3-flash`（逾時，帶參數也一樣）；Mistral（每分鐘上限 0，見第 11 節） | — | — |

1. **值得加進選項清單的新管道**：

   | 管道 | 為什麼值得加 | 要注意的 |
   |---|---|---|
   | **NVIDIA NIM** | 約 40 RPM，整個帳號共用；模型最多也最強（DeepSeek V4.1 Flash、Kimi K2.6、GLM-5.3-Flash）；有向量 | 條款限制用在 production；實測免費端點很擠，DeepSeek V4.1 Flash 一篇 143 秒，GLM-5.3-Flash 逾時 |
   | **Inception Mercury 3** | 一次送 100M token；官方標示支援 `json_mode` 和 `structured_outputs`；context 1M | 用完要綁卡 |
   | **Kilo Gateway**（不用金鑰，已實測） | 每 IP 每小時 200 次；OmniKeep 的分析 prompt 實測能解析 | 會記錄提示並拿去訓練；`kilo-auto/free` 實際由來源不明的 stealth 模型回答 |
   | **OVHcloud AI Endpoints**（不用金鑰，已實測） | gpt-oss-120b、Llama 3.3 70B 實測可用，支援 `json_object` | 回應標頭證實每 IP 每模型每分鐘只有 2 次，只適合當備援 |
   | **Requesty** | 每天 200 次；有公司實體和 DPA | — |
   | **AIHubMix** | 40 多個 `-free` 路由 | 第三方整理說每條每天約 100 次 |
   | **Itera Compute** | Qwen3.8-27B 每月 30M token | 活動 2026-11-24 結束 |

   要實名、+86 手機或台胞證的平台一律剔除（2026-11-06 使用者決定：只收 Google 登入或簡單註冊就能用的），所以智譜國內版、魔搭、硅基流動、火山方舟、訊飛、商湯都不列。第 4 節只留作紀錄。智譜的免費模型改走國際版 z.ai，用 email 註冊。

2. **影片裡號稱「免費 Claude Opus、GPT-5.5」的，幾乎都是中轉站**。照決定只列名單，不測（第 7 節）。

3. **很多管道已經停了**：GitHub Models、Cerebras 永久免費、Hugging Face、百度千帆、LongCat 每日免費、Modal、iFlow 等（第 8 節）。影片和舊清單的數字常常過時，連 FreeLLMAPI 的筆記也有好幾處落後官網。

4. **之後要更新這份清單，直接比對兩個來源最省事**：FreeLLMAPI（目錄加實測紀錄），以及 `mvalentsev/awesome-free-ai-coding`（每週實測兩次）。

5. **單一管道撐不住 OmniKeep 的量**：OmniKeep 每天幾百則請求，單一免費管道大多不夠穩，要靠備援鏈（options 文件第 5 節）。

6. **要先跟使用者講清楚的現象**：
   - 推理型免費模型（Nemotron 3 Ultra、Beam）回應很慢，或把輸出額度全花在推理上，結果沒有正文。
   - 這類模型要標「不適合分析」，或在能力旗標裡記錄下來。

## 1. 怎麼找的

**來源**
- 使用者提供的 10 支 YouTube 影片，加上 Code With Yousaf 頻道最新 45 支影片的說明欄。
- 開源閘道 FreeLLMAPI（github.com/tashfeenahmed/freellmapi）：MIT 授權、約 4.8 萬星，2026-11-06 仍有更新。它維護 43 家免費平台的 adapter 和實測筆記，是目前最完整、最新的單一來源。
- GitHub 上 6 份免費 API 清單：
  - `mnfst/awesome-free-llm-apis`（約 1.2 萬星）
  - `open-free-llm-api/awesome-freellm-apis`
  - `for-the-zero/Free-LLM-Collection`
  - `peter123023/awesome-free-llm-api`
  - `mvalentsev/awesome-free-ai-coding`（每週實測兩次，只收合法管道）
  - `guihuashaoxiang/FreeLLM-API-KeyHub`（中國平台）
- 4 個研究 subagent 依類別到各家官方頁查證：國際官方、中國平台、FreeLLMAPI 收錄的閘道、影片裡的閘道。

**篩選原則**（沿用既有決定）
- 只收官方發的 API key，或不需要金鑰的公開端點。
- 「會不會拿資料訓練」不當取捨理由，只記錄一句。
- 混入簡體字不算缺點。
- 會排除的：可能讓使用者帳號被停權的、有安全疑慮的，以及靠帳號池或逆向才能免費提供閉源模型的中轉站（2026-11-06 使用者決定：只列名單，不測）。

**實測方法**：腳本 `free_llm_probe.py`，每個模型送兩個請求。
1. OmniKeep 連線測試用的小 JSON 請求。
2. OmniKeep 真實的分析 prompt（`app/pipeline.py` 的 `_ANALYSIS_PROMPT_TEMPLATE`）加一段約 400 字的繁中技術文章，最多輸出 3000 token。

每次記錄：HTTP 狀態、延遲、`response_format: json_object` 能不能用、JSON 能不能解析、必要欄位有沒有缺、每秒 token 數、rate-limit 回應標頭。送出的都是自己寫的範例文字，沒有用到任何使用者資料。

## 2. 實測結果（2026-11-06，這台電腦，台灣 IP）

「小 JSON」是 OmniKeep 的連線測試請求；「完整分析」是真實的分析 prompt，輸出上限 3000 token。「json_object」表示 `response_format: {"type": "json_object"}` 有沒有被接受。

| 管道與模型 | 金鑰 | 小 JSON | 完整分析 | 速度 | 觀察 |
|---|---|---|---|---|---|
| **Agnes** `agnes-3.0-flash`（基準，用已存的連線） | 有 | 通過，3.4 秒 | **通過**，16.2 秒；json_object 可用；7 個欄位齊全；deep_analysis 1,227 字 | 每秒 61 token | 品質與速度都穩 |
| **OVHcloud** `gpt-oss-120b` | 不用 | 通過，5.1 秒 | **通過**，32.3 秒；json_object 可用；欄位齊全；1,499 字 | 每秒 50 token | 回應標頭 `x-ratelimit-limit-minute: 2`，證實匿名每 IP 每模型每分鐘 2 次 |
| **OVHcloud** `Meta-Llama-3_3-70B-Instruct` | 不用 | 通過，0.8 秒 | **通過**，13.2 秒；欄位齊全，但 deep_analysis 只有 313 字 | 每秒 38 token | 內容偏淺 |
| **Kilo** `kilo-auto/free` | 不用 | 通過（不接受 json_object，改用一般請求再解析） | **通過**，45.1 秒；欄位齊全；1,724 字 | 每秒 56 token | 實際由 `stealth/glyph-cluster` 回答，來源不明 |
| **LLM7** `gpt-oss:20b` | 不用 | 通過，2.6 秒 | **通過**，17.9 秒；json_object 可用；710 字 | 每秒 100 token | 匿名只剩這類基本模型可用 |
| LLM7 `GLM-5.3-Flash`、`DeepSeek-V4-Flash-0731` | 不用 | 等 45 到 62 秒後回 429「Upstream provider rate limit exceeded」 | — | — | 免費上游被擠爆 |
| LLM7 `deepseek-v4.1-flash`、`gemma4:31b` | 不用 | 401「Missing API key」 | — | — | 要註冊金鑰 |
| **Pollinations** `openai-fast`（gpt-oss-20b） | 不用 | 通過 | 間隔 47 秒仍回 402「1 reply every 45 seconds per IP」 | — | 每分鐘不到 1 次，不實用 |
| Kilo `nvidia/nemotron-3-ultra-550b-a55b:free` | 不用 | 通過，6.5 秒 | 180 秒逾時 | — | 推理型，太慢 |
| Kilo `reflection/beam-free`、`dots-3-note-preview:free`、`nemotron-3.5-super-vl:free`、`nemotron-3.5-lightning:free` | 不用 | 通過或部分通過 | 3000 token 全花在隱藏推理上（`reasoning_tokens` 2,699 到 3,000），正文是空的 | 每秒 69 到 206 token | 見下方重測 |

**重測推理型模型**：加上 `reasoning: {"effort": "low"}`，輸出上限放寬到 12,000 token。

| 模型 | 結果 |
|---|---|
| Kilo `reflection/beam-free` | **通過**，8.8 秒，每秒 150 token；推理只用 389 token；欄位齊全，871 字 |
| Kilo `nvidia/nemotron-3.5-super-vl:free` | 76 秒用完 12,000 token，其中推理 10,870 token；JSON 寫到一半被截斷 |
| Kilo `dots-studio/dots-3-note-preview:free` | 113 秒用完 12,000 token，其中推理 8,293 token；沒有理會 effort 參數 |
| Kilo `nvidia/nemotron-3.5-lightning:free`、`nemotron-3-ultra-550b-a55b:free` | 180 秒逾時 |

**結論**：Kilo 免金鑰可以接的是 `kilo-auto/free` 和 `reflection/beam-free`（後者要帶 low effort）。Nemotron 系列和 dots 不適合拿來做分析。

### 要金鑰的管道（2026-11-06 使用者提供金鑰）

金鑰用 `scripts/add_test_connections.py` 存成 OmniKeep 的加密連線，id 3 到 11，名稱都以「免費測試-」開頭。推理型模型第一輪在 3000 token 上限被截斷，所以拿掉上限重測一次，和 OmniKeep 實際呼叫的條件相同；下表取兩輪中較好的一次。

| 管道與模型 | 完整分析 | 時間 | 速度 | 輸出 token（其中推理） | 觀察 |
|---|---|---|---|---|---|
| **Inception** `mercury-3` | **通過**，欄位齊全，1,080 字 | **5.0 秒** | **每秒 431 token** | 約 2,100 | 最快；標題夾雜簡體 |
| **Token Harbor** `deepseek-v4.1-flash:free` | **通過**，1,769 字 | 19.4 秒 | 每秒 111 token | 2,150 | base URL 要用 `https://tokenharbor.ai/v1`（`api.` 子網域不存在） |
| Token Harbor `mimo-v2.6-flash:free` | 通過，1,202 字 | 44.8 秒 | 每秒 30 token | 1,364 | — |
| Requesty `google/gemma-4-31b-it` | 通過，914 字 | 57.4 秒 | 每秒 35 token | 約 2,000 | 小 JSON 在 200 token 上限下沒寫完 |
| Requesty `novita/ling-3.1-flash` | 通過，1,157 字（不接受 json_object） | 55.2 秒 | 每秒 115 token | 6,361 | 輸出很長 |
| NVIDIA `minimaxai/minimax-m3.1-flash` | 通過，1,703 字 | 82.0 秒 | 每秒 19 token | — | — |
| AIHubMix `glm-4.7-flash-free` | 通過，895 字 | 83.6 秒 | 每秒 64 token | 5,334（4,200） | 推理很多 |
| Z.ai `glm-4.5-flash` | 通過，1,081 字 | 74.3 秒 | 每秒 32 token | — | — |
| SEA-LION `Qwen-SEA-LION-v4.5-27B-IT` | 通過，1,208 字 | 112.9 秒 | 每秒 43 token | 4,798（3,797） | 回應標頭寫每分鐘 10 次 |
| NVIDIA `deepseek-ai/deepseek-v4.1-flash` | 通過，1,121 字，但要帶 `chat_template_kwargs: {"thinking": false}` | 143.0 秒 | 每秒 6.8 token | — | 不帶這個參數時，內容全在推理欄位，正文是空的；免費端點很擠 |
| Itera `qwen/qwen3.8-27b` | 通過，1,173 字 | 165.4 秒 | 每秒 42 token | 6,857（5,760） | 每篇約 9K token，每月 30M 大約夠 3,300 篇 |
| NVIDIA `mistralai/mistral-large-4-1t-a52b` | 通過，1,536 字 | 193.2 秒 | 每秒 22 token | 4,213（2,772） | 太慢 |
| Z.ai `glm-4.7-flash` | **不通過**：沒上限時 300 秒逾時；3000 上限時缺 3 個欄位 | — | — | — | 小 JSON 就要 94 到 162 秒 |
| NVIDIA `z-ai/glm-5.3-flash` | **不通過**：300 秒逾時 | — | — | — | — |
| NVIDIA `moonshotai/kimi-k2.6`、`kimi-k3.1-pro` | 404：這個帳號不能用，或模型 ID 不對 | — | — | — | 公開 `/v1/models` 有列 k2.6，但帳號呼叫不到 |
| Requesty `poolside/laguna-m.1` | 404 | — | — | — | — |
| AIHubMix `gemma-4-31b-it-free` | 429（錯誤訊息要你聯絡客服） | — | — | — | — |
| **Mistral** `mistral-small-latest` | 429，標頭 `x-ratelimit-limit-req-minute: 0` | — | — | — | 帳號還沒啟用免費的 Experiment 方案 |

**關閉推理後重測**（2026-11-06，各家的參數不同，OmniKeep 用連線的 `caps.extra_body` 帶上）

| 管道與模型 | 參數 | 關閉前 | 關閉後 | 結論 |
|---|---|---|---|---|
| Z.ai `glm-4.7-flash` | `{"thinking": {"type": "disabled"}}` | 300 秒逾時 | **28 秒**；輸出 1,003 token，推理 0 | 卡片預設 |
| AIHubMix `glm-4.7-flash-free` | 同上 | 84 秒，5,334 token | **43 秒**，996 token | 卡片預設 |
| SEA-LION `Qwen-SEA-LION-v4.5-27B-IT` | `{"chat_template_kwargs": {"enable_thinking": false}}` | 113 秒，4,798 token | **76 秒**，1,112 token | 卡片預設 |
| Kilo `reflection/beam-free` | `{"reasoning": {"effort": "low"}}` | 推理用完 3000 token，沒有正文 | **14 秒** | 卡片預設模型改成它 |
| Kilo `kilo-auto/free` | 同上 | 45 秒 | 43 秒，推理 1,136 token | 參數沒什麼效果 |
| NVIDIA `deepseek-v4.1-flash` | `{"chat_template_kwargs": {"thinking": false}}` | 正文是空的 | 143 秒，通過 | 只有這個模型需要；卡片預設模型不是它，所以不帶 |
| NVIDIA MiniMax、Mistral Large 4、GLM-5.3-Flash | 同上 | 82 到 193 秒或逾時 | 逾時，或參數被忽略（推理仍有 5,000 到 6,000 token） | 不帶 |
| Itera `qwen/qwen3.8-27b` | `{"chat_template_kwargs": {"enable_thinking": false}}` | 165 秒 | 300 秒逾時 | 不帶 |

套用後，用 OmniKeep 的連線測試量回應時間：Z.ai 0.7 秒（不關閉推理時 94 到 162 秒）、AIHubMix 4.8 秒（38.8 秒）、SEA-LION 1.4 秒（17.6 秒）、Kilo beam 1.8 秒。

**從實測看出來的**
- 推理型模型（GLM-4.7-Flash、Qwen3.8、SEA-LION、Mistral Large 4）每篇會多花 3,000 到 6,000 token 在推理上，免費額度消耗快好幾倍。OmniKeep 的能力旗標可以加一項「關閉推理的參數」（例如 `reasoning: {"effort": "low"}` 或 `chat_template_kwargs: {"thinking": false}`），依服務商帶上。
- 非推理或推理很少的模型（Mercury 3、Token Harbor 的 DeepSeek V4.1 Flash）快又省，最適合當主要分析管道。

**注意**
- OmniKeep 的分析請求本身沒有設 `max_tokens`（`app/` 底下找不到），所以實際使用時推理型模型不會被截斷，只是比較慢、比較耗額度。表裡「正文是空的」是測試腳本自己設了上限造成的。
- 這次沒有測 AI Horde（理由見第 7 節）。
- 每個模型只測了一篇範例，速度會受當下的擁擠程度影響，只能看大方向。

## 3. 國際官方一手免費層

| 管道 | 免費內容 | 額度 | 門檻 | JSON／向量 | 條款與風險 | 狀態（信心） |
|---|---|---|---|---|---|---|
| **NVIDIA NIM**（`integrate.api.nvidia.com/v1`） | 84 個模型，含 DeepSeek V4.1 Flash、Kimi K2.6、GLM-5.3-Flash、Nemotron 3 Ultra、Mistral Large 4 | 社群回報約 40 RPM，整個帳號共用；沒有提高上限的途徑 | NVIDIA 帳號；第三方說要手機驗證，不用信用卡 | 依模型而定；有向量 `nemotron-3.5-embed-8b` | 官方寫明不能用在 production | 可用（中） |
| **Inception Mercury 3**（`api.inceptionlabs.ai/v1`） | 新帳號一次送 100M token | 第三方說 1,000 RPM，沒有每日上限（低信心） | email，不用信用卡 | `json_mode`、`structured_outputs`；context 1M | 用完要綁卡 | 可用（高） |
| **Z.ai 國際版**（`api.z.ai/api/paas/v4`） | GLM-4.7-Flash、GLM-4.5-Flash、GLM-4.6V-Flash 免費；GLM-5.3-Flash 要付費（每百萬 token 輸入 0.15、輸出 0.50 美元） | 沒公布；第三方說只能 1 個並行 | 國際站註冊 | 未查到 | — | 可用（價格高，限額低）；已在選項清單 |
| **SEA-LION**（`api.sea-lion.ai/v1`） | Qwen-SEA-LION-v4.5-27B、Llama-SEA-LION-v3.5-70B-R | 10 RPM；每人限一把 Trial key | Google 登入，不用信用卡 | function calling；向量 600M（1024 維） | Trial key；強項是東南亞語言，繁中品質未知 | 可用（高） |
| **Mistral Experiment**（`api.mistral.ai/v1`） | 各模型 | 各來源說法不一：1 RPS、500K TPM、每月 1B token，也有人說約 2 RPM | 手機驗證（不限 +86），不用信用卡 | JSON、`mistral-embed`（未重查） | 請求可能被拿去訓練；官方 pricing 頁已找不到免費 API 的說明 | 不確定（中到低） |
| **Cohere Trial**（`api.cohere.ai/compatibility/v1`） | Command A、R+、R 等 | 每月 1,000 次、20 RPM | 不用信用卡 | 有 Embed | 禁止商用；一天就用完 | 可用但太少（高） |
| **AMD Radeon TokenFactory**（`developer.amd.com.cn/radeon/api/v1`） | 輪替的實驗模型，例如 DeepSeek-V4-Flash | 看回應標頭 | .com.cn 站，可能要實名（未證實） | 未查到 | 實驗性質，模型會換 | 不確定（中到低） |
| **Scaleway** | 1M token，一次性 | — | Scaleway 帳號 | — | — | 可用（中） |
| **Nebius** | Builder Program 給 25 美元抵免，每人最多 50 美元；一般新帳號約 1 美元 | — | — | — | 抵免額，不是長期免費 | 可用（中） |
| **Cerebras** | `gpt-oss-120b`、`qwen-3.8-27b` | 每模型 5 RPM、每日 1M token | 要先綁付款方式才給 5 美元，30 天到期 | — | 官方寫明沒有永久免費層 | 只剩試用（高） |
| **DeepSeek 官方** | 新用戶贈送額度官方沒寫；第三方說約 5M token、30 天 | — | — | JSON；context 1M | Flash 離峰每百萬 token 輸入 0.15、輸出 0.60 美元，很便宜但不免費 | 付費為主（中） |
| **Ollama Cloud**（`ollama.com/v1`） | 26 個雲端模型 | 官方 pricing 頁只剩隨用隨付；第三方說 2026-08-31 改制後有小額起始額度 | email | — | 不拿來訓練 | 不確定（中） |


## 4. 中國平台

**2026-11-06 使用者決定：要實名、+86 手機或台胞證的平台一律剔除。本節只留作紀錄。** 多數官方文件是 JS 單頁，抓不到內文的數字改用搜尋摘要和第三方交叉比對，信心欄有標。

| 管道 | 免費內容 | 額度 | 註冊與實名 | JSON／向量 | 備註 | 狀態（信心） |
|---|---|---|---|---|---|---|
| **智譜 bigmodel.cn**（`open.bigmodel.cn/api/paas/v4`） | GLM-4.7-Flash（context 200K、輸出 128K）、GLM-4.5-Flash、GLM-4-Flash-250414、GLM-4.6V-Flash | 沒公布；第三方說只能 1 個並行 | +86 手機 | 官方確認有結構化輸出 | 永久免費；國際版 z.ai 有同樣的免費模型，金鑰不互通 | 可用（高） |
| **魔搭 ModelScope**（`api-inference.modelscope.cn/v1`） | DeepSeek-V4.1-Flash、GLM-5.3、MiniMax-M2.7 等 | 每帳號每天 2,000 次，每模型最多約 200 次；UTC+8 午夜重置 | 要綁阿里雲中國站帳號並實名 | 文件標題有寫 JSON，內文沒讀到 | 驗證金鑰要實際打一次 chat | 可用（中） |
| **硅基流動 SiliconFlow**（`api.siliconflow.cn/v1`） | 官方頁可見 Hunyuan-MT-7B、Xing4.0-29B、PaddleOCR-VL；bge 向量和 reranker 免費 | 第三方說 1,000 RPM、50K TPM | **官方文件寫明台灣居民可以用台胞證或居住證實名** | JSON；免費向量 | 免費對話模型變少、變小；11-16 會下架 7 個模型 | 可用（中） |
| **火山方舟**（`ark.cn-beijing.volces.com/api/v3`） | DeepSeek-V4.1-Flash、GLM-5.3 系列等 | 協作獎勵計劃：每天每模型最多 5M token 的推論，隔天發等量資源包，30 天有效；個人額度二手資料說 2M | 個人實名；台灣證件能不能過沒查到 | 未查到 | 要簽「豆包模型資料授權協議」，拿資料換額度；官方頁寫合作期到 2026-09-30，部分模型已退出，現況要看控制台 | 不確定（中） |
| **訊飛星火 Spark Lite**（`spark-api-open.xf-yun.com/v1`） | Spark Lite | 輸入 8K、輸出 4K；第三方說 5 RPM；同一把金鑰同時只能 1 個請求 | 第三方說要實名 | 有 `json_object`；沒有向量 | 模型小 | 可用（中） |
| **商湯日日新**（第三方說 `token.sensenova.cn/v1`） | SenseNova-6.7 Flash-Lite、U1 Fast、DeepSeek-V4-Flash | Token Plan 公測、限時免費，沒公布截止日；額度說法從每 5 小時 1,500 次到每週 120 萬積分都有 | 手機號；第三方說不用實名 | 未查到 | 第三方說只限個人學習與原型；影片作者說它「很穩定」 | 可用（低） |
| **阿里雲百煉** | 新人每模型約 1M token、90 天；國內版限北京區 | 一次性 | 國內版要實名；國際版（新加坡）不用大陸實名 | — | 2026-10-29 起國際版的 flash 系列取消新人額度；記得打開「免費額度用完即停」，不然會自動轉成按量計費 | 只有一次性額度（高） |
| **騰訊混元** | Hunyuan-a13b、Hunyuan-embedding 各 1M token | 一次性，1 年內有效 | — | 有向量 | hunyuan-lite 已經不在計費頁 | 只有一次性額度（高） |
| **美團 LongCat**（`api.longcat.chat/openai`） | LongCat-2.5（context 1M） | 2026-06-30 起改成 Token Pack 和按量付費，沒有再看到免費額度 | 境外用 email 或手機就能註冊，不用實名 | — | 第三方說「每天 50M」是 2026-03 的舊資料 | 不確定，傾向沒有（高） |
| **Kimi**（`api.moonshot.cn/v1`） | 大陸手機新用戶送 15 元，3 個月內有效 | — | +86 | — | — | 只有試用（高） |
| **書生 Intern AI** | `intern-latest` | 10 RPM；金鑰 6 個月有效 | — | OpenAI 格式 | 上海 AI 實驗室 | 可用（中） |

**已停或不算免費**
- **百度千帆**：免費的 ERNIE Speed、Lite、Tiny 已在 2026-06-30 下線，2026-07-28 最終停服。現在只剩實名後送的 20 元代金券。
- **心流 iFlow**：免費 API 在 2026-04-17 停了。
- **MiniMax**：沒有免費額度，最便宜的 M3.1-Flash 是每百萬 token 輸入 1 元、輸出 4 元人民幣。
- **階躍星辰**：只剩限時免費到 2026-11-08 的語音模型。


## 5. 第三方閘道（FreeLLMAPI 有收錄的）

FreeLLMAPI 的筆記有多處和官網現況不符，例如 xKiro、Experiential、AINative；下表以官網為準。

| 管道 | 營運方 | 免費內容與額度 | 門檻 | JSON | 紅旗 | 狀態（信心） |
|---|---|---|---|---|---|---|
| **Requesty**（`router.requesty.ai/v1`） | Requesty Ltd，有 DPA 和 EU 資料駐留 | 約 13 個免費模型（Nemotron 3 Ultra 等）；每天 200 次，全部免費模型共用 | 不用信用卡 | 逐模型標示 json_schema 和 json_object | 免費模型少，而且常換 | 可用（高） |
| **OpenRouter `:free`**（`openrouter.ai/api/v1`） | OpenRouter Inc.（美國） | 12 個免費模型；20 RPM；累計購買未滿 10 點每天 50 次，滿 10 點每天 1,000 次 | — | 部分模型有 structured_outputs | 免費端點通常會被上游記錄 | 可用（高）；已在選項清單 |
| **Kilo Gateway**（`api.kilo.ai/api/gateway/v1`） | Kilo Code | 不用金鑰；每 IP 每小時 200 次；9 個免費路由 | 無 | 部分模型有 structured_outputs | 會記錄提示並用於訓練；有來源不明的 stealth 模型 | 可用，已實測（高） |
| **OVHcloud AI Endpoints** | OVHcloud（法國） | 文件寫匿名每 IP 每模型 2 RPM；有金鑰 400 RPM，但要 Public Cloud 專案 | 見第 2 節實測 | — | 文件前後矛盾 | 見第 2 節 |
| **Inferbase**（`api.inferbase.ai/v1`） | Inferbase | 每月 5,000 次；每天 100 次託管請求、0.50 美元；單次輸出最多 1,024 token；10 RPM | 不用信用卡 | 有 structured_outputs；有向量和 rerank | 輸出 1,024 token 放不下 OmniKeep 的完整分析 | 可用但不適合（高） |
| **AnyAPI**（`api.anyapi.ai/v1`） | AnyAPI Inc.（美國） | 每天 100K「ANY Tokens」；Gemma 3n 4B、Qwen3.8 27B | 不用信用卡 | — | 自家點數和 token 的換算不明 | 可用（中） |
| **Routeway**（`api.routeway.ai/v1`） | 未標示 | 9 個 `:free` 模型（DeepSeek V4.1 Flash 等，context 42K）；每天 200 次、1 個並行；實測約 5 RPM | 不用信用卡；要帶瀏覽器 User-Agent | 多數有 response_format | 首頁寫「No rate limits」，和每日上限矛盾；找不到 ToS | 可用（中） |
| **BazaarLink**（`bazaarlink.ai/api/v1`） | 未具名，用台幣計價、開統一發票 | 只有 `auto:free` 一條路由，額度沒公布 | email | — | 不能指定模型 | 可用（中） |
| **OrcaRouter**（`api.orcarouter.ai/v1`） | Continuum-AI-Corp | 7 個免費別名（DeepSeek V4.1 Flash、GLM-5.3-Flash、Hy4 Preview）；額度刻意不公布 | 不用信用卡 | — | 額度不透明 | 可用（中） |
| **UnoRouter**（`api.unorouter.com/v1`） | 未具名 | 169 個 `:free` 模型；每模型約 1 RPM | — | — | 上游可能使用你的輸入；並行時整批 429 | 可用（中） |
| **xKiro**（`api.xkiro.com/v1`） | 匿名；收款走越南銀行和加密貨幣 | 45 個免費模型（Qwen3.8 Max 等）；每天 500K token，Telegram 驗證後 1M | email | — | 營運方匿名、上游不明；付費層宣稱 Claude、GPT-6.1 與官方同價 | 可用（中），只適合當最後備援 |
| **ElectronHub**（`api.electronhub.ai/v1`） | 未具名 | 每週 0.25 美元；約 21 個 `:free` 模型，每天 10 次，看廣告可以加 | — | — | HTTP 200 回應裡會夾帶代理錯誤 | 可用但量小（中） |
| **SimpleLLM**（`api.simplellm.eu/v1`） | EU，有 Impressum | 只有 `gemma-4-E4B` 免費；全帳號只能 1 個並行 | — | 依模型 | 額度要登入才看得到 | 可用但不適合（中） |
| **Experiential Labs** | 自稱 YC 投資 | 免費模型（GPT-6 Luna、DeepSeek V4.1 Flash）共用每天 1M token、10 RPM | 要刷 1 美元信用卡驗證 | — | 免費提供 OpenAI 旗艦系列 | 可用（中），歸入排除類 |
| **Sail Research** | 未具名 | 綁付款方式後每月 5 美元 | 要信用卡 | json_schema | 走 `/v1/responses` 背景工作，延遲不固定 | 可用（中） |
| **NaraRouter**（印尼） | PT. Nara Pemecut Digital | 每天 7M token、15 RPM，但免費方案標示缺貨 | — | — | 低價賣 GPT 5.6 系列 | 不確定（中） |
| **NavyAI**（`api.navy/v1`） | 不明 | Discord 宣傳每天 150K token | — | — | 宣稱提供 GPT、Claude、Gemini | 不確定（低） |
| **LLM7.io**（`api.llm7.io/v1`） | 不明 | 第三方說匿名約 30 RPM | 部分模型不用金鑰 | 有 json_mode 欄位 | 官方內文讀不到 | 見第 2 節實測 |
| **Pollinations**（`gen.pollinations.ai/v1`） | 柏林，MIT | 匿名只剩 GPT-OSS 20B，每 IP 每 45 秒 1 次；其他要用 Pollen 點數 | — | — | — | 見第 2 節實測 |
| **AINative Studio** | AiNative Lab Inc | 官網已沒有免費層（3 天試用，之後每月 5 美元） | — | — | 列出大量 Claude 模型 | 已停（中） |
| **Aion Labs、B.AI** | 不明 | 沒找到免費模型，或只有限時活動 | — | — | — | 不確定（低） |
| **freemodel.in**（FreeLLMAPI 收錄；影片裡寫成 freemodel.dev） | 匿名；收款走 UPI 和 USDT | 每月 1M token、60 RPM；免費層宣稱有 Claude Opus 5、GPT-6.1 | email 或 Telegram | — | 免費提供閉源旗艦，疑似帳號池 | 歸入排除類 |


## 6. 影片裡的閘道（之前沒人驗證過）

可信度主要看四件事：營運方是誰、網域註冊多久（RDAP 查詢）、有沒有條款，以及有沒有公開又透明的 `/models`。

| 管道 | 營運方與網域 | 免費內容與額度 | 紅旗 | 結論（信心） |
|---|---|---|---|---|
| **Itera Compute**（`api.iteracompute.com/v1`） | 重慶公司；網域 2026-08-20 註冊 | 只有 `qwen/qwen3.8-27b`；每月 30M token、160K TPM；超額回 429，不會自動扣款；email 或 Google 註冊，不用信用卡 | 網域很新；**活動 2026-11-24 結束**；禁止用多帳號繞額度 | 可以列，但要標到期日（高） |
| **AIHubMix**（`aihubmix.com/v1`） | AIHubMix, LLC；網域 2023-12 註冊，這批裡最老 | 公開 `/v1/models` 有 40 多個 `-free` 路由（GLM-4.7-Flash、Nemotron 3 Ultra、Kimi K3 coding 等）；第三方整理說多數 5 RPM、每天 100 次，GLM-4.7-flash-free 每天 500 次 | 免費額度只有第三方整理；路由會輪替 | 可以列，當多模型備援（中到高） |
| **Token Harbor**（`tokenharbor.ai/v1`） | TH TECHNOLOGY PTE. LTD.（新加坡）；網域 2026-04 註冊 | DeepSeek V4.1 Flash、MiMo 等 `:free` 路由；每 7 天滾動額度，金額沒公開；60 RPM | 免費路由的內容會被留存、員工可讀；以前要邀請碼，現在不確定 | 可以列（中） |
| **APInex**（`api.apinex.bond/v1`） | 營運方不明；`.bond` 網域，2026-08-01 註冊 | 每天 20M「加權單位」（每個 token 扣 2 到 4 單位）、15 RPM；`free/` 前綴有 DeepSeek V4.1 Flash、Hy4、GLM-5.3、Kimi K3 | 同時「允許免費」使用 Claude Opus 5.5 和 GPT-6.1；額度規則一個月內就變過；找不到條款 | 歸入排除類（中） |
| **zro.moonmath.ai** | MoonMath.ai；網域 2025-07 註冊 | GLM-5.3 Flash、DeepSeek V4.1 Flash，每日重置，額度沒公開 | 連不上 API 主機 | 等有額度數字再說（低到中） |
| **anyrouter.dev** | 營運方不明；網域 2026-04 註冊 | 免費模型要先付 2 美元月費，或捐一把供應商金鑰才能用 | 走共用的捐贈金鑰池 | 不算免費（中） |
| **beatapi.io** | 營運方不明 | `deepseek-v4.1-flash-free`；儲值前每分鐘只能 1 次 | 宣稱 Claude Opus 5.5 便宜 78% | 太慢，不列（中） |
| **top-tools-ai.com** | 營運方不明；沒有條款 | 自家模型每天 10M token，但沒說底層是什麼模型 | 主要賣 3 天、30 天通行證 | 不列（低） |
| **larprouter.com** | 營運方不明；只收加密貨幣 | 沒有免費額度 | 示範去審查模型 | 不列（中） |
| **refuseless.com** | 網域 2026-10 註冊 | 免費模型在 LiteLLM 驗證時回 404 | 主打去審查模型 | 已停（中） |
| **modelrouter.id** | 網域 2026-09 註冊 | 連不上 | — | 不確定（低） |
| **chat.b.ai** | 據說屬 TRON 生態 | 免費活動 2026-09-16 結束 | — | 已停（中） |
| **perchai.app** | — | 是 agent 產品，不是 API；影片說的「20 美元」是每月方案內含的用量 | — | 不適用（高） |
| **Modal** | — | 免費共用端點從 2026-09-01 起不再包含在 Starter 方案；每月 30 美元是算力抵免額 | — | 已停（高） |


## 7. 排除：只列名單，不測

**宣稱免費提供 Claude、GPT 等閉源旗艦模型的中轉站**

排除理由：
- 閉源模型要免費，只能靠帳號池、逆向網頁或盜用額度取得，隨時會停。
- 回應內容可能被竄改。影片 3VJrZNnA1Z4 的說明欄寫到，有人把 unlimited.surf 接進 Claude Code 後，電腦被寫入亂七八糟的東西。
- 對 OmniKeep 的特別風險：分析結果會存進筆記，而使用者的 agent 會透過 MCP 讀取這些筆記，等於多一條提示注入的路。

| 中轉站 | 宣稱 | 紅旗與現況 |
|---|---|---|
| unlimited.surf | 免費、不限量、不用註冊的 Claude Opus、GPT-5.5 | 疑似投毒；現在是 Cloudflare 1000 錯誤，等於已關站。Symantec 2026-10-29 的報告描述過一個未授權中轉服務，會改寫 Claude Code 與 Codex 的設定、換掉 base URL、關掉 sandbox，但報告沒點名是哪個站 |
| agentrouter.org | Claude、GPT 旗艦「不限量低倍率」 | new-api 後台，要用 GitHub 或 linux.do 登入；部分模型已下線 |
| anyrouter.top | Claude Code 公益中轉，註冊送額度 | linux.do 有「All providers failed」的回報；CISPA 研究估計近半數中轉站會偷偷換模型 |
| api520.pro | 要登入才看得到模型 | new-api 範本，沒有營運方資訊 |
| y-api.bestvirtualgoods.com | — | 網域是賣虛擬商品的，2026-05 註冊 |
| ClaudeMix | — | 網域 2026-08 註冊，目前回 Cloudflare 522 |
| pioneer.ai | Claude、GPT 目錄；Pro 方案「無限用量到 2026-08」 | 活動已過期；連不上 |
| freemodel.dev | GPT-6 系列 | new-api 範本，`/v1/models` 只有 3 個 GPT-6 模型 |
| freemodel.in | 每月 1M token，含 Claude Opus 5、GPT-6.1 | 營運方匿名，收 UPI 和 USDT；FreeLLMAPI 註明「回傳的模型身分只是業者自稱」 |
| APInex、Experiential Labs、xKiro 的閉源旗艦路由 | 免費或與官方同價的 Claude、GPT | 見第 5、6 節；它們的開源模型免費路由另外評估 |
| ChatAnywhere 等免費 GPT 中轉 | 免費 GPT | 清單收錄，這輪沒查 |

**重用訂閱 OAuth 或網頁 cookie 的自架路由**
- 9Router、OmniRoute 的 OAuth、cookie 與代理類來源。
- 理由：可能讓使用者自己的帳號被停權（見 `docs/ai_engine_onboarding_survey_2026-11.md` 第 5 節）。

**不是 API 的**
- IDE 或 agent 內建的免費額度：Qoder、WorkBuddy、ZCode、Cline、CodeBuddy、Freebuff。要從外部呼叫只能重用登入，屬於上一類。
- OpenCode Zen 的免費模型：2026-09 起只能用 OpenCode 自己的客戶端（FreeLLMAPI #1249）。
- 影片 PEWkPwjKwPs 講的是 kdns.fr 免費網域和容器；anything.com 是線上 app 產生器。兩者都和 LLM 無關。

**不適合 OmniKeep**
- AI Horde：志工提供算力、要排隊；2026-11-06 線上 23 個文字模型，大多是角色扮演或去審查的微調版，任何 worker 都能看到 prompt。

## 8. 已停或不再免費（2026-11-06 查證）

| 管道 | 現況 | 來源 |
|---|---|---|
| GitHub Models | 2026-07-30 全面退役 | docs.github.com |
| SambaNova | 官方文件還寫有 Free Tier（每天 20 次），FreeLLMAPI 實測 2026-06 起回 402 | 兩邊矛盾 |
| Hugging Face Router | 官方寫 Free 使用者每月抵免額是「None」；`/v1/models` 沒有 0 元模型 | huggingface.co/docs/inference-providers/pricing |
| Cerebras | 沒有永久免費層，只剩綁卡後 30 天的 5 美元試用 | inference-docs.cerebras.ai |
| StepFun 國際版 | `step-5-preview` 要付費 | platform.stepfun.ai |
| Modal | 免費共用端點 2026-09-01 停 | modal.com/pricing |
| 騰訊 Hy4 | 沒找到免費 API；兩週免費只限 WorkBuddy、CodeBuddy | 第三方 |
| Hyperbolic、Chutes、Reka | 要付費或預付 | FreeLLMAPI、第三方 |
| OpenCode Zen 免費模型 | 2026-09 起只限 OpenCode 自己的客戶端 | FreeLLMAPI #1249 |
| 百度千帆免費 ERNIE | 2026-06-30 下線 | cloud.baidu.com |
| 心流 iFlow | 2026-04-17 停 | 第三方 |
| 美團 LongCat 每日免費 | 2026-06-30 起改付費 | longcat.chat change-log |
| AINative Studio | 改成 3 天試用 | 官網 |
| B.AI | 免費活動 2026-09-16 結束 | FreeLLMAPI #1181 |

## 9. 第二輪候選（清單比對找到、這輪還沒查證）

以下出現在 `mvalentsev/awesome-free-ai-coding`（標示 2026-11-05 實測）或其他清單中，不在本輪範圍：

| 管道 | 清單上的說法 |
|---|---|
| Hetzner Inference API | 德國 Hetzner 自有硬體，實驗期間免費；Qwen3.6、Qwen3.8-27B |
| VLM Run Gateway | beta 期間不需註冊或金鑰；Qwen3.8-27B |
| FreeInference（Harvard SEAS） | 哈佛 MadSys Lab 免費提供開源模型，OpenAI 和 Anthropic 兩種格式 |
| Nous Portal | Nous Research（Hermes Agent 的開發者）的 `:free` 模型 |
| Regolo AI | 義大利，資料不留存；一個月內有每日 token 額度，不需信用卡 |
| Upstage Solar | 註冊送 10 美元，不需信用卡 |
| IBM watsonx.ai Lite | 每月 30 萬 token |
| Moark（Gitee AI） | 200 多個開源模型，每天 100 次 |
| 書生 Intern AI | 上海 AI 實驗室，免費 API |
| Jina AI | 向量與 rerank 有免費 token |
| Vercel AI Gateway | 加付款方式後每月 5 美元，另有 0 元模型路由 |
| Merkium、LLM.kiwi、NovAI（香港）、TokenRouter、LLMTR（土耳其）、MegaNova、Kiosapi.id（印尼） | 第三方閘道，有免費模型或每日額度 |
| Arli AI、Bytez、Mixlayer、Wallaby、HPC-AI、RouterPlex、Sarvam AI、OpenTyphoon | 額度很小，或只是一次性小額抵免 |
| PPIO 派歐雲、StreamLake（快手）、天翼 AI、DMXAPI、零一萬物、AI21、Inference.net | 中文清單收錄，多為新人額度 |
| Dahl Inference、Gonka Broker | 走 Gonka 去中心化 GPU 網路 |

## 10. 自架聚合器：FreeLLMAPI 和 OmniRoute

兩者都是使用者在自己電腦上跑的閘道：把多家免費層的金鑰併成一個 `/v1` 端點，自動備援。OmniKeep 的「自訂 OpenAI 相容端點」都接得上。

| | FreeLLMAPI | OmniRoute |
|---|---|---|
| 定位 | 只做免費層，43 家 adapter，加自訂端點 | 通用 AI 閘道，也含 OAuth、cookie 類來源 |
| 授權與熱度 | MIT，約 4.8 萬星，2026-11-06 有更新 | MIT，約 8.4 萬星 |
| 條款風險 | 只用 API key 與免金鑰端點；README 寫明只限個人實驗 | 要手動關掉 OAuth、cookie、代理類來源 |
| 這台的狀況 | 未安裝 | 3.8.52，只綁本機（見 options 文件第 4 節） |

FreeLLMAPI 也適合當「各家現況」的資料來源：它的 `docs/en/providers/` 與 CHANGELOG 會記錄哪家停了免費層、哪家改了限制。

## 11. 要使用者註冊的清單

**2026-11-06 已做成服務商卡片**（`app/provider_catalog.py`）：Inception、Token Harbor、Requesty、NVIDIA NIM、AIHubMix、SEA-LION、Itera Compute、Kilo（不用金鑰）、OVHcloud（不用金鑰）。另外把 Z.ai 的預設模型改成實測通過的 `glm-4.5-flash`。

- 各卡片的預設模型都挑實測通過的。NVIDIA 用 MiniMax M3.1 Flash：DeepSeek V4.1 Flash 要關閉推理才有正文，OmniKeep 目前還不能帶這類參數。
- 用 OmniKeep 自己的連線測試，10 張卡片全部通過。
- **連帶修正**：沒有金鑰的連線原本會送 `Authorization: Bearer dummy-key`。Kilo 收到這個不認得的金鑰會回 401，OVHcloud 則是帶任何金鑰都拒絕。現在沒有金鑰就不送這個標頭（`app/providers/openai_compatible.py` 的 `client_auth`）。本機的 Ollama 和 llama.cpp 本來就不看這個標頭，不受影響。
- **關閉推理**（2026-11-06）：連線新增 `caps.extra_body`，內容會併進每一個 chat 請求，包括連線測試。不能覆寫 `model`、`messages` 等核心欄位，上限 2000 字元。Z.ai、AIHubMix、SEA-LION、Kilo 的卡片預設帶上，結果見第 2 節。
- **用途順序**（2026-11-06）：
  - 分析：Inception → Agnes → Token Harbor → OVHcloud → Kilo
  - 雷達：Token Harbor → Kilo → Requesty
- **Mistral 沒通過**：方案已經改版，沒有「Experiment」了。Free 方案每月內含 10 美元的 API 額度，Limits 頁的限流也都不是 0，但金鑰呼叫任何模型都回 429（code 1300，每分鐘上限 0）。訂閱頁的「API pay-as-you-go」有個「Enable」按鈕，看起來要先開這個才行，但它屬於付費設定，帳上也沒有付款方式，所以沒開，也不做卡片。
- **每週比對**：`scripts/free_channel_watch.py` 會比較 FreeLLMAPI 和 mvalentsev 的清單跟上週快照的差異，報告存在 `%LOCALAPPDATA%\OmniKeep\free_channel_watch\`。桌面 app 的排程「【每週】OmniKeep 免費 LLM 管道比對」每週一 08:30 執行，只回報、不改檔。

只收用 Google 登入或 email 簡單註冊就能用的（2026-11-06 使用者決定）。

| 優先 | 管道 | 申請入口 | base URL | 建議先測的模型 | 註冊方式 |
|---|---|---|---|---|---|
| 1 | NVIDIA NIM | https://build.nvidia.com | `https://integrate.api.nvidia.com/v1` | `deepseek-ai/deepseek-v4.1-flash` | NVIDIA 帳號；第三方說要手機簡訊驗證 |
| 2 | Inception | https://docs.inceptionlabs.ai/get-started/get-started | `https://api.inceptionlabs.ai/v1` | `mercury-3` | email，一次性 100M token |
| 3 | Itera Compute | https://iteracompute.com/free | `https://api.iteracompute.com/v1` | `qwen/qwen3.8-27b` | email 或 Google；活動到 2026-11-24 |
| 4 | SEA-LION | https://docs.sea-lion.ai/guides/inferencing/api | `https://api.sea-lion.ai/v1` | `aisingapore/Qwen-SEA-LION-v4.5-27B-IT` | Google |
| 5 | Requesty | https://www.requesty.ai/free-models | `https://router.requesty.ai/v1` | `google/gemma-4-31b-it`（公開 `/v1/models` 上的 0 元模型） | 帳號註冊 |
| 6 | AIHubMix | https://aihubmix.com | `https://aihubmix.com/v1` | `glm-4.7-flash-free` | 帳號註冊 |
| 7 | Token Harbor | https://tokenharbor.ai | `https://tokenharbor.ai/v1` | `deepseek-v4.1-flash:free` | email；要在 dashboard 手動開啟免費模型 |
| 8 | Z.ai 國際版 | https://z.ai | `https://api.z.ai/api/paas/v4` | `glm-4.7-flash` | email；OmniKeep 已經有這張卡片 |
| 9 | Mistral | https://admin.mistral.ai | `https://api.mistral.ai/v1` | `mistral-small-latest` | 要手機簡訊驗證，不限 +86 |

不建議註冊：xKiro、APInex、freemodel 系列，以及第 7 節的中轉站。

**測試流程**
1. 註冊並建立金鑰。使用者選擇直接把金鑰貼在對話裡（2026-11-06）。
2. 用 `scripts/add_test_connections.py` 把金鑰存成 OmniKeep 的「自訂 OpenAI 相容端點」連線（加密存放，不排進用途順序）。
3. 跑 `probe_saved.py`。它會讀已存的自訂端點，用 OmniKeep 自己的程式在記憶體中解密金鑰，不印出、不寫檔；錯誤訊息裡如果回顯金鑰，會先遮掉再存。測試項目和第 2 節相同。

## 12. 主要來源

- FreeLLMAPI：https://github.com/tashfeenahmed/freellmapi （`docs/en/providers/`、`server/src/providers/index.ts`、CHANGELOG、issues #936、#1181、#1249、#1478）
- 免費清單：https://github.com/mvalentsev/awesome-free-ai-coding ；https://github.com/mnfst/awesome-free-llm-apis ；https://github.com/peter123023/awesome-free-llm-api ；https://github.com/for-the-zero/Free-LLM-Collection ；https://github.com/guihuashaoxiang/FreeLLM-API-KeyHub ；https://github.com/open-free-llm-api/awesome-freellm-apis
- 國際官方：https://docs.api.nvidia.com/nim/docs/api-quickstart ；https://docs.inceptionlabs.ai/get-started/get-started.md ；https://docs.z.ai/guides/overview/pricing ；https://docs.sea-lion.ai/guides/inferencing/api ；https://docs.cohere.com/docs/rate-limits ；https://inference-docs.cerebras.ai/support/rate-limits ；https://huggingface.co/docs/inference-providers/pricing ；https://docs.github.com/en/github-models/prototyping-with-ai-models ；https://modal.com/pricing ；https://ollama.com/pricing ；https://api-docs.deepseek.com/quick_start/pricing ；https://platform.stepfun.ai/docs/en/pricing/details
- 中國平台：https://docs.bigmodel.cn ；https://docs.siliconflow.com/en/faqs/authentication ；https://docs.volcengine.com/docs/82379/1391869 ；https://help.aliyun.com/zh/model-studio/new-free-quota ；https://cloud.baidu.com/doc/qianfan/s/zmrykcisj ；https://longcat.chat/platform/docs/change-log ；https://cloud.tencent.com/document/product/1729/97731 ；https://www.kimi.com/en/help/kimi-api/api-free-trial
- 第三方閘道：https://www.requesty.ai/pricing ；https://openrouter.ai/docs/api-reference/limits ；https://inferbase.ai/pricing ；https://iteracompute.com/free-tier-terms/ ；https://tokenharbor.ai/terms ；https://aihubmix.com/v1/models ；https://free-llm.com （第三方整理）
- 影片：ReJJimUbB7E、3VJrZNnA1Z4、PEWkPwjKwPs、M0pRLyhi9OI、Hsylj00jJvI、R0ZabVokiHw、mcZx8E-F6QI、fll88-uwDKo、OYu1LvAgOPQ、g67kUnCcPto，以及 @codewithyousaf 最新 45 支。
