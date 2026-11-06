# OmniKeep AI 服務選項清單（Hermes Agent 式，讓使用者自己接）

日期：2026-11-04　狀態：取代 `docs/ai_engine_onboarding_survey_2026-11.md` 第 0、6 節的建議。那份文件的調查和來源仍可參考。
2026-11-06 補充：免費管道的擴大調查和實測放在 `docs/free_llm_channels_2026-11.md`，新增的候選管道見該文件第 0 節。

## 0. 設計原則

- **只列選項，不替使用者預設答案。** 設定時由使用者的 Claude、Codex 或 Antigravity 依他的狀況說明各選項，使用者自己選、自己貼金鑰。
- **不提供任何會消耗使用者訂閱額度的路**：背景工作不走 Claude、Antigravity 訂閱，也不走 Sign in with ChatGPT。
- **預設使用者都是桌機**，規格接近 20 核 CPU、64 GB RAM、16 GB 顯示卡。
- **混入簡體字不算缺點**，所以不強制做繁簡檢查。
- **「會不會拿資料訓練」不作為取捨理由**：使用者選了會訓練的免費方案時，提醒一次即可。
- **仍會排除的**：可能讓帳號被停權、或有安全漏洞的做法，例如 OmniRoute 的登入重用、cookie、代理類來源。

## 1. 選項清單

| 選項 | 費用 | 限制（2026-11-04 查） | 需要使用者做什麼 | 備註 |
|---|---|---|---|---|
| **本機 llama.cpp**：分析 Qwen3.6-35B-A3B、向量 Qwen3-Embedding-0.6B | 0 | 沒有額度上限、可離線；速度依顯示卡 | 不用（OmniKeep 代管，第二階段） | 16 GB 顯示卡加大記憶體可跑 MoE；背景開多槽 |
| **Agnes**（`agnes-3.0-flash`） | 0（官方「體驗價」三項都是 0 美元） | RPM 依帳號與金鑰權限：個人免費約 20 RPM；企業金鑰依使用者所述是個人版的 2 倍，以 console 顯示為準。沒公布每日上限；沒有向量；文件沒列 JSON 格式參數，需實測 | 到 platform.agnes-ai.com 申請金鑰；企業金鑰由企業帳號管理 | 很適合當保底；context 512K、最大輸出 65,536 token |
| **Gemini API 免費層** | 0 | Flash 約 5 RPM、每日 20 次；Flash-Lite 約 10 RPM、每日 500 次（第三方數據）；有免費向量 | 到 AI Studio 申請金鑰 | 免費層內容會拿去改進產品（提醒一次） |
| **Google AI Pro 附送的 Cloud 抵免額** | 0（用完才扣款） | 每個 Pro 帳號每月 10 美元：Gemini 3.8 Flash 約 2,100 次（2026-12-31 前價格）、3.5 Flash-Lite 約 3,800 次 | 加入 Google Developer Program、建 Cloud 付款帳戶（要信用卡）、套用抵免額、建專案 | 走 Vertex（Gemini Enterprise Agent Platform）最穩；付費層不訓練 |
| **Groq 免費** | 0 | 每模型 30 RPM、每日 1,000 次、每日 20 萬 token；沒有向量 | 申請金鑰 | 支援嚴格 JSON schema |
| **Cloudflare Workers AI** | 0 | 每日 10,000 Neurons（推估約 400 則分析）；有 `bge-m3` 向量 | 申請帳號與 API token | 部分模型才支援 JSON |
| **OpenRouter `:free`** | 0 | 20 RPM；每日 50 次，累計儲值滿 10 美元後變每日 1,000 次 | 申請金鑰 | 免費模型常替換 |
| **Z.AI GLM Flash** | 0 | 據稱 1 個並發（第三方說法）；2026-11-06 實測：GLM-4.7-Flash 要關閉推理（卡片已預設帶上），一篇約 28 秒 | 申請金鑰（email） | 適合單線程背景工作 |
| **2026-11-06 新增的免費卡片**：Inception Mercury 3、Token Harbor、Requesty、NVIDIA NIM、AIHubMix、SEA-LION、Itera Compute、Kilo（不用金鑰）、OVHcloud（不用金鑰） | 0 | 各卡片的額度與實測時間，見 `docs/free_llm_channels_2026-11.md` 第 2 節 | Google 或 email 註冊；Kilo、OVHcloud 不用註冊 | 都通過真實分析 prompt 的實測 |
| **OmniRoute 閘道** | 0 | 把上面多家的 API key 免費層併成一個端點，自動備援 | 在 OmniRoute 裡接各家金鑰 | 只接 API key 類；只讓使用者自己的電腦連（見第 4 節） |
| **付費便宜 API**（Gemini Flash-Lite、DeepSeek 等） | 每天 500 篇約每月 8 到 40 美元 | 額度最充足 | 申請付費金鑰 | 最省事 |
| **自訂 OpenAI 相容端點** | 看服務商 | — | 填位址與金鑰 | 任何相容服務都能接 |

**不提供的**：
- 用 Claude、Antigravity 或 ChatGPT 訂閱跑背景工作：會燒使用者的訂閱額度，Claude 和 Antigravity 的條款也禁止。
- OmniRoute 的 OAuth、網頁 cookie、公開代理類來源：可能讓帳號被停權。

## 2. Google AI Pro 抵免額怎麼用（給有 Pro 的人）

每個 Pro 帳號都要各做一次。步驟依 Google 官方說明（2026-11-04 查證），畫面名稱可能略有不同。

**A. 領取抵免額**
1. 用 Google AI Pro 帳號登入 https://developers.google.com/program ，加入 Google Developer Program（免費）。個人 @gmail.com 帳號的 premium 福利已改由 AI Pro 或 Ultra 訂閱提供。
2. 打開 My Benefits：https://developers.google.com/program/my-benefits ，找到「Google Cloud credit」卡片。卡片上會列出你能用的付款帳戶。
3. 下拉選單是空的或顯示「No billing account」時：先到 https://console.cloud.google.com/billing 建立付款帳戶（要信用卡），再回到第 2 步。用別人的付款帳戶時，你需要 `billing.accounts.redeemPromotion` 權限。
4. 選這個付款帳戶，按套用，並勾選「Always use this billing account」，之後每月的抵免額會自動套用。已套用的抵免額不能再移到別的帳戶。
5. 如果卡片顯示的是 promo code 而不是下拉選單：到 https://console.cloud.google.com/billing/redeem 貼上代碼、選付款帳戶、按 Continue。
6. 抵免額發放後一年內有效，可用在任何 Google Cloud 產品，包含 Vertex AI。

**B. 用在 Vertex（Gemini Enterprise Agent Platform）**
- **最簡單（express mode）**：
  1. @gmail.com 帳號打開 https://console.cloud.google.com/expressmode ，它會自動建立 API 金鑰。
  2. 在 express mode 裡連結步驟 A 的付款帳戶，用量才會扣抵免額。
- **標準方式**：
  1. 在 Cloud Console 建立專案，連結步驟 A 的付款帳戶。
  2. 啟用 Gemini Enterprise Agent Platform（原 Vertex AI）的 API。
  3. 到 https://console.cloud.google.com/agent-platform/studio/settings/api-keys 建立 API 金鑰。
- **填進 OmniKeep**：在「Google Vertex」卡片貼上金鑰（加上專案 ID 和區域 `global`）。OmniKeep 目前還不支援 Vertex，第二階段要加，SDK 參數屆時實測。

**C. 控管費用**
- 到 https://console.cloud.google.com/billing/budgets 設預算告警。
- 預算不會自動封頂：抵免額先扣，用完直接扣你的卡。

**注意**：
- **AI Studio API 金鑰這條路目前沒定論**：2026 年 5 到 6 月有多起回報說抵免額沒扣到 AI Studio 的預付帳戶上，Google 客服建議改走 Vertex。
- **一個人用自己的多個 Pro 帳號**：條款沒有明文禁止，屬灰色地帶。
- **同事的帳號**：Google Developer Program 條款禁止分享付費福利或使用他人帳號，所以同事應各自用自己的帳號和自己的 OmniKeep，不要彙整到同一台。
- 第 1 步和第 3 步的權益名稱以 Google 官方頁面為準（10 美元已查證：developers.google.com/program/plans-and-pricing）。

## 3. Agnes 金鑰為什麼失效、怎麼修

- **原因**：OmniKeep 收到的 `This token status is unavailable`，是 Agnes 所用閘道（開源 new-api 的改版）在「金鑰被停用」時回的訊息。不是過期、不是額度用完，也不是帳號被封；帳號被封會回 403。
- **誰停用的**：可能是在 console 被關掉，或 Agnes 依條款撤銷。企業金鑰也可能是企業帳號的管理員停用或輪換了，要先問管理員。
- **修法**：
  1. 登入 https://platform.agnes-ai.com ，到 `settings/apiKeys` 看這把金鑰。
  2. 是停用狀態就重新啟用；啟用不了就刪掉重建。新金鑰只會顯示一次。
  3. 新金鑰填進 OmniKeep「設定 › AI 服務商」，按測試。
  4. 新金鑰還是 401 或變成 403，就是帳號層的問題，把錯誤裡的 request id 寄給 support@agnes-ai.com。
- **注意**：同一類型的金鑰共用一個額度池，多開金鑰不會多拿額度；條款也禁止規避限額。

## 4. OmniRoute 升級與測試結果（2026-11-04）

- **版本**：要用 3.8.52 以上（npm 上 2026-10-19 的版本）。OSV 資料庫查 3.8.52 沒有已知漏洞；3.8.50 以前有 CVE-2026-88062。升級前先備份 `~\.omniroute` 底下的資料庫。
- **安裝補強**：新版 npm 預設擋下安裝腳本。要手動補跑 omniroute 自己的修正腳本，它會把 Windows 版原生模組複製到正確位置，只在本機複製檔案。
- **升級後健檢**：資料庫遷移完成、SQLite 檢查通過、已存憑證能解密、原生模組相容、健康檢查 healthy。
- **要注意的地方**：
  - **預設綁所有網路介面、而且推論 API 不需要金鑰**：預設綁 `0.0.0.0`、`REQUIRE_API_KEY=false`。實測不帶金鑰打 `/v1/chat/completions` 回 400（模型不存在），而不是 401，代表沒有驗證。管理介面有登入保護，回 401。
    - **風險**：電腦所在的網路一旦被 Windows 歸類成允許連入的網路（例如私人網路），OmniRoute 就會在沒有任何金鑰的情況下對外開放。
    - **修法**：在 `~\.omniroute\.env` 加 `OMNIROUTE_SERVER_HOST=127.0.0.1`，啟動後確認只綁本機、安全警告消失。
  - **會讀「目前所在資料夾」的 `.env`**：在 OmniKeep 資料夾執行時，它讀到了 OmniKeep 的 `.env`，連 `PORT` 都被蓋掉。啟動 OmniRoute 一定要在 `~\.omniroute` 底下執行。
  - **CLI 預設連 `localhost`**，Windows 會先解析成 IPv6，所以只綁 127.0.0.1 時要加 `--base-url http://127.0.0.1:20128`。

安全的啟動方式（在 PowerShell 執行；設定永久化之前，這次啟動只綁本機）：

```powershell
Set-Location $env:USERPROFILE\.omniroute; $env:OMNIROUTE_SERVER_HOST='127.0.0.1'; omniroute serve --daemon --no-open
```

## 5. 設定介面怎麼做（照 Hermes Agent，補上它缺的）

Hermes Agent（MIT，v0.22.7，2026-11-03）的做法：
- 首次設定有 `hermes setup` 精靈。
- `hermes model` 依序選服務商、登入或貼金鑰、選模型。
- 內建 40 多家服務商，另可接自訂端點。
- 金鑰和設定分開存放。
- 有備援鏈 `fallback_providers`，以及多把金鑰輪替。

OmniKeep 要做的：
1. **服務商卡片**：每張卡帶位址、建議模型、金鑰申請連結、免費額度、最後查證日期。「自訂端點」也放在同一層，不預先選好任何一家。
2. **貼金鑰後自動列出可用模型**，再按「測試」實際送一筆小的中文 JSON 請求。這一步 Hermes 沒做。
3. **依工作分槽**：分析、Ask Brain、雷達評分、向量各自選服務商與模型，預設跟分析用的那家相同，各有自己的備援鏈。
4. **備援規則**：
   - 429、5xx：退避重試，用完才換下一家。
   - 401、403、404：立刻換下一家。
   - 遵守 `Retry-After`；下一筆工作回到主要服務商。
5. **每把金鑰的狀態燈與冷卻時間**。「金鑰被停用」這類 401 標成要人工處理並附修復連結，不自動重試。
6. **錯誤訊息翻譯**：把各家英文錯誤翻成「知道怎麼處理」的中文。例如 Agnes 的 `This token status is unavailable` 翻成「金鑰被停用：到 platform.agnes-ai.com 重新啟用或重建」。
7. **模型能力旗標**：記錄是否支援 JSON schema、向量、context 長度，可手動修改，依旗標自動調整呼叫方式。
8. **設定由 agent 帶著做**：使用者對自己的 Claude、Codex 或 Antigravity 說「幫我設定 OmniKeep」，agent 偵測硬體、說明選項、帶他申請金鑰。使用者自己貼金鑰，agent 再呼叫 OmniKeep 測試並儲存。

## 6. 分階段

| 階段 | 內容 |
|---|---|
| 1 | 服務商卡片與自訂端點、分槽與備援鏈、測試按鈕、金鑰狀態燈與錯誤翻譯；給 agent 用的設定 Skill 與 MCP 工具（偵測環境、提出設定、套用設定）；MCP 改 Streamable HTTP；修 Ask Brain 的 4096 token 截斷 |
| 2 | OmniKeep 代管本機 `llama-server`（依顯示卡自動下載對應版本與模型）；Gemini 走 Vertex（使用 Pro 抵免額）；合併「使用者背景」與雷達興趣設定檔 |
| 3 | 依使用情況再加入其他服務商卡片；讀取 OmniKit 個人配置當初稿 |

## 7. 來源

- Google Developer Program 方案與價格：https://developers.google.com/program/plans-and-pricing （10 美元已查證）
- 抵免額兌換與用途：https://developers.google.com/profile/help/benefits
- AI Studio 方案與計費：https://aistudio.google.com/docs/google-ai-plans ；https://aistudio.google.com/docs/billing
- 抵免額沒扣到 AI Studio 的回報：https://discuss.ai.google.dev/t/10-monthly-developer-program-credits-visible-in-gcp-billing-but-ai-studio-forces-prepay-top-up-no-available-credits/143815
- Google Developer Program 條款：https://developers.google.com/profile/terms
- Agnes 價格、限制、條款：https://wiki.agnes-ai.com/en/docs/pricing.md ；https://wiki.agnes-ai.com/en/docs/code.md ；https://wiki.agnes-ai.com/en/docs/tokenplan.md ；https://wiki.agnes-ai.com/en/docs/terms-of-service.md
- new-api 錯誤訊息對應：https://github.com/QuantumNous/new-api/blob/main/middleware/auth.go
- Hermes Agent：https://hermes-agent.nousresearch.com/docs/integrations/providers ；https://hermes-agent.nousresearch.com/docs/user-guide/features/fallback-providers ；https://hermes-agent.nousresearch.com/docs/user-guide/features/credential-pools
- 各家免費層：https://console.groq.com/docs/rate-limits ；https://developers.cloudflare.com/workers-ai/platform/pricing/ ；https://openrouter.ai/docs/api/reference/limits ；https://aistudio.google.com/docs/pricing ；https://docs.z.ai/guides/overview/pricing
- OmniRoute 漏洞：https://osv.dev/vulnerability/GHSA-hf57-cqmx-p4gr ；設定說明見已安裝套件的 `.env.example`（`OMNIROUTE_SERVER_HOST`、`REQUIRE_API_KEY`）
