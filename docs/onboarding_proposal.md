# OmniKeep 首次設定與個人化改版提案

日期：2026-11-04　狀態：已被 `docs/ai_engine_onboarding_survey_2026-11.md` 取代（起草改由使用者的 Claude／Codex／Antigravity 負責，新使用者沒有收藏資料可推）

## 0. 需要你決定的事

1. **方向**：首次設定改成「自動偵測 → 從你的資料起草 → 只問 3 到 5 題確認 → 預覽 → 馬上看到效果」，不再給空白表單。要採用嗎？
2. **讀取範圍**：預設只用 OmniKeep 裡已有的資料（收藏、標籤、星標、行為）和你匯入的書籤；掃描電腦資料夾做成選擇性，由你挑資料夾、先預覽會讀哪些檔。可以嗎？（理由見第 5 節）
3. **先做哪一段**：建議先做第一階段（第 6 節），也就是你剛才卡住的「不知道要填什麼」。

## 1. 問題

- 設定頁是一張欄位表：使用者背景、本機硬體都是空白文字框，一般人不知道該寫什麼。
- 硬體要手打，但程式本來就讀得到：這台是 20 核／28 執行緒的 CPU、64 GB RAM、16 GB 顯示卡。
- 有兩個重疊的「個人化」：
  - 雷達裡的興趣設定檔（`user_interest_profile`）。DreamPass 會依行為提出更新，但目前是空的。
  - 剛加的「使用者背景」（`USER_BACKGROUND`）。
  - 使用者分不清兩者差在哪裡。
- 要填一堆位址和模型名稱：例如 OpenAI 相容服務的 `/v1` 位址。
- 安裝步驟多：git clone、`bootstrap_env.py`、`npm ci`、`npm run build`、手動建 watchdog 排程。

## 2. 業界做法（2026-11-04 查證，來源見第 8 節）

| 面向 | 代表做法 | 可借用的 |
|---|---|---|
| 硬體偵測 | Jan 用 `sysinfo`、NVML 讀硬體，模型標「Fits／May be slow／Won't fit」[1][2]；llmfit 用 `nvidia-smi`，依記憶體用量分 Perfect、Good、Marginal、Too Tight [3]；AnythingLLM 全新安裝時依硬體建議本機模型 [4] | 偵測結果直接顯示成卡片，旁邊放「編輯」；估算要能覆寫並說明依據 |
| 不用空白框的個人化 | ChatGPT 特質用標籤多選 [5]；Claude 記憶從對話自動整理，可看、可改、可停 [6]；Claude 匯入是給一段 prompt 貼到別家 AI 再貼回來 [7] | 草稿先由系統產生，使用者只改；提供「從 ChatGPT／Claude 匯入」 |
| 冷啟動興趣 | Artifact 要先選 10 個主題，讀滿 25 篇才個人化 [8]；Perplexity 承認只靠主題選擇「quite limiting」[9]；Readwise Reader 靠匯入舊資料冷啟動 [10] | 主題選項從使用者自己的資料產生，不用通用清單；匯入就是最好的冷啟動 |
| 從既有資料推論 | Recall 依既有標籤結構自動上標籤，但使用者回報會漏標 [11] | 推論結果一定要看得到、改得了、刪得掉 |
| LLM 訪談 | `grill-me`／`grilling`：每題附建議答案，回 yes 就採用；查得到的事 agent 自己查，人只做決定 [12] | 短訪談、每題有預設答案；想更準再追問 |
| 掃描本機檔案 | Microsoft Recall：預設關閉、要 opt-in、本機處理、可排除、可暫停、可刪除 [13] | 資料夾掃描一律選擇性，先預覽 |
| 零設定安裝 | Open WebUI 第一個帳號就是擁有者，密鑰自動產生 [14]；n8n 首次啟動自動產生加密金鑰 [15]；AnythingLLM 裝在目前使用者、不需管理員權限 [16] | 安裝後自動開瀏覽器到一次性設定頁，密鑰全部自動產生 |

別人踩過的坑：
- 記憶體估算可能偏高一倍。LM Studio 估 22.92 GB，實際約 11.5 GB [17]，所以估算必須允許覆寫。
- 設定改了之後，相容標籤沒有跟著重算，結果卡住不更新 [18]。
- 只靠通用興趣標籤太粗 [9]。
- 自動推論不透明，使用者不信任 [11]。

## 3. OmniKeep 已經有、可以直接用的資料（這台實測）

| 資料 | 數量 | 用途 |
|---|---|---|
| 帶標籤的收藏 | 1311 筆，3834 種標籤 | 推斷工作領域與興趣 |
| 分類 | 17 個 | 推斷關注主題 |
| 主題權重（加強／減弱／封鎖） | 40 筆 | 你明確表達過的偏好 |
| 行為紀錄 | 85 筆 | 你實際看了什麼 |
| 星標 | 10 筆 | 最重要的訊號 |
| 本機 Ollama | qwen3:8b、embeddinggemma-2 | 起草全程在本機完成，不需要雲端金鑰 |
| 硬體 | CPU、核心數、RAM、GPU、VRAM | 全部可自動偵測（`psutil`、`nvidia-smi`） |

## 4. 建議：首次設定改成五步

```text
1 自動偵測（不問）→ 2 從資料起草（本機 AI）→ 3 短訪談 3–5 題（每題有建議答案）→ 4 預覽「我們對你的理解」→ 5 拿一筆收藏示範個人化前後
```

### 4.1 自動偵測，不問

- **硬體**：存成結構化欄位（CPU、核心、RAM、GPU、VRAM），不再是自由文字。設定頁顯示偵測結果，附「重新偵測」和「手動修正」。Docker 裡偵測不到 GPU 時會明說。
- **AI 服務**：
  - 偵測到本機 Ollama 和已下載的模型，就直接用「本機模式」，不需要任何金鑰。
  - 沒有 Ollama 時，用服務商卡片（OpenAI、DeepSeek、Gemini、OpenRouter…）。位址和建議模型自動帶入，只要貼金鑰。
- **密鑰類**：`API_KEY`、主金鑰、推播金鑰全部自動產生。推播金鑰已經做到，其他沿用同樣做法。
- **模型能不能跑**：依偵測到的 VRAM 和 RAM，給收藏裡的 AI 模型標「跑得動／會很慢／跑不動」，並列出估算依據。

### 4.2 從你的資料起草「關於你」

- **素材**：收藏的標籤和分類、星標、主題權重、最近的行為。新使用者沒有收藏時，第一步先請他匯入瀏覽器書籤；匯入功能已經有了。
- **起草**：本機 qwen3 只輸出固定格式的 JSON，例如工作領域、正在做的事、關注主題、想避開的主題、希望分析多深。後端驗證格式後才存，模型輸出亂了也不會把設定寫壞。
- **另一個捷徑**：「從 ChatGPT／Claude 匯入」。給一段 prompt，你貼到 ChatGPT 或 Claude 問，再把結果貼回來，跟 Claude 的匯入同一做法。

### 4.3 短訪談（3 到 5 題，每題有建議答案）

選項從你自己的資料產生，你只要點選或改一下：
1. 「看起來你主要關注 A、B、C，對嗎？」（標籤可增減）
2. 「你的工作比較接近哪一個？」（從資料推出 2 到 3 個候選，外加「其他」）
3. 「最近在做什麼專案？」（從最近的收藏推出候選）
4. 「分析要多深？」（重點摘要／技術細節／含落地建議）
5. 「有沒有不想再看到的主題？」（從你封鎖過的主題預選）

想更準可以按「再問深一點」，這時才進入 grill-me 式的追問。

### 4.4 兩個個人化合併成一個「關於你」

- 「使用者背景」和雷達的「興趣設定檔」合併，只留一個地方。
- DreamPass 繼續依你的行為提出更新，你按「套用」或「略過」。

### 4.5 預覽與第一次成功

- 存檔前顯示一頁「我們對你的理解」，每一項都能改、能刪。
- 存好後挑一筆收藏重新分析，並排顯示個人化前後的差別，讓你馬上看到效果。

### 4.6 安裝簡化（第二階段）

- 發行包內附建置好的前端，不需要 Node。
- 一支安裝腳本搞定：
  - 安裝 Python 依賴。
  - 自動產生所有密鑰。
  - 建立開機自動啟動。
  - 自動開瀏覽器到一次性設定連結，不用手動輸入存取金鑰。
- 設定頁改版：
  - 服務商用卡片選，不用填網址。
  - 間隔、併發這類參數收進「進階」。
  - 首頁顯示一張狀態卡：AI、向量、Bot、備份是否正常。

### 4.7 給 agent 的安裝路徑（第三階段）

- 提供 MCP 工具（例如 `setup_profile`）。Claude Code 或 Codex 安裝時，可以替使用者完成偵測和訪談，寫入時走同一套格式驗證，也就是 LLM 判斷、程式寫入。
- 等 OmniKit 的階段 2（掃描、短訪談、產生個人配置）完成後，OmniKeep 可以讀它的個人配置當初稿。這不是前提，OmniKeep 自己的流程不依賴它。

## 5. 為什麼不建議預設讀取電腦裡所有檔案

- **隱私與信任**：全機掃描會碰到合約、帳務、私人照片。業界做法都是預設關閉、由使用者選擇（Microsoft Recall [13]）。
- **訊號品質**：你收藏的東西本來就是「你在意什麼」最直接的訊號；硬碟裡大部分檔案和興趣無關。
- **架構限制**：OmniKeep 可能跑在 Docker 或另一台主機，伺服器看不到你的電腦。
- **折衷做法**：做成選擇性的「指定資料夾」。例如你的專案資料夾只讀檔名和 README，先列出會讀哪些檔，在本機處理，可以隨時刪除。

## 6. 分階段

| 階段 | 內容 | 解決什麼 |
|---|---|---|
| 1 | 硬體自動偵測（結構化）、合併兩個個人化、本機 AI 從收藏起草、3 到 5 題訪談、預覽、第一次成功；服務商卡片與本機模式自動判斷 | 你剛才遇到的「不知道要填什麼」 |
| 2 | 一鍵安裝包、一次性設定連結、設定頁視覺改版與狀態卡 | 整體安裝太繁雜 |
| 3 | 指定資料夾掃描、從 ChatGPT／Claude 匯入、agent 用的 `setup_profile`、讀取 OmniKit 個人配置、模型相容標籤 | 更準、更省事 |

## 7. 對照 OmniKit 提案

沿用 OmniKit `docs/proposals/2026-11-04-onboarding.md` 的原則：
- 掃描先做，只問掃不到的。
- 訪談不超過 6 題，選擇題為主。
- LLM 判斷，程式寫入。
- 先預覽再套用。
- 最後要讓使用者實際看到一次成功。

兩邊的使用體驗會一致。

## 8. 來源

1. https://raw.githubusercontent.com/janhq/jan/dev/src-tauri/plugins/tauri-plugin-hardware/Cargo.toml
2. https://docs.jan.ai/desktop/manage-models
3. https://github.com/AlexsJones/llmfit/blob/main/docs/how-it-works.md
4. https://docs.anythingllm.com/setup/llm-configuration/local/built-in （取自搜尋摘要，官方頁直接抓取回 403）
5. https://www.neowin.net/news/users-report-a-revamped-custom-instructions-interface-on-the-chatgpt-web-app/ （官方頁未取得，未查證）
6. https://support.claude.com/en/articles/11817273
7. https://claude.com/import-memory
8. https://www.inma.org/blogs/product-initiative-newsletter/post.cfm/there-is-still-a-lot-media-product-teams-can-learn-from-tech
9. reddit r/perplexity_ai AMA（1khwrqm）
10. https://docs.readwise.io/reader/docs/migrating-content
11. https://docs.recall.it/deep-dives/tagging
12. https://github.com/mattpocock/skills
13. https://support.microsoft.com/windows/d404f672-7647-41e5-886c-a3c59680af15
14. https://docs.openwebui.com/getting-started/quick-start/
15. https://docs.n8n.io/hosting/configuration/configuration-examples/encryption-key/
16. https://docs.useanything.com/installation-desktop/windows
17. https://github.com/lmstudio-ai/lms/issues/499
18. https://github.com/janhq/cortex.cpp/issues/1142
