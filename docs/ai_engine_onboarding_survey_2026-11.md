# OmniKeep 的 AI 引擎與首次設定：2026-11 調查與結論

日期：2026-11-04　狀態：調查完成。第 0、6 節的建議已由 `docs/ai_provider_options_2026-11.md` 取代，改成讓使用者自己選的選項清單，也不再考慮任何會消耗訂閱額度的路。本文件保留調查內容與來源。

前提（2026-11-04 確立）：
- 所有使用者都已經有 Claude（Code）、Codex、Antigravity。
- 剛安裝的使用者沒有任何收藏資料。
- 推薦任何本機引擎或模型之前，都要先做當月的調查。
- 資料會不會被拿去訓練，不作為取捨理由，也不分私人和公開內容走不同管道。使用者選了會訓練的免費方案時提醒一次就好；介意的人自己改接其他管道。

## 0. 結論

1. **首次設定交給使用者自己的 agent**。
   - 做法：OmniKeep 附一份設定用 Skill，加上 MCP 工具，三家都能跑。
   - agent 已經認識使用者，可以偵測硬體、起草「關於你」、問 3 到 5 題、提出設定。
   - OmniKeep 只負責驗證格式，並在 PWA 顯示差異讓使用者按「套用」。
   - 品質最好、不需要任何金鑰、條款風險低。
2. **背景 AI 不能借 Claude 或 Antigravity 的訂閱來跑**。兩家的條款都已明文禁止（原文已查證，見第 1 節）。
   - 背景工作改由 OmniKeep 內建的「引擎路由」決定，依偵測到的硬體和你的選擇分配：
     - **向量**：一律在本機算。理由是沒有額度限制、延遲最低，而且換服務商就得全部重算。
     - **分析**：硬體夠力就用本機 MoE 模型；一般筆電改走雲端。
   - 雲端有三條合法的路：
     - **Sign in with ChatGPT**：不用金鑰，走使用者的 ChatGPT 方案。OmniKeep 是開源、本機執行，符合資格。
     - **便宜的付費 API**：每天 500 篇約每月 8 到 40 美元。
     - **官方免費層**：Gemini、Groq、Cloudflare 等。選了會訓練的方案時，提醒一次「免費方案可能會拿你的內容（包括私人筆記和 Telegram、LINE 訊息）去訓練模型」。
3. **Ollama 不算「過時」，但預設值不適合 OmniKeep**。
   - 問題在預設值：一次只處理 1 個請求、只讀 4096 token。
   - 2026 年真正讓「普通電腦跑強模型」成真的技術在 llama.cpp 主線上：
     - 小活化參數的 MoE，部分專家可以放到系統記憶體。
     - 多槽批次，可以同時處理多個請求。
     - 投機解碼。
   - 建議 OmniKeep 改成管理一個 `llama-server`（MIT 授權、可以一起散布）。Ollama 保留為相容選項。
4. **免費線上模型可以用，但不要透過 OmniRoute 的「免費 Claude、GPT、Gemini」**。
   - 那些靠的是重用訂閱登入、網頁 cookie、公開代理輪換，跟 Anthropic、Google、Kiro、OpenAI 的條款衝突。理由是**帳號可能被停權**（Anthropic、Google 都已執行過），不是資料訓練。
   - 舊版有 critical 等級的漏洞（見第 7 節）。
   - 只用官方 API key 的免費層，包括會訓練的 Gemini 免費層。
   - OmniRoute 升級後可以留著，當這些合法免費層的總閘道：OmniKeep 現在就能把 API 位址指向它。要關掉登入重用、cookie 和代理類來源，並關掉預設的 prompt 壓縮。

### 需要你決定的事

1. **方向**：同意「設定交給 agent、背景交給引擎路由」嗎？
2. **雲端的預設選項**：Sign in with ChatGPT（不另花錢、品質高，但和 Codex 共用額度），還是官方免費層（不花錢、額度小又常變）？兩者都可以讓使用者在設定時自己選，這裡只決定 agent 先推薦哪個。
3. **OmniRoute**：升級到 3.8.52 以上，還是移除？移除屬於刪除，要你確認。
4. **先做哪一段**：建議先做第 8 節的第一階段。

## 1. 調查範圍與親自查證的主張

五個方向平行調查：本機推論引擎、2026 小模型與向量模型、瀏覽器與作業系統內建 AI、用使用者的 agent 當引擎、免費線上模型與 OmniRoute。

以下是影響決策最大的主張，都親自到原始頁面查證過（2026-11-04）：

| 主張 | 查證結果 | 來源 |
|---|---|---|
| Anthropic 不允許第三方代替使用者走 Claude 訂閱 | 屬實。原文："Anthropic does not permit third-party developers to offer Claude.ai login into their own applications, or to route requests through Free, Pro, Max, or Ultra plan credentials on behalf of their users." 但使用者自己登入原版 Claude Code 不受限制 | [1] |
| Antigravity 禁止用第三方軟體存取 | 屬實。第 6 條把 "Using third party software, tools, or services to access the Service" 列為違約，例子是 "using OpenClaw with Antigravity OAuth"，可停權 | [2] |
| OpenAI 開放 app 走 ChatGPT 方案額度 | 屬實。開放對象是 "open-source projects, personal projects that run locally, and selected private apps"。預覽限制：`store: false`、`stream: true`、不能用 system role、不能設 temperature 和 max_output_tokens；文件沒提 JSON schema | [3][4] |
| MCP sampling 已棄用 | 屬實。2026-07-28 版規格：新實作 "SHOULD NOT adopt it" | [5] |
| Ollama 預設值 | 屬實。context 4096 token、`OLLAMA_NUM_PARALLEL` 預設 1 | [6] |
| Qwen3.6-35B-A3B | 屬實。總參數 35B、活化 3B、Apache-2.0、C-Eval 90.0、原生 262K context、含 MTP | [7] |
| OmniRoute 有 critical 等級漏洞 | 屬實。CVE-2026-88062（9.5 分），3.8.50 以前全部受影響；沒開登入或沒設管理密碼時，未登入就能遠端執行程式 | [8] |
| Gemini 免費層會拿內容改進產品 | 屬實。免費層 "Content used to improve our products"，付費層不會 | [9] |

**本機實測**（這台電腦）：
- Claude Code 2.1.314、Codex CLI 0.148.0、Antigravity CLI（`agy`）1.4.12 都在。
- 三者都能非互動執行，並用 JSON Schema 強制輸出格式（`claude -p --json-schema`、`codex exec --output-schema`、`agy -p --json-schema`），也都有 `mcp` 和 `plugin` 管理指令。

其餘數據大多是單一來源或廠商自報，只能看方向，第 4 到 6 節會標註。

## 2. 首次設定：誰來做

| 做法 | 品質 | 需要什麼 | 條款風險 | 缺點 |
|---|---|---|---|---|
| App 內表單 | 低：使用者面對空白欄位 | 無 | 無 | 就是現在的問題 |
| App 內精靈加本機小模型 | 中：小模型不認識使用者 | 本機模型 | 無 | 新使用者沒資料可推 |
| **使用者的 agent（Skill 加 OmniKeep MCP）** | **最高：agent 已經認識使用者，也能查電腦** | 三家都已安裝 | **低**：使用者自己用自己的 agent [1][2] | 三家設定位置不同，安裝器要分別處理 |
| MCP sampling（讓伺服器借 agent 的模型） | — | — | — | 已棄用，Claude Code 也不支援 [5] |
| OmniKeep 用 ACP 或 `claude -p` 驅動 agent | 高 | — | 中到高：屬於「代使用者使用訂閱」[1][2] | 不適合當預設 |

### 建議流程

1. **安裝**：安裝器（或使用者的 agent）自動完成兩件事：
   - 偵測 `claude`、`codex`、`agy`，替每一家註冊 OmniKeep 的 MCP 伺服器：
     - Claude Code：`claude mcp add -s user`。
     - Codex：`codex mcp add`。
     - Antigravity：寫入 `~/.gemini/config/mcp_config.json`。
   - 同一份 `SKILL.md` 複製到三個路徑：`~/.claude/skills`、`~/.agents/skills`（Codex）、`~/.gemini/config/skills`（Antigravity）。
   - 注意：OmniKeep 現在的 MCP 走 SSE。Antigravity 不支援 SSE，Claude Code 也已棄用，要改成 Streamable HTTP 或 stdio。
2. **設定**：使用者對任一 agent 說「幫我設定 OmniKeep」，Skill 帶著 agent 依序走：
   1. `detect_environment`：偵測硬體（CPU、RAM、GPU、VRAM）、本機推論引擎、可用的雲端選項。
   2. agent 依它已知的使用者脈絡，例如記憶、專案、對話，起草「關於你」和初始雷達來源。
   3. 問 3 到 5 題確認，每題附建議答案，使用者回「對」就採用；想更準再追問。
   4. `propose_settings`：OmniKeep 依 schema 驗證後，在 PWA 顯示差異，使用者按「套用」才寫入。
   5. 第一次成功：拿一篇文章分析給使用者看。
3. **新使用者沒有收藏**：agent 先依興趣建議幾個雷達來源，並引導匯入書籤，第一天就有內容。

做法和 OmniKit 提案（`OmniKit/docs/proposals/2026-11-04-onboarding.md`）的原則一致：先掃描、短訪談、LLM 判斷、程式寫入、先預覽再套用。

## 3. 背景 AI 引擎：各選項比較

工作量：每篇收藏一次結構化分析（輸入 1–4k token、輸出 0.5–1k、繁中）、每篇和每次搜尋一次向量、Ask Brain 問答、每天數百篇雷達評分。

| 選項 | 繁中品質 | 吞吐 | 成本 | 會拿資料訓練（只用於提醒） | 條款風險 | 安裝摩擦 | 備註 |
|---|---|---|---|---|---|---|---|
| 使用者的 Claude 訂閱（`claude -p`） | 最高 | 慢（每次約數秒啟動），吃掉使用者自己寫程式的額度 | 已付費 | 依帳號設定 | **中**：由 OmniKeep 代呼叫屬於被禁止的用法 [1] | 無 | 只適合使用者自己在 agent 裡隨選使用 |
| 使用者的 Antigravity（`agy -p`） | 高 | 同上 | 已付費 | 依帳號設定 | **中高**：條款禁止，有停權前例 [2] | 無 | 不做 |
| **Sign in with ChatGPT** | 高 | 受方案的 5 小時額度限制，與 Codex 共用 | 已付費（ChatGPT 方案） | 依帳號設定 | **低**：官方開放給開源、本機 app [3] | 低：登入一次 | 預覽限制多，要自己驗證 JSON [4] |
| **本機 `llama-server`（MoE）** | 中到高（Qwen 會混入簡體，要加檢查） | 多槽批次，吞吐最好 | 0 | 否 | 無 | 中：OmniKeep 可以自動下載管理 | 16GB 顯卡或 32GB Mac 才實用 |
| 本機 Ollama | 同上 | 預設一次 1 個請求、4096 token | 0 | 否 | 無 | 最低 | 要調參數才堪用 [6] |
| Foundry Local（微軟） | 看模型 | 未查證 | 0 | 否 | 無 | 低：pip 安裝、Python 同行程呼叫 | 會自動選 NPU；JSON 支援未查證 |
| 瀏覽器內建（Chrome Gemini Nano） | **不支援中文** | 要開著分頁 | 0 | 否 | 無 | 0 | 不適用 |
| Apple 內建模型 | 支援繁中 | 一次只能 4096 token | 0 | 否 | 無 | 低（只有 Mac） | 只適合短任務 |
| 官方免費層（Groq、Cloudflare） | 看模型 | 每天幾十到幾百則 | 0 | 否 | 低 | 低 | 額度常變 |
| Gemini 免費層 | 高 | 額度常被調降 | 0 | 是 [9] | 低 | 低 | 品質最好的免費選項；選用時提醒一次 |
| 付費便宜 API（Gemini Flash-Lite、DeepSeek） | 高 | 高 | 每月約 8 到 40 美元 | 否（付費層） | 低 | 低：貼一把金鑰 | 最省事 |
| OmniRoute 的 OAuth、cookie、代理來源 | 不穩定（自動切換模型，JSON 不保證） | — | 0 | 依上游 | **高**：帳號可能被停權 | — | 不做 |

## 4. 本機推論：2026 現況

**真正有效的技術**（主要在 llama.cpp 主線，Ollama 已吸收一部分）：
- 小活化參數的 MoE，加上把部分專家放到系統記憶體（`--n-cpu-moe`）。例如 Qwen3.6-35B-A3B 每個 token 只動用 3B 參數，16GB 顯卡加 64GB 記憶體就能跑。
- 混合線性注意力（Gated DeltaNet、Mamba）：長上下文時省記憶體。
- 多 token 預測和投機解碼：單一請求的解碼速度約快 1.7 到 1.85 倍，但只能單槽。
- 4-bit 量化（GGUF K、IQ、MXFP4）。NVFP4 只有 Blackwell 支援，上一代的顯示卡用不到。
- 還不成熟、不建議用的：擴散式 LLM、1.58-bit 模型、Intel NPU（比 iGPU 慢、context 受限）。

**引擎比較重點**：

| 引擎 | 優點 | 缺點 |
|---|---|---|
| llama.cpp `llama-server` | MIT 授權可散布、Windows 原生、多槽批次、MoE 卸載、投機解碼、向量與 rerank | 要自己管理程序和參數（OmniKeep 可以代管） |
| Ollama | 安裝最簡單、非常活躍（2026-10 到 11 月發了 9 版）、Mac 預設走 MLX | 預設 1 槽、4096 token；一份單一作者的測試顯示 32 併發時總吞吐約只有 llama.cpp 的八分之一（只能看方向）；商業重心轉向雲端 |
| LM Studio | 介面好、MLX 有連續批次 | 專有授權，條款禁止綁包散布 |
| vLLM、SGLang | 吞吐最強 | Windows 只能走 WSL2 或不支援；16GB 顯卡放不下 KV cache |
| Foundry Local、Lemonade | 會自動選 NPU、可綁包 | JSON 支援未查證，之後再評估 |

**各層硬體建議**（速度是依記憶體頻寬推估，必須用 `llama-bench` 實測）：

| 硬體 | 分析模型 | 向量模型 | 預估 |
|---|---|---|---|
| T1 文書筆電（iGPU、16GB） | Qwen3.5-4B 或 9B，只做雷達短評分；完整分析建議走雲端 | Qwen3-Embedding-0.6B（CPU） | 9B 每篇約 40 到 60 秒，只適合夜間批次 |
| T2 Mac 16GB／32GB | 16GB：Qwen3.5-9B 或 Gemma 4 12B；32GB：Qwen3.6-35B-A3B | 同上 | 32GB 可以本機為主 |
| T3 NVIDIA 16GB（這台：16 GB 工作站顯示卡，頻寬 224 GB/s） | Qwen3.6-35B-A3B 的 Q4，加 `--n-cpu-moe`；背景開 4 到 8 槽 | 同上，或 4B 版 | 每秒約 25 到 50 token（推估，未實測） |

**向量模型**：Qwen3-Embedding-0.6B 的多語分數（MMTEB 64.33）高於目前用的 embeddinggemma-2（61.36），截成 256 維幾乎不掉分，Apache-2.0。

**繁體中文**：Qwen 系列會混入簡體字。研究測得現行最強的視覺語言模型有 3% 到 19% 的簡體汙染。必須在系統提示要求臺灣正體，並用 OpenCC `s2twp` 比對輸出，超標就重試。

## 5. 免費線上模型與 OmniRoute

**OmniRoute 是什麼**：
- 本機的 AI 閘道，MIT 授權，GitHub 約 8.4 萬星。
- 宣稱的「每月約 16 億免費 token」，是你自己去各家註冊之後的加總估算，其中 10 億來自 Mistral。

**合法與不合法的部分**：
- 合法：各家官方 API key 的免費層。
- 有條款風險：
  - 重用登入的 OAuth：`claude`、`codex`、Copilot、`kiro`、`agy`、`qoder`、`cursor`。
  - 網頁 cookie：`claude-web`、`gemini-web` 等。
  - 輪換公開代理繞過限流：官方指南寫明 "IP rotation … to avoid rate limiting"。
  - Quota-Share：把一個訂閱帳號分給多人，等於帳號共享。
- 它的條款旗標在 v3.8.48 只是顯示，不會擋路由；而且 `claude`、`codex` 沒有標任何旗標，但 Anthropic 明文禁止這種用法 [1]。

**其他問題**：
- 切換模型時 JSON 和繁中品質都沒有保證：轉給 Claude 時 JSON schema 只變成提示文字，轉給 Kiro 時直接丟掉。
- 預設會壓縮 prompt。

**官方免費層現況**：

| 服務 | 適合 OmniKeep 嗎 | 重點 |
|---|---|---|
| Gemini 免費層 | 適合，品質最好 | 會拿內容改進產品 [9]，選用時提醒一次；額度常被調降 |
| Groq | 適合 | 支援嚴格 JSON；每模型每天約 1,000 次（方案標示不清） |
| Cloudflare Workers AI | 適合（含向量） | 每天 10,000 Neurons（推估約 170 到 260 次分析）；JSON 不保證 |
| OpenRouter `:free` | 可用 | 免費模型平均上架 75 天就換 |
| NVIDIA、SambaNova、Mistral | 不適合 | 只限試用或評估，或額度極小 |
| GitHub Models、Hugging Face、Together、Chutes | 不可用 | 已退役或沒有免費層 |

## 6. 建議架構：引擎路由

不分私人或公開內容，全部走同一套設定。使用者選了會拿資料訓練的免費方案時，提醒一次「免費方案可能會拿你的內容（包括私人筆記和 Telegram、LINE 訊息）去訓練模型」；介意的人自己改接其他管道。

| 工作 | 預設 | 理由 |
|---|---|---|
| 向量 | 本機小模型（Qwen3-Embedding-0.6B，CPU 就能跑） | 每次搜尋都要算：沒有額度限制、延遲最低；換服務商就得全部重算，固定在本機最穩 |
| 單篇分析、Ask Brain | 設定時由 agent 依使用者狀況建議：有 ChatGPT 方案就用 Sign in with ChatGPT；想完全免費就用官方免費層（Gemini、Groq、Cloudflare）；硬體夠力（T3、T2-32GB）或想離線、不受額度限制就用本機 `llama-server` | 品質、成本、額度的取捨，交給使用者選 |
| 雷達評分（量大） | 官方免費層或本機小模型 | 量大但每則輸出短，最省額度 |
| 隨選的重度整理（例如「整理這週收藏」） | 使用者在自己的 agent 裡發起，經 MCP 讀寫 | 個人使用、條款允許，品質最高 |

另外三條：
- 可以設定多個服務商依序備援，額度用完自動換下一個。
- 每筆收藏記錄是哪個模型、哪版 prompt 產生的。
- 輸出一律做 JSON 驗證加簡體偵測，不合格就重試或換下一個服務商。

## 7. 立即可做的修正（不必等改版）

1. **OmniRoute 安全**：
   - 3.8.50 以前有 CVE-2026-88062（9.5 分），另有 CVE-2026-118984（不輸入舊密碼就能改管理密碼）。
   - 要用的話，先升級到 3.8.52 以上、設管理密碼、開 `requireLogin`、只綁 127.0.0.1；不用的話就移除。
2. **Ask Brain 被截斷**：
   - 沒有設定 `OLLAMA_CONTEXT_LENGTH`，`app/brain.py` 也沒傳 `num_ctx`，所以每次問答只有 4096 token。
   - 修正：在 `brain.py` 傳 `num_ctx`，或改用 llama-server。
3. **MCP 改成 Streamable HTTP**：讓 Antigravity 也能接上 OmniKeep。
4. **向量模型改成 Qwen3-Embedding-0.6B**：用 `rebuild_embeddings.py --reembed --all` 全部重算，這台約 2 到 3 分鐘。
5. **繁中純度檢查**：加 OpenCC。

## 8. 分階段

| 階段 | 內容 |
|---|---|
| 1 | 第 7 節的修正；MCP 改 Streamable HTTP；`detect_environment`、`propose_settings`、`apply_settings` 三個 MCP 工具；一份給三家 agent 的設定 Skill，安裝器自動註冊；PWA 的差異確認頁；合併「使用者背景」和雷達興趣設定檔 |
| 2 | 引擎路由；OmniKeep 代管 `llama-server`（自動下載對應版本與模型、依硬體選擇）；Sign in with ChatGPT；每筆收藏的模型與 prompt 版本記錄 |
| 3 | 選用會訓練的免費方案時的一次性提醒；多個免費層之間的自動備援；Foundry Local／NPU 評估；讀取 OmniKit 個人配置當初稿 |

## 9. 來源

1. https://code.claude.com/docs/en/legal-and-compliance （2026-11-04 查證原文）
2. https://antigravity.google/terms （第 6 條，2026-11-04 查證）
3. https://developers.openai.com/cookbook/articles/sign-in-with-chatgpt
4. https://developers.openai.com/siwc/token-sharing-open-source/preview-limitations
5. https://modelcontextprotocol.io/specification/2026-07-28/client/sampling
6. https://docs.ollama.com/faq
7. https://huggingface.co/Qwen/Qwen3.6-35B-A3B
8. https://osv.dev/vulnerability/GHSA-hf57-cqmx-p4gr
9. https://aistudio.google.com/docs/pricing
10. https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md
11. https://computingforgeeks.com/ollama-vs-vllm-vs-llama-cpp/ （單一作者的吞吐測試，只能看方向）
12. https://huggingface.co/Qwen/Qwen3-Embedding-0.6B
13. https://huggingface.co/google/embeddinggemma-2
14. https://aclanthology.org/2026.findings-acl.1830/ （繁中的簡體汙染）
15. https://developer.chrome.com/docs/ai/prompt-api （Gemini Nano 支援的語言）
16. https://learn.microsoft.com/en-us/azure/foundry-local/what-is-foundry-local
17. https://developer.apple.com/documentation/technotes/tn3193-managing-the-on-device-foundation-model-s-context-window
18. https://code.claude.com/docs/en/skills ； https://learn.chatgpt.com/docs/build-skills ； https://antigravity.google/docs/skills
19. https://code.claude.com/docs/en/mcp ； https://learn.chatgpt.com/docs/extend/mcp ； https://antigravity.google/docs/mcp
20. https://github.com/cheaper-inference/OmniRoute/blob/HEAD/docs/reference/FREE_TIERS.md ； 同 repo `docs/reference/PROVIDER_REFERENCE.md`、`docs/ops/PROXY_GUIDE.md`
21. https://console.groq.com/docs/your-data ； https://developers.cloudflare.com/workers-ai/platform/data-usage/
