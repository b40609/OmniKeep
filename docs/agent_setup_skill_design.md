# OmniKeep 設定 Skill 與 MCP 工具設計（草案）

日期：2026-11-04　狀態：流程與題目已定案（第 2、3 節），待實作

## 0. 目標

使用者對自己的 Claude Code、Codex 或 Antigravity 說「幫我安裝 OmniKeep」或「幫我設定 OmniKeep」，agent 從安裝一路帶到第一次成功。使用者只需要回答幾題、在 OmniKeep 頁面貼金鑰、按確認。

## 1. 原則（沿用 OmniKit 的 `omnikit-setup`）

- **先掃描**：掃得到的不問，只請使用者確認。
- **最多 6 題，以選擇題為主**。Claude Code 用選項按鈕（AskUserQuestion），Codex 和 Antigravity 列編號題。想更準可以說「再問深一點」。
- **LLM 判斷，程式寫入**：agent 只負責判斷，並把答案寫成 JSON。設定一律由 OmniKeep 依 schema 驗證後寫入，弱一點的模型也不會把設定改壞。
- **寫入前先預覽**，使用者同意才套用。
- **金鑰不經過聊天**：agent 打開 OmniKeep 的設定頁，請使用者自己貼，貼完再呼叫測試。金鑰貼在聊天裡會送到 agent 的模型服務商，也會留在對話紀錄。
- **不讀、不印金鑰**：掃描結果只有名稱、版本、狀態。
- **選項只說明，不替使用者決定**：各 AI 管道的優缺點講清楚，由使用者選（見 `docs/ai_provider_options_2026-11.md`）。

## 2. 流程（2026-11-04 定案：第 9 節方案一「先看到成果」）

原則：
- 接金鑰之前，先讓使用者看到為自己挑的內容。
- 分析深度、通知送到哪和幾點，等使用者看過結果才問。

理由與比較見第 9 節。

0. **安裝**（還沒裝 OmniKeep 時）：
   - 檢查 Python、Node、git。
   - clone、安裝依賴、建置前端、啟動。
   - Windows 上建立 watchdog 自動重啟。
   - 註冊 MCP 到三家 agent（見第 5 節）。
1. **掃描**：MCP 工具 `omnikeep_scan`（OmniKeep 還沒啟動時改跑 `python scripts/setup.py scan`）。結果包含：
   - CPU、RAM、GPU、VRAM。
   - OmniKeep 的版本與狀態，收藏數、雷達來源數。
   - 已接的 AI 管道和健康狀況。
   - 有沒有本機推論引擎。
   - 上次訪談的答案。
   - OmniKit profile 的語言與背景；有就不再問（見第 8 節）。
   - Chrome、Edge 書籤檔在不在、各幾筆；`gh` 有沒有登入、星標幾個。只看有沒有和筆數，不讀內容。
2. **起草**：agent 依掃描結果和自己對使用者的了解（記憶、對話、專案），起草：
   - 3 到 5 個關注主題。
   - 「關於你」。
3. **種子**（題 1）：
   - 貼了連結：每個連結呼叫 `omnikeep_peek`（不跑 AI、不存），agent 據此修正主題。連結留到第 7 步分析。
   - 選「從書籤或星標挑」：agent 只讀最近加入的 50 筆書籤的標題與資料夾名稱，或用 `gh api user/starred` 讀星標。只用來推興趣，不寫進 OmniKeep。
4. **主題包**（題 2）：
   - agent 依主題與種子提出候選來源：RSS、YouTube 頻道、GitHub 專案、Google News 關鍵字、網頁變動。
   - 交給 `omnikeep_check_sources` 驗證，只留抓得到的。
   - 分成 2 到 4 包，每包 3 到 5 個來源。每個來源列出：
     - 推薦理由：對應哪個主題或種子。
     - 最近一篇的日期、每週篇數。
     - 最近 3 篇的標題。
   - 驗證後湊不滿 2 包時，補上內建的 4 個範例來源當一包。
5. **接 AI 管道**（題 3）：已經有可用的就只確認。否則：
   - agent 說明申請步驟，並打開申請頁。
   - 需要金鑰時，呼叫 `omnikeep_open_settings` 取得指向該卡片的設定頁連結，請使用者自己貼。
   - 貼完呼叫 `omnikeep_test_provider`，實際送一筆小的中文 JSON 請求確認可用。
6. **第一次預覽與套用**：
   - 答案 JSON 交給 `omnikeep_preview_setup`，它做 schema 驗證，回傳設定差異。
   - agent 原樣給使用者看，問「照這樣設定嗎？」預覽內容：
     - 關於你、興趣設定檔。
     - 雷達來源。有勾主題包就開啟雷達，預設每 3 小時巡檢一次。
     - AI 管道，以及主要和備援的順序。
     - 通知先維持不送（`silent`），看完第一份雷達摘要再決定。
   - 同意後呼叫 `omnikeep_apply_setup`，帶上預覽時拿到的確認碼。
7. **第一次成功之一：分析**：
   - 用 `omnikeep_ingest` 分析種子連結（最多 3 篇），挑一篇把結果貼回來，接著問題 4（分析深度）。
   - 沒有種子時，先做第 8 步，再分析雷達摘要裡最相關的一篇，然後問題 4。
   - 沒有種子、也沒勾主題包時：請使用者給一個網址；沒有就分析一篇範例。
8. **第一次成功之二：雷達摘要**：
   - 用 `omnikeep_run_radar` 跑一次巡檢，產生第一份雷達摘要，把摘要貼回來。
   - 接著問題 5、題 6（送到哪、幾點）。
   - 選了 Telegram 或 LINE：agent 帶著建 Bot，金鑰照樣在設定頁貼；Telegram 綁定走配對連結。
   - 選了網頁推播：打開 OmniKeep，按「允許」。
   - 一包都沒勾時：跳過這一步和題 5、題 6，雷達維持關閉。
9. **第二次預覽與套用**：只改分析深度與通知，做法同第 6 步。
10. **收尾卡**：
    - 接了哪些 AI 管道、主要和備援的順序。
    - 追蹤幾包、幾個來源，巡檢間隔。
    - 雷達摘要送到哪、幾點，下一份什麼時候到。
    - 之後想改，直接跟 agent 說，Skill 只改那一項。例如：
      - 「多加幾個 X 的來源」。
      - 「摘要改到晚上」。
      - 「分析短一點」。
    - 想搬舊資料，說「匯入書籤」：
      - 可以搬 Chrome 與 Edge 書籤、GitHub 星標、Pocket 匯出檔、OPML。
      - 用 `omnikeep_import`，只存標題與網址，不跑 AI。
    - 每天滑卡一分鐘，推薦會越來越準。
    - Dreampass 累積夠多互動後，會提議更新興趣設定檔，使用者批准才改。

補充：
- **AI 用量**：首次設定最多約 7 次 AI 呼叫：
  - 種子 3 篇。
  - 首輪雷達分析 3 篇，沿用每輪上限 `max_analyze_per_cycle`。
  - 雷達摘要 1 次。

  就算用 Gemini 免費層 Flash（每日 20 次）也夠。
- **分析失敗時**（例如免費層限流）：照錯誤翻譯說明原因，改用備援管道或稍後重試，不要卡住後面的步驟。
- **重新設定、或 OmniKeep 已經有資料時**：每題預設帶入上次的答案；跳過種子與第一次成功，只改使用者想改的。

## 3. 訪談題目（2026-11-04 定案）

| # | 何時問 | 題目 | 選項 | 寫入 |
|---|---|---|---|---|
| 1 | 起草之後 | 我猜你最近在追 X、Y、Z。要更準的話，給我 1 到 3 個最近覺得有價值的連結 | 猜得對，直接用／我貼連結／從你的書籤或 GitHub 星標挑（掃描到才出現）／改一下（自由輸入） | 推興趣設定檔與分類的依據；連結留到第 7 步分析 |
| 2 | 候選來源驗證完 | 要追蹤哪幾包？（多選） | 2 到 4 個主題包，每包列出來源和最近的標題 | 雷達來源；有勾就開啟雷達 |
| 3 | 勾完主題包 | 分析要用哪些 AI 管道？（多選：主要加備援；掃描到可用的先勾好） | `docs/ai_provider_options_2026-11.md` 第 1 節的選項清單 | 要接的管道與順序 |
| 4 | 看完第一篇分析 | 這樣的分析可以嗎？ | 剛好／太長，精簡一點／要更多技術細節／要加落地建議 | 「設定 › 個人化 › 分析深度」（`ANALYSIS_DEPTH`）：剛好是不改；其餘依序對應 `concise`、`technical`、`actionable`。預設 `standard`，維持原本的寫法 |
| 5 | 看完第一份雷達摘要 | 雷達摘要要送到哪？（多選） | 網頁推播／Telegram／LINE／不用送，我自己打開看 | 要接的通知管道；「不用送」對應 `notification_mode` 的 `silent` |
| 6 | 同上 | 什麼時候送？ | 每天早上 8 點／中午 12 點／晚上 9 點／只送重要的 | `notification_mode`（`daily_digest` 或 `vip_alert`）與 `daily_digest_hour` |

補充：
- **「關於你」不另外問**：agent 依 OmniKit profile 和自己的記憶起草，在第一次預覽給使用者看，可以直接改。
- **提問方式**：
  - Claude Code 用 AskUserQuestion，題 5、題 6 一起問，其他各問一次。
  - Codex 和 Antigravity 列編號題，用編號回答。
- **題 2 最多 4 包**：剛好是 AskUserQuestion 每題的選項上限；Codex 和 Antigravity 列編號清單。
- **題 1 選「改一下」**：使用者的那句話取代 agent 的猜測。
- **題 3 選了會拿資料訓練的免費方案**：提醒一次（見 `docs/ai_provider_options_2026-11.md` 第 0 節）。
- **題 4 選「剛好」以外的**：第二次套用後，下一篇開始用新模板；想看效果，說「重新分析這篇」。
- **題 6 選每天幾點**：
  - 選定的小時起 3 小時內送出；電腦晚開機也會補送。
  - 內容是上一份每日摘要之後分析完成、還沒進過摘要的雷達項目，最多 20 篇。
- **題 6 選「只送重要的」**：分數到門檻（`vip_threshold`，預設 4.0）的項目才通知，不送每日摘要。

## 4. MCP 工具

| 工具 | 用途 | 會寫入嗎 |
|---|---|---|
| `omnikeep_scan` | 掃描硬體、狀態、已接管道、上次答案、OmniKit profile、書籤與 GitHub 星標的筆數 | 否 |
| `omnikeep_peek` | 抓取並解析一個網址，不跑 AI、不存，讓 agent 推興趣。Threads、YouTube 這類 agent 自己抓不到的，靠 OmniKeep 的解析器 | 否 |
| `omnikeep_check_sources` | 驗證候選雷達來源；給網站首頁就自動找 RSS。回傳最近一篇的日期、每週篇數、最近 3 篇標題 | 否 |
| `omnikeep_list_provider_options` | 回傳選項卡片：位址、建議模型、限額、申請連結、最後查證日 | 否 |
| `omnikeep_open_settings` | 回傳指向某張卡片的設定頁連結 | 否 |
| `omnikeep_test_provider` | 用已存的金鑰送一筆中文 JSON 小請求 | 否 |
| `omnikeep_preview_setup` | 驗證答案 JSON，回傳設定差異（含「關於你」與興趣設定檔），附確認碼；第二次預覽只含分析深度與通知 | 否 |
| `omnikeep_apply_setup` | 套用設定，必須帶預覽給的確認碼 | 是 |
| `omnikeep_ingest` | 分析一個網址，用來展示第一次成功 | 是（新增一筆收藏） |
| `omnikeep_run_radar` | 跑一次巡檢並產生雷達摘要，回傳摘要內容 | 是（雷達項目與摘要） |
| `omnikeep_import` | 匯入書籤檔、GitHub 星標清單、OPML（OPML 進雷達來源）；預設只存標題與網址 | 是 |

所有工具都不回傳金鑰，只回傳「已設定」和末四碼。

## 5. 安裝與散布

- OmniKeep repo 內附 `skills/omnikeep-setup/SKILL.md`。安裝腳本（或 agent 自己）把它複製到三家讀得到的位置：
  - Claude Code：`~/.claude/skills`。
  - Codex：`~/.agents/skills`。
  - Antigravity：文件寫的是 `~/.gemini/config/skills`，但 OmniKit 現在只裝在 `~/.agents/skills`，要實測 Antigravity 讀哪裡。
- 註冊 MCP 一律用 stdio。OmniKeep 的 MCP 程式自己讀存取金鑰，agent 的設定檔裡不用放任何金鑰：
  - Claude Code：`claude mcp add -s user omnikeep -- <python> <OmniKeep>\mcp_server.py`
  - Codex：`codex mcp add omnikeep -- <python> <OmniKeep>\mcp_server.py`
  - Antigravity：`agy mcp add`（語法要實測），或直接寫 `~/.gemini/config/mcp_config.json`。
- 進一步：做成三家的 plugin，從 GitHub 一行安裝，例如 `claude plugin marketplace add b40609/OmniKeep`、`agy plugin install https://github.com/b40609/OmniKeep`。這樣連「從零安裝」都能交給 agent。

## 6. 已決定（2026-11-04）

- **從零安裝也交給 agent**：GitHub 一行安裝，使用者不用動手；agent 做不到的步驟才引導使用者。
- **金鑰預設不在聊天裡貼**：引導到 OmniKeep 設定頁；使用者明確要求時才接受在聊天裡貼。
- **連接方式兩種都做，安裝時自動選**：同一台用 stdio，別台電腦用 HTTP（見第 7 節）。
- **OmniKeep 和 OmniKit 分開但互通**（見第 8 節）。
- **本機服務只讓使用者自己的電腦連**：綁 `127.0.0.1`；要從自己的其他裝置連，經 Tailscale，不對整個網路開放。
- **流程與題目採第 9 節方案一「先看到成果」**（細節見第 2、3 節）：
  - 題 1 種子、題 2 主題包、題 3 AI 管道。
  - 分析深度、送到哪、幾點，等看過第一篇分析和第一份雷達摘要才問，所以預覽套用分兩次。
  - 雷達來源由 agent 推、OmniKeep 驗證，內建 4 個範例來源當保底。
  - 掃描到的書籤與 GitHub 星標只當種子選項；完整搬家放在收尾卡。

## 7. stdio 和 HTTP 怎麼選

兩者都是 agent 和 OmniKeep 之間的連接方式：
- **stdio**：agent 自己啟動一個 OmniKeep 小程式，透過標準輸入輸出溝通。
- **HTTP**：agent 連到常駐的 OmniKeep 服務的網址。

實測（這台，2026-11-04）：OmniKeep 現有的 MCP 程式有 14 個工具，全部直接讀資料庫；用 stdio 每次啟動要 3 到 6 秒、佔約 131 MB 記憶體。

| | stdio | HTTP（Streamable HTTP） |
|---|---|---|
| agent 設定檔裡要放金鑰嗎 | 不用，小程式自己讀 | 要放 OmniKeep 的存取金鑰（明文），之後可改用 OAuth |
| 網路暴露 | 沒有 | 有一個網路端點；只綁本機就沒問題 |
| agent 在另一台電腦 | 不行，必須同一台 | 可以，例如筆電上的 agent 經 Tailscale 連這台伺服器 |
| 啟動成本 | 每個 agent 工作階段各開一個：實測 3 到 6 秒、約 131 MB | 沒有，共用常駐服務 |
| OmniKeep 服務沒開時 | 仍能查資料（直接讀資料庫） | 不能用 |
| 設定改了能不能立即生效 | 直接寫資料庫的話，常駐服務不會馬上知道，例如 Telegram 不會換新 Token，要另外通知 | 天然即時 |
| 三家 agent 支援 | 都支援 | 都支援 Streamable HTTP；Antigravity 不支援現在用的 SSE |

**建議：兩種都做，安裝時自動選。**
- **agent 和 OmniKeep 在同一台**：用 stdio。
  - 小程式讀資料直接讀資料庫；會改設定或新增收藏的工具，轉呼叫本機的 OmniKeep 服務，讓設定即時生效。金鑰由小程式自己讀，不寫進 agent 設定檔。
  - 改成用到才載入，把啟動時間壓到 1 秒內。
- **agent 在別台電腦**：用 HTTP（Streamable HTTP，取代已棄用的 SSE），帶 OmniKeep 的存取金鑰，經 Tailscale 連線。

## 8. OmniKeep 和 OmniKit 的關係

不是要合併。這裡只是讓 OmniKeep 的設定 Skill 沿用 OmniKit 的步驟與風格，兩邊體驗一致。

| 做法 | 優點 | 缺點 |
|---|---|---|
| 完全分開 | 最單純 | 兩邊重問同樣的問題，例如語言、背景 |
| **分開但互通（建議）** | OmniKit 可以把 OmniKeep 列成一個可選的工具包，勾選就由 agent 安裝；OmniKeep 設定時讀 OmniKit 的 profile（語言、背景），不再重問 | 兩邊要約定 profile 格式 |
| 合併成一個 repo | 一次安裝 | OmniKeep 是 24 小時跑的服務（資料庫、前端、Bot），OmniKit 是 agent 規則與技能管理，使用者、更新頻率、測試都不同；只想要其中一個的人得多裝一堆東西 |

## 9. 業界做法與方案比較（2026-11-04 查證）

**定案（2026-11-04）**：採方案一。另外三個細節都照建議：
- 分析深度與通知看完結果才問。
- 雷達來源由 agent 推、OmniKeep 驗證。
- 書籤與星標當種子選項。

已寫進第 2、3 節；本節保留查證與比較。

### 9.1 查了哪些產品

| 產品 | 首次使用怎麼做 | OmniKeep 可以借的 |
|---|---|---|
| Netflix [1] | 建帳號或新增設定檔時請你挑幾部喜歡的作品，用來起跑推薦；可以跳過，跳過就先給多元的熱門內容。之後實際觀看會蓋過初始選擇，近期行為權重較高 | 用具體作品冷啟動，不問抽象分類；初始答案不必準 |
| Spotify [2] | 新使用者先挑喜歡的歌手（2018 年官方文章寫 5 位以上），用來產生起始推薦；之後按愛心或隱藏再修正 | 同上 |
| TikTok [3] | 新使用者可選感興趣的類別；沒選就先給熱門影片，再依前幾支影片的互動修正 | 興趣題可跳過；早期互動比問卷重要 |
| Threads [4] | 設定時列出你在 Instagram 追蹤的帳號，可逐一或一鍵全部追蹤（第三方教學，非官方文件） | 從既有資料一鍵搬家 |
| Bluesky 入門包 [5][6] | 任何人都能做入門包：最多 150 個帳號加 3 個自訂動態，附分享連結與 QR code。研究顯示高峰期最多 43% 的追蹤來自入門包 | 把來源依主題打包，一次勾一整包；之後也能分享給同事 |
| Feedly [7][8] | 搜尋主題或你喜歡的來源，列出該主題的熱門來源；有產業來源包；依「常被一起讀」推薦相關來源 | 來源卡附熱門度與更新頻率；從一個來源推相關來源 |
| Inoreader [9] | 2014 年推出來源包（一鍵訂閱整組依主題推薦的來源）；官方在 2024 年停用（原因未公開） | 人工維護的內建來源包有維護成本 |
| Feeder AI 設定（beta）[10] | 用自己的話描述想追什麼，AI 找來源、建資料夾、加關鍵字監控；來源一個個出現在側欄，可邊建邊改；可丟 OPML 匯入；設定完聊天還在，之後繼續用聊天改。目前只開放給約一半的新註冊者 | 跟 OmniKeep 由 agent 帶設定最像：邊建邊讓使用者喊停，設定後同一個對話繼續改 |
| Readwise Reader [11][12] | 第一步是從 Pocket、Instapaper、Feedly 匯入；Pocket 關閉後改上傳匯出的 zip。Daily Review 可設寄送時間，也可設成不寄 | 匯入是主要入口；摘要時間可設、可關 |
| Duolingo [13] | 先上完第一課，才請你建帳號保存進度；再設每日目標（5、10、15 分鐘等）（第三方分析，非官方） | 先給價值，再要求付出 |
| Superhuman [14] | 新使用者必須先上一對一上手課：早期最長 90 分鐘（30 分鐘了解需求、60 分鐘帶操作），後來縮成 30 分鐘。做了五年之後，再花三年把這些做法搬進產品，改成全自助 | 專人帶的效果最好，先了解需求再帶操作；使用者的 agent 就是這個專人 |
| OpenClaw [15] | 第一次啟動跑 `BOOTSTRAP.md`：agent 跟你取名、定個性、選外掛組合，寫進 `IDENTITY.md`、`SOUL.md`；設定完自動刪掉，只跑一次；`--skip-bootstrap` 可跳過 | agent 帶的首次儀式；答案存檔、只跑一次、可跳過 |
| Hermes Agent | `hermes setup` 精靈；`hermes model` 依序選服務商、貼金鑰、選模型 | 已用在 AI 服務選項（見 `docs/ai_provider_options_2026-11.md`） |
| Apple 設計規範 [16] | 不要一啟動就要權限，除非沒有就不能用；在需要的情境才問 | 通知等使用者看過第一份雷達摘要再問 |

### 9.2 歸納出的規律

1. **冷啟動用具體東西，不用抽象分類，而且都能跳過**（Netflix、Spotify、TikTok）。
2. **初始答案不必準，之後由行為修正**（Netflix、TikTok）。OmniKeep 已經有對應的機制，所以首次設定不用問很多：
   - 每日滑卡：⭐👍 調升、👎 調降主題權重，14 天半衰期（`app/watch/taste.py`）。
   - Dreampass：依最近的互動提議修改興趣設定檔，使用者批准才改（`app/radar/dreampass.py`）。
3. **一次勾一整包，比一個個加快**（Bluesky、Threads、早期 Inoreader）；但內建包要有人維護，Inoreader 已經停用。
4. **先給價值再要求付出，權限在需要時才問**（Duolingo、Apple）。
5. **由專人或 AI 帶，邊建邊讓使用者調整，設定後同一個對話繼續改**（Superhuman、Feeder、OpenClaw）。

### 9.3 對照之下，原草案（定案前的第 2、3 節）的問題

- 第 1 題「想收哪些內容」是抽象分類：新使用者不好答，答了也推不出具體來源。
- 第 3 題「分析要多深」：還沒看過任何一篇分析就要選。
- 第 5 題「通知到哪」：還沒有任何東西可通知就要選，而且 Telegram、LINE 各要多花幾分鐘建 Bot。
- 走完之後第一天是空的：雷達預設關閉，4 個範例來源（Hacker News、arXiv AI、The Verge、FastAPI）也預設停用（`app/database.py:139`），「第一次成功」只有一篇分析。
- 接 AI 金鑰是最大的關卡（要離開聊天去申請、再回來貼），草案把它放在使用者看到任何價值之前。

### 9.4 三個方案

**方案一：先看到成果（建議）**

1. 掃描：除了原草案的項目，加上 OmniKit profile、agent 自己的記憶、Chrome 與 Edge 書籤的筆數、`gh` 是否已登入。只看有沒有和筆數，不讀內容。
2. agent 依掃描結果與自己的記憶，起草 3 到 5 個關注主題。
3. **題 1 種子**：「我猜你最近在追 X、Y、Z。要更準的話，給我 1 到 3 個最近覺得有價值的連結。」
   - 選項：猜得對，直接用／我貼連結／從你的書籤或 GitHub 星標挑（掃描到才出現）／改一下（自由輸入）。
4. agent 依主題與種子提出候選來源：RSS、YouTube 頻道、GitHub 專案、Google News 關鍵字、網頁變動。
   - OmniKeep 逐一驗證：抓得到、最近一篇的日期、每週篇數、最近 3 篇標題。
   - 只留驗證過的，分成 2 到 4 個主題包（像 Bluesky 入門包）。
5. **題 2 主題包**（多選）：每包列出來源和最近的標題。接 AI 之前，使用者就先看到為自己挑的內容。
6. **題 3 AI 管道**：掃描到可用的先勾好，已經有可用的就跳過。之後照第 2 節第 5 步：申請、在設定頁貼金鑰、測試。
7. 預覽，然後套用。內容包含：
   - 關於你、興趣設定檔。
   - 雷達來源、開啟雷達、巡檢間隔。
   - AI 管道。
8. **第一次成功之一**：分析種子連結。沒有種子的話，改分析第 9 步雷達摘要裡最相關的一篇。
   - **題 4 分析深度**（看完才問）：太長／剛好／要更多技術細節／要落地建議。
9. **第一次成功之二**：跑一次雷達，產生第一份雷達摘要。
   - **題 5 送到哪**（看完才問）：網頁推播（按允許就好）／Telegram（要先建 Bot）／LINE（要先建官方帳號）／不用送。
   - **題 6 幾點**：早上 8 點／中午 12 點／晚上 9 點／只送重要的。
10. 第二次預覽與套用，只改通知與分析深度，然後給收尾卡。收尾卡另外列出：
    - 想搬舊書籤，跟 agent 說「匯入書籤」。
    - 每天滑卡一分鐘，推薦會越來越準。
    - 想改來源或時間，直接跟 agent 說。

優點：
- 接金鑰前就看到價值。
- 收件匣第一天就有分析和雷達摘要。
- 題目固定 6 題。
- 來源由 OmniKeep 驗證，弱模型也不會推出不存在的來源。

缺點：
- 預覽套用分兩次。
- 新工具較多（見 9.6）。

**方案二：邊聊邊建（Feeder AI 設定、OpenClaw 式）**

1. 掃描。
2. agent 開放地問：「最近在追什麼？」
3. 邊聊邊把驗證過的來源一張張加進預覽，使用者隨時喊停或改。
4. 接 AI，預覽，套用，第一次成功。
5. 最後問送到哪、幾點。

固定題只有 AI 管道、送到哪、幾點三題，其餘是自由對話。

優點：
- 最自然、最貼身。
- 知道自己要什麼的人最快。

缺點：
- 三家 agent 的結果差異大，難重現。
- 不知道要說什麼的人會卡住，也就是調查文件第 2 節指出的「面對空白欄位」問題。
- 題數難控制，也比較花 token。

**方案三：搬家優先（Threads、Readwise 式）**

1. 掃描既有資料：Chrome、Edge 書籤，GitHub 星標，下載資料夾裡的 Pocket 匯出檔、OPML。
2. **題 1**：要搬哪些？選項附上筆數。
3. 匯入：預設只存標題與網址，不跑 AI。現有的 `/api/items/import/bookmarks` 預設就是這樣。
4. agent 從資料夾名稱、標題、星標推出興趣與來源。
5. **題 2**：勾選來源。
6. **題 3**：接 AI，分析最近 10 筆，示範用 Ask Brain 問自己的舊資料。
7. **題 4、題 5**：送到哪、幾點。

優點：
- Ask Brain 第一天就有內容可以問。
- 興趣來自真實行為，最準。

缺點：
- 要先讀個人檔案，需要使用者同意。
- 很多人的書籤是多年前存的，推出來的興趣會過時。
- 全部分析會吃光免費額度，例如 Gemini 免費層每日 20 次。
- 沒有舊資料的人用不上。

### 9.5 比較

| | 方案一 先看到成果 | 方案二 邊聊邊建 | 方案三 搬家優先 | 原草案 |
|---|---|---|---|---|
| 第一次看到價值 | 接金鑰前看到為你挑的來源；套用後馬上有分析與雷達摘要 | 同方案一 | 匯入後馬上有資料；分析要等接好 AI | 最後才有一篇分析 |
| 個人化準確度 | 高（agent 記憶加具體連結） | 高，但看 agent 能力 | 最高，但可能過時 | 低（抽象分類） |
| 題數、可重現 | 固定 6 題 | 不固定 | 固定 5 題 | 固定 6 題 |
| 弱模型容錯 | 高（題目固定、來源經驗證） | 低 | 中 | 高 |
| 要讀的個人資料 | 只有使用者選「從書籤挑」時才讀 | 少 | 多 | 少 |
| 免費額度用量 | 低（分析 1 到 3 篇加一份雷達摘要） | 低 | 高，除非只存標題 | 低 |
| 要新做的 | 來源驗證、跑一次雷達、第二次套用 | 同方案一，加上逐步更新預覽 | 匯入書籤、星標、OPML，加上來源驗證 | 最少 |

**建議**：用方案一當主線。
- 方案三的匯入，變成題 1 的一個選項（掃描到才出現），完整搬家放在收尾卡。
- 方案二的「設定完用同一個對話繼續改」，當成收尾後的用法。

### 9.6 方案一要新增的 MCP 工具

已併入第 4 節的工具表：`omnikeep_peek`、`omnikeep_check_sources`、`omnikeep_run_radar`、`omnikeep_import`。

### 9.7 來源

1. https://help.netflix.com/en/node/100639
2. https://newsroom.spotify.com/tag/taste-onboarding/
3. https://newsroom.tiktok.com/en-us/how-tiktok-recommends-videos-for-you/
4. https://www.neowin.net/guides/you-can-pre-follow-instagram-users-on-threads-heres-how/ （第三方）
5. https://bsky.social/about/blog/06-26-2024-starter-packs
6. https://www.lancaster.ac.uk/news/starter-packs-have-played-a-central-role-in-blueskys-rapid-growth-new-study-shows
7. https://docs.feedly.com/article/768-follow-sources-in-feedly
8. https://feedly.com/new-features/posts/new-ai-driven-discovery-experience （2019 年 Feedly Lab）
9. https://www.inoreader.com/blog/2014/10/bundles-collect-share-and-discover-best.html （文首註明 2024 年停用）
10. https://feeder.co/product/ai-onboarding
11. https://docs.readwise.io/reader/docs/migrating-content
12. https://help.readwise.io/article/75-can-i-turn-off-daily-review-emails-and-still-get-ios-notifications
13. https://goodux.appcues.com/blog/duolingo-user-onboarding （第三方）
14. https://review.firstround.com/superhuman-onboarding-playbook/
15. https://docs.openclaw.ai/start/bootstrapping
16. https://developer.apple.com/design/human-interface-guidelines/privacy

## 10. 實作前要處理或實測的

流程與題目已定案（第 2、3 節），沒有待決定的項目。

讀現有程式時發現四個缺口，2026-11-05 已在分支 `fix/radar-notify-20261105` 修好（`66ec681`、`ac3d625`），還沒部署到正式機：

1. **每日摘要改成到點就送**：
   - 原本只有在巡檢剛好跑在 `daily_digest_hour` 那個小時、而且那一輪的新項目至少 2 筆時，才會產生摘要。巡檢每 3 小時一次，可能一直碰不到。
   - 現在排程每分鐘檢查一次，從選定的小時起 3 小時內送出。
   - 內容是上一份每日摘要之後分析完成、還沒進過摘要的雷達項目，最多 20 篇。
2. **LINE 收得到雷達通知**：雷達摘要、重要項目、自動收藏都會送，跟 Telegram、網頁推播一樣；沒設定 LINE 時不送。
3. **「只送重要的」（`vip_alert`）**：改成分數到門檻就送。原本還要求同時被自動收藏，關掉自動收藏時就永遠不會通知。
4. **新增「設定 › 個人化 › 分析深度」**（`ANALYSIS_DEPTH`）：
   - 選項：標準、重點摘要、技術細節、含落地建議。
   - 預設是標準，提示內容跟原本完全一樣。

還要處理的：

5. **「關於你」與興趣設定檔是兩個欄位**（`USER_BACKGROUND`、`user_interest_profile`）：合併排在第二階段；第一階段預覽兩處都寫。
6. **要實測的**：
   - Chrome、Edge 書籤檔在各設定檔（Default、Profile 1 等）的位置。
   - `gh api user/starred` 在沒登入時的回應。
   - 題 2 主題包在三家 agent 的呈現效果。
   - 首輪巡檢加分析要多久，決定 agent 等待時怎麼說明。
7. **之後可做**：讓使用者把自己的雷達來源匯出成主題包（OPML 或連結）分享給同事，像 Bluesky 入門包。
