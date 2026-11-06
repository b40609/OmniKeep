# OmniKeep 下一步討論（2026-11-06）

依據：
- 2026-10-25 的競品調查 `docs/competitive_survey_2026-10-25.md`。
- 這次補查的 10-25 到 11-06 競品動態，查的是 GitHub release 與官方 changelog。
- 對照 10-25 調查的缺口清單，查程式現況（逐項附 file:line）。
- 這次免費管道工作裡實際碰到的問題。

## 1. 免費模型會自動建議給新用戶嗎？

**會列出來，但不會被推薦，也不會預先勾選。**
- 新卡片放在 `app/provider_catalog.py`。首次設定精靈、設定頁，以及使用者 agent 用的 `omnikeep_list_provider_options`（Skill 第 5 節「題 3：AI 管道」），都直接讀這份目錄，所以新卡片已經自動出現在這三個地方。
- 依 2026-11-04 定的原則「只列選項，不替使用者決定」，卡片沒有預設值或推薦標記。測試 `test_catalog_lists_options_without_a_default_or_subscription_routes` 也會擋這件事。

**新用戶的缺口**
- 新用戶沒有任何金鑰時，每一張卡片都要先去註冊。Kilo 和 OVHcloud 其實不用註冊就能用，但 Skill 的「掃描到可用的先勾好」只看本機 Ollama，不認得這兩家。
- 可以讓它們以「不用註冊、現在就能試」的身分出現，讓新用戶第一分鐘就看到分析結果，呼應已定案的「先看到成果」流程。
- 這算不算「替使用者預設答案」，要你決定。

## 2. 跟業界相似專案的差距

### 已經補上的（10-25 調查之後）
- **入口安全**：全域預設拒絕、CORS、測試資料庫隔離（`app/security.py:27`）。
- **混合搜尋**：FTS 加向量，用 RRF 合併；Ask Brain 會回傳引用（`app/brain.py:94`）。
- **成本**：雷達先用本地預篩，每輪只深度分析前 3 名（`app/radar/scheduler.py:66`）。
- **去重**：雷達去重加了向量相似度（`app/radar/clustering.py:64`）。
- **其他**：推薦理由、匯出、備份還原演練、HTML 快照、規則引擎、Web Push、書籤匯入。
- **SSRF 防護**：只連公開位址，DNS 和重新導向都檢查（`app/network.py`），已經不輸 Karakeep 和 Open Notebook 這期的加固。

### 還沒補的

依我判斷的價值排序：

| 缺口 | 誰有 | OmniKeep 現況 | 工作量 |
|---|---|---|---|
| **中文搜尋** | 中文使用者的基本需求 | FTS 仍是 `unicode61`（`app/database.py:93`），中文不分詞，搜詞容易漏 | 小：這台的 SQLite 3.50.4 內建 FTS5 `trigram` 分詞器，已實測中文子字串能命中；要重建索引 |
| **證據標記** | Readwise（逐字稿時間戳、段落引用）、Pi-tree | YouTube 抓不到內容時，只用標題和說明欄分析，但沒有標示「只看了標題」（`app/pipeline.py:322`）；L2 沒有來源段落，引用只到整篇 | 中 |
| **各連線的用量與額度** | Hermes v0.23 的花費上限、CondenseIt 的預算頁 | 沒有 LLM 用量統計；免費管道有一次性或每月額度（Inception 100M、Itera 30M），用完才知道 | 中 |
| **排序品質驗證** | CondenseIt | 沒有離線評估集，也沒有「不相關原因」回饋 | 中 |
| **瀏覽器擴充** | Karakeep、Linkwarden | 只有書籤小工具 | 中 |
| **更多內容類型** | SurfSense（電子書、Instagram、Reddit）、Readwise（Podcast 逐字稿）、Open Notebook（文件上傳） | 沒有電子書、Podcast、文件上傳 | 中到大 |
| **專案監看接 OSV、Trivy** | 這是 OmniKeep 自己的差異化賭注 | 沒做，仍是檔名加指紋（`app/watch/scanner.py`） | 中 |
| **把內容交給 agent 處理** | Prismis v0.3.12 的 `prismis-cli open` | 有 MCP，但卡片上沒有「交給 agent」的動作 | 小 |
| **PWA 離線寫入佇列** | Folo 1.17 | 沒有 | 中 |

### OmniKeep 的獨有優勢（這期查的專案都沒有）
- 專案監看。
- 雷達、收藏、問答整合在一台機器上。
- Dream Pass 從使用者互動自動提議更新興趣設定檔。
- Telegram、LINE 雙向回饋。
- 首次設定由使用者自己的 agent 帶著做。
- 服務商卡片、用途分槽、自動備援。

## 3. 下一步方向（四選一）

| 方案 | 內容 | 理由 |
|---|---|---|
| **A（建議）：可信又好找** | 中文 trigram 搜尋；YouTube 等只看了標題的內容標「只看標題」；各連線的用量與額度顯示 | 都打在每天用得到的核心體驗；中文搜尋工作量最小、效果最直接 |
| B：收集端 | 瀏覽器擴充；電子書、Podcast、文件上傳 | 對齊 Karakeep 和 SurfSense，但收藏基礎建設是別人的主場 |
| C：專案監看差異化 | 接 OSV；提案附 repo 元件證據；排序離線評估 | 強化 OmniKeep 獨有的賭注，但要先有評估資料 |
| D：原定的第二階段 | OmniKeep 代管 `llama-server`；Vertex 用 Google AI Pro 抵免額；OmniKit 互通 | 已在 2026-11-04 的計畫裡；有了免費管道之後，急迫性降低 |

## 4. 小缺口

| # | 問題 | 證據 | 建議 |
|---|---|---|---|
| 1 | **Bug：舊設定搬移時，把 OpenAI 相容連線硬塞進「向量」備援** | `app/ai_connections.py` 的 `migrate_legacy` 會把 legacy 的 openai 連線加進向量用途，模型填 `text-embedding-3-small`，不檢查卡片支不支援向量；你的 Agnes 就被放進去了，但它沒有向量。本機 Ollama 沒開時，向量就會失敗 | 搬移時檢查卡片的 `caps.embeddings`；把 Agnes 從你的向量用途移掉 |
| 2 | 依賴檢查的測試在這台會失敗 | `tests/test_optional_dependencies.py:37` 只排除 `frontend` 和 `static`，所以會掃到未追蹤的 `.agents`、`_bmad` 等工具資料夾 | 擴充排除清單 |
| 3 | 設定頁不能改額外請求參數 | `extra_body` 只能靠卡片預設；同一條連線換模型時，沒辦法帶不同參數（NVIDIA 的 DeepSeek 需要） | 進階欄位，或改成依模型設定 |
| 4 | 設定頁只顯示第一張卡片的查證日期 | `AiProvidersPanel.vue:380` 讀 `cards[0].verified`；現在每張卡片的日期不同 | 改成每張卡片各自顯示 |
| 5 | 新用戶沒有零設定的 AI | 見第 1 節 | 讓 Kilo 和 OVHcloud 以「不用註冊」的身分出現（要你決定） |
| 6 | Itera 卡片的免費活動 11-24 結束 | 卡片的 cost 欄位 | 到期前確認；每週比對也會提醒 |
| 7 | 測試連線的名稱都有「免費測試-」前綴 | 你的設定頁 | 改成正式名稱 |
| 8 | 每週排程第一次跑可能卡在權限 | 排程沒有繼承這個對話的權限模式 | 到側邊欄的 Scheduled 打開任務按「Run now」核准一次 |
| 9 | （本機事項，不列在公開文件） | — | — |
| 10 | 6 份規劃文件沒進 git | `docs/` 底下未追蹤的檔案 | 先檢查有沒有個資，再決定 commit 或刪除 |
| 11 | 向量檢索的測試在缺 sqlite-vec 時會整組跳過 | `tests/test_b_full_features.py:75` | CI 環境裡缺 sqlite-vec 就直接判失敗 |
| 12 | 這次的部署流程沒照守則 | 交接文件規定「正式機的工作目錄不直接改程式、先備份再部署」；這次我直接在正式機改程式並重啟，沒有先備份 | 已記入記憶，下次改在 worktree 做；這次的回滾點是 `533a5f0` |

## 5. 來源

- 競品 release 與 changelog：
  - Karakeep：https://github.com/karakeep-app/karakeep/releases/tag/v0.34.1
  - Folo：https://github.com/RSSNext/Folo/releases/tag/desktop/v1.17.0
  - SurfSense：https://github.com/MODSetter/SurfSense/releases/tag/v2.3.0
  - Readwise：https://docs.readwise.io/changelog
  - Prismis：https://github.com/nickpending/prismis/releases
  - Open Notebook：https://github.com/lfnovo/open-notebook/releases/tag/v1.15.1
  - Hermes Agent：https://github.com/NousResearch/hermes-agent/releases/tag/v0.23.0
  - Khoj：https://github.com/khoj-ai/khoj/releases/tag/2.0.0-beta.28
- 新冒出的相近專案：https://github.com/itechmeat/open-second-brain （511 星，給 Hermes 用的 Obsidian 記憶層，有夜間 dream pass 和 MCP）
- SQLite FTS5 trigram 分詞器：https://www.sqlite.org/fts5.html#the_trigram_tokenizer
