# OmniKeep 競品與替代解法深度調查

**調查日期：2026-10-25（Asia/Taipei）**  
**範圍：自託管收藏、AI 情報雷達、個人化學習、知識檢索、專案感知提案、可信任的自動化。**

> 判讀標準：「已有同類解法」代表功能設計有公開依據；不代表驗證過效能、準確率或維運品質。GitHub Star／最後推送日由 `gh api repos/{owner}/{repo}` 於調查日查得，僅作社群成熟度線索。商業產品資料來自官方功能文件。未逐一安裝或執行所有競品，也未實測其品質。

## 1. OmniKeep 的真正定位

依照目前的 `README.md`、`docs/watch_proposals.md` 與實際程式：

1. **收集**：iOS Shortcut、PWA／Web、Telegram／LINE、MCP、URL／文字；背景 Radar 支援 RSS、YouTube、GitHub。
2. **解讀**：網頁擷取／Gemini 影片理解；每筆產出 L1 速覽與 L2 深入分析，並儲存原文；可從彙整型內容拆出獨立提及的專案。
3. **挑選**：來源權重與使用者滑卡反饋修改技術標籤權重（14 天半衰期）；排名加入約 20% 探索項。
4. **關聯**：本機 Watch Target 讀專案結構／README／依賴／可選原始碼及 git；生成指紋，以新雷達情報和監看目標匹配產生提案；使用者可核准、忽略和修正分數。
5. **取回**：SQLite FTS5 搜尋、卡片閱讀器、摘要、備份和跨端訊息介面。

最有價值的方向是 **「外界的新情報 → 我的實際工作／專案 → 有證據、可審核的下一步」**。純收藏、RSS 摘要、AI 標籤、第二大腦、滑卡學習都已有多套替代方案。專案感知提案與權限分離值得保留，但其準確率仍待驗證。

## 2. 高度相似作品（按解題相似度，不按 Star）

| 專案與證據 | Star／最後推送（2026-10-25） | 已公開的較完整解法 | OmniKeep 值得借的部分／限制 |
|---|---:|---|---|
| [CondenseIt](https://github.com/wildlifechorus/condenseit) | 91／10-20 | RSS、YouTube、網站差異、HN、Reddit、GitHub Releases、Podcast；顯式星評及隱式閱讀反饋；TF-IDF、片語、來源、主題、embedding、可選 LLM rerank；「Why ranked here?」可拆解排名；管理頁支援排程、預算與冷啟動偏好 | **最值得拆解排名層**；其完整功能來自 README 宣稱，仍需實測排序效果。MIT |
| [Prismis](https://github.com/nickpending/prismis) | 14／10-23 | context.md 明確描述個人關切，按 HIGH/MEDIUM/LOW 評等，重要項再做深入綜述；錯過的高價值內容可回報、再建議修正 context；本地 SQLite、CLI／TUI／Web | **比每個技術 tag 加權更貼近語意意圖**；亦保留人能理解／修改的設定。MIT，早期產品 |
| [Cruxwire](https://github.com/philoking/cruxwire) | 13／06-28 | 本地 Ollama、來源無關的語意事件去重、read/later/history 同步、來源偏好、embedding 品味與防訊息洪水的保留機制 | **可學跨來源事件合併與收件匣容量控制**；近期維護訊號較弱。MIT |
| [Brain](https://github.com/mstick3/brain) | 2／07-25 | YouTube／podcast／論文／RSS→Markdown；候選先按興趣批次評分；每日上限；局部 embedding 搜尋、來源引用；依照個人專案提出 idea、早晨摘要、週回顧 | **方向最貼近「資訊與專案產生聯動」**，但 Star 極少、活動停在 7 月，適合研究架構而非直接採用。MIT |
| [BrewMe](https://github.com/xiaojiou176-open/BrewMe) | 2／06-04 | RSS、YouTube、Bilibili、RSSHub，來源導向 reader、CLI／MCP／SDK、版本化契約與 evals | **參考來源可追溯、對外工具契約與品質評估**；早期作品。MIT |
| [ReadEverything](https://github.com/berleary/read-everything) | 0／06-17 | FastAPI、SQLite、不同內容各有專用 fetcher，先正規化再做摘要與 digest | **多來源單一 schema 造成語意流失的問題**；作者說明這是展示架構的 portfolio，非即裝即用產品，授權未明 |
| [Pi-tree](https://github.com/shuowu/pi-tree) | 10／10-19 | 影片／論文／書籍／RSS、引用源片段的對話式閱讀、分支對話、跨資料概念網路、從閱讀紀錄解釋推薦理由、session-scoped 工具權限 | **從「讀完摘要」改成「可追問來源及脈絡」**；AGPL-3.0，實作與交互方式更重 |
| [Second Brain](https://github.com/ZenekeZene/second-brain) | 8／10-25 | Telegram 收集、晚間整理為相互連結的 wiki、定期 lint／健康檢查、孤兒或重複知識發現、回顧 | **知識庫需要保養、重浮現與交叉連結**；小型個人作品，不能當作成熟產品。MIT |

## 3. 成熟的相鄰產品：哪些輪子應該直接借用觀念

| 產品／官方資料 | 相近層 | 已具備的代表能力 | 對 OmniKeep 的啟示 |
|---|---|---|---|
| [Karakeep](https://docs.karakeep.app/)／[repo](https://github.com/karakeep-app/karakeep)（29,964★，10-25 有推送） | 收藏、抓取、搜尋 | 瀏覽器擴充、iOS／Android、全文＋語意搜尋、影像 OCR、AI 標籤／摘要、規則引擎、整頁封存、批次作業、RSS 自動收錄 | **收藏基礎建設已非常成熟**；不是值得繼續發明差異化的主戰場。AGPL-3.0 |
| [Linkwarden](https://github.com/linkwarden/linkwarden)（20,201★，10-24） | 原文保存 | 可讀 HTML、單檔網頁、截圖與 PDF 多形式保存，標註、協作、App／延伸套件 | 網頁內容必須能抗 link rot，原始 HTML、時間與變動史須追溯。AGPL-3.0 |
| [Readeck](https://readeck.org/) | 深度閱讀 | 離線可讀內容、重點標註、動態 collection、文章呈現與閱讀流程 | 閱讀器真正價值是閱讀、標註、重訪，不只是 L2 Markdown 很長 |
| [Folo](https://github.com/RSSNext/Folo)（39,168★，10-24） | 訂閱／訊息流 | 多平台 RSS、影片／Podcast／社交來源、每日總覽、摘要翻譯、AI Tasks、OPML、newsletter inbox、對外整合 | **多來源整合體驗與跨端成熟度**遠高於小型自架 RSS 系統；AGPL-3.0 |
| [Readwise Reader](https://docs.readwise.io/reader/docs)／[Global Ghostreader](https://docs.readwise.io/reader/guides/ghostreader/global) | 影片閱讀、跨庫研究 | YouTube 同步逐字稿與跳轉、highlight、讀書筆記、跨收藏庫問答和段落級引用 | L2 必須能回到影片秒數／原文段落；只輸出 AI 分析不足以建立信任 |
| [Khoj](https://github.com/khoj-ai/khoj)（37,815★，08-02） | 第二大腦、RAG | 個人文件／網站問答、語意檢索、自訂 Agent、排程研究與通知、自託管 | 查舊資料的能力可直接參考 RAG 的檢索與引用策略。AGPL-3.0 |
| [SurfSense](https://github.com/MODSetter/SurfSense)（16,602★，10-25） | 多來源知識與研究 | 多來源 connector、Hybrid search、引用式問答、MCP、可排程 Agent、模型彈性、自託管 | **多資料型態的擷取、檢索、引用層**有現成的系統性方案；Apache-2.0，但授權不代表所有其依賴無限制 |
| [Feedly AI](https://feedly.com/ai) | 專業情報分析 | 大規模來源觀測、公司／事件／主題追蹤和情報優先化 | 產品中心可以是「議題／目標」，而非無止盡的個別文章 |
| [agents-radar](https://github.com/duanyytop/agents-radar)（1,141★，10-25） | 技術雷達 | GitHub Trending、HN、Product Hunt、ArXiv、HF、官方網站 sitemap，定時彙整與雙語 Markdown | 可把開源生態追蹤拆成廉價來源擷取，避免所有類別都做深度 AI 解析。MIT |
| [changedetection.io](https://github.com/dgtlmoon/changedetection.io)（35,281★，10-25） | 網站／版本觀測 | 網頁、DOM 區塊、JSON、PDF、瀏覽器步驟、差異通知 | 非 RSS 資源的可靠追蹤可以借成熟的差異偵測概念。Apache-2.0 |

### 安全與專案維護需參考的「專業元件」

- [OSV-Scanner](https://google.github.io/osv-scanner/usage/scan-source)：掃 lockfile／SBOM 找已知漏洞，比推測性的 AI 依賴風險提示更有可驗證依據。
- [Trivy](https://trivy.dev/docs/latest/target/filesystem/)：檔案系統漏洞、組態、機密與授權掃描，可取代只看危險檔名的粗略 L0。
- [OpenSSF Scorecard](https://scorecard.dev/)：外部開源專案的安全實務指標。
- [Renovate](https://docs.renovatebot.com/)：依賴版本變更、提案與更新自動化；OmniKeep 更適合作為其上層「為何值得升級」判斷器。

## 4. 從 OmniKeep 實碼看到的主要差距

| 優先 | 現況證據 | 缺口與技術後果 | 對照更完整的設計 |
|---|---|---|---|
| **P0** | `app/config.py:12` 預設固定 API key；`app/main.py:70-92` CORS `*` 且中介層只攔 `/mcp`；`app/routers/ingest.py:17-31` 定義 `verify_api_key()` 卻沒有用 `Depends` 掛到 ingest 路由；多個寫入／刪除 API 也沒有路由層驗證；`AUDIT_HANDOFF_GPT61.md` 記載 tunnel 與測試曾寫入 live DB | **靜態程式碼顯示 `/api/ingest` 等 API 缺少應用層認證**。若外網能連到 `/api`，可能被未授權讀寫；須先確認實際 reverse proxy／tunnel 存取政策。本調查未對外網進行存取測試，也無法宣稱實際已遭暴露 | API 預設拒絕、細分讀寫權限、測試 DB 隔離、限制公開範圍、稽核日誌 |
| **P1** | `app/pipeline.py:107-136`：Gemini 看完整影片；失敗或無 Gemini 時僅用影片標題、頻道、URL 問其他 LLM | metadata-only 可能得到看似完整、實則無影片證據的 L2；`deep_analysis` 目前無來源段落級定位 | Readwise 的 timestamp transcript、Pi-tree 的 source evidence |
| **P1** | `app/watch/taste.py`、`app/radar/recommender.py`：分類、AI tags 權重與 14 天衰減；探索項取排序尾部，固定 4:1 插入 | 這是**決定性尾段穿插**，並非真正隨機的 ε-greedy；技術 tag 拼寫不一致會影響信號，沒有個人／專案意圖向量 | CondenseIt 多信號、embedding、冷啟動與「Why ranked here?」；Prismis 的 context.md |
| **P1** | `app/radar/clustering.py`：48h 內標題字詞 Jaccard >0.35，事件來源數單純 +1 | 同一事件跨語言／不同標題容易漏合併；同來源反覆更新可能膨脹來源統計 | Cruxwire semantic clustering，利用 URL canonical、實體、時間與相似度 |
| **P1** | `app/watch/relevance.py`：以技術標籤與目標指紋重疊作 coarse gate，雲端模型可再評論；每篇最多一項提案 | 未足以分辨「技術上相關」與「**對某 repo 某個元件有具體收益**」；提案缺檔案／版本／來源證據鏈 | Brain project-linked ideas＋OSV、Renovate 與差異偵測帶來可核實資料 |
| **P1** | `app/radar/scheduler.py:64-90`：新來源逐筆呼叫完整 `run_pipeline()` 才算排序與風險阻擋 | 成本決策太晚；低品質或重複項已花抽取／LLM 開銷；失敗處理與佇列背壓還薄弱 | Brain 每日攝取上限、CondenseIt 預算頁；二階段 cheap filter → expensive deep dive |
| **P2** | `app/database.py`／README：SQLite Unicode61 FTS5；`app/pipeline.py` 分離 L1/L2 原文 | 中文分詞與跨篇語意搜尋弱；尚欠可引用的 chat-with-library、跨內容對比 | Khoj、SurfSense hybrid retrieval、Reader Global Ghostreader |
| **P2** | `README.md` 的 UI 遷移與來源支援；`app/parsers/web.py` 使用文字擷取 | 現有 reader/文字不等於長期可重現原頁；網站關閉或重新編輯後難以驗證 AI 說法 | Karakeep、Linkwarden 的多格式 archive |
| **P2** | `app/watch/scanner.py` 本機檔名 L0＋指紋；`redact.py` regex-based masking | L0 不是實際安全漏洞掃描，遮蔽模式不是所有機密都能保證擋下；需要清楚標示能力邊界 | Trivy／OSV 等結構化結果，雲端最小揭露與審計 |

**現有優勢也需保留**：兩軸讀取／外送權限、外送遮蔽、提案批准／駁回與人工修正、Telegram 快速回饋、可自由選擇模型、原文與分析分層、單機 SQLite／自託管。這些比再多一個摘要按鈕更能支撐使用者信任。

## 5. 建議的目標架構（刻意保持單機簡潔）

```text
External Sources / Manual Save / Watched Repo
    │
    ├─ 1. Source adapters → canonical URL / source fingerprint / metadata
    │                     → cheap quality filter + budget gate + dedup
    ├─ 2. Evidence capture → snapshot + timestamp/quote span + provenance
    │                     → selective L1/L2 + verifier / failure status
    ├─ 3. Knowledge index → SQLite FTS + local embeddings + hybrid rerank
    │                     → entity / topic / source links
    ├─ 4. Project profiles → manifest / README / architecture / recent diffs
    │                     → dependency evidence / project priorities
    ├─ 5. Decision engine → interest match + project impact + source trust
    │                     → explanation / cost / confidence / next action
    └─ 6. Review loop → Telegram & PWA deck → approved/dismissed/corrected
                          → calibration / evaluation / digest / resurface
```

分離 **source evidence**、**model inference**、**user judgment** 是核心：讓使用者知道原文說了什麼、OmniKeep 推斷了什麼、最後要做什麼。提案可以提出程式檔或相依版本的具體定位，但應先保持 read-only 提案；程式變更另走既有授權與驗證流程。

## 6. 以「不重做全部」為原則的優先開發清單

| 順序 | 小範圍交付 | 驗收條件（實際可量測） |
|---|---|---|
| 0 | **入口與資料庫安全地基**：為 `/api` 路由加入真正執行的權限依賴或全面中介層；取消固定預設憑證、確認 tunnel 存取控制、隔離測試 DB；建立現有系統 smoke baseline | 在無憑證／錯誤憑證下 `/api/ingest`、`/api/watch`、刪除／更新 API 必須拒絕；測試絕不產生 live DB 新列；原有功能可用 |
| 1 | **有證據的情報卡**：處理 YouTube fallback 時明確降級為 `metadata_only`；在可用情況保存逐字稿時間戳或頁面段落來源；L2 重要主張附可點返回的 source span | 隨機抽 30 筆：每筆 L2 核心主張能跳回內容或明確標示「缺原文」；來源與模型推斷不混淆 |
| 2 | **排序競賽先做離線評估**：從歷史使用行為收集盲測集；比較現有 tag baseline、文字 TF-IDF、local embeddings、LLM rerank 的 top-k 精確率 | 先固定 50–100 則人工標註資料；Precision@10、誤推率、成本／100 筆有具體數字，盲測後再決定替換 |
| 3 | **Why this matters 卡片**：顯示技術關鍵詞、我的目標、共同文件／依賴、來源、推薦理由；提供「不相關原因」回饋 | 每張提案可說清「對哪個 repo 的哪個部分」；缺證據降分或不出卡；人工可糾正模型 |
| 4 | **來源去重與成本先閘門**：URL canonical + 相似度聚類 + 每來源限額；先廉價過濾，再選項呼叫 LLM | 相同事件多來源收斂、保留引用來源；LLM 費用與每日總量可計算，重要內容召回率不低於基準 |
| 5 | **Hybrid retrieval**：SQLite FTS（中文前處理）+ 本地 embedding + RRF／rerank + 帶引用跨篇問答 | 30 個中英混合問題：引用有原文，且人工比較純 FTS 的 top-5 召回改善 |
| 6 | **專案監看導入專業安全資料**：先串 OSV／Trivy JSON 報告，依相依及檔案確證提示 | 正確顯示受影響依賴、版本、問題來源；未知情況不得說成已確認漏洞 |
| 7 | **收集與長期可用性**：瀏覽器擴充／Share extension、可讀原文 archive、Markdown/JSON 匯出、backup restore drill | 任一筆可匯出來源＋摘要＋證據；一次從備份完整還原並校驗筆數 |

不建議優先做：華麗動畫、額外 Agent persona、全面自動修改專案、將全部內容搬進大型向量資料庫、再增加 10 個未實測來源 connector。這些會增加運營與維護成本，卻不一定提高「精準找出值得採取行動的情報」的成功率。

## 7. 一個可反駁的產品假說

用 4 週測試 OmniKeep 是否真的比既有系統更有價值：

- 收集樣本：固定多類來源、至少 100 條訊息、3 個本地監看專案；保留人工評分。
- 每週比較：有用情報 Precision@10、**真能行動的提案比例**、錯誤／重複卡率、閱讀時間節省、token 成本、可追溯主張比例。
- 基線：OmniKeep 目前排序；加一套簡易 TF-IDF／embedding 方案；可行時再拿 CondenseIt 或 Prismis 的同類公開資料做公平比較。不同資料、模型、硬體不可直接比速度與成本。
- 停損：若加了 semantic ranking 後 Precision@10 沒提升，就先改善原文、偏好標註與資料品質，避免堆疊模型。

## 8. 市場與社群回饋（非代表性抽樣）

- [2026-01 selfhosted bookmark 討論](https://www.reddit.com/r/selfhosted/comments/1q3giqc/best_selfhosted_bookmark_manager/)：Karakeep AI 標籤與 App 受到肯定，但也有使用者偏好 Linkding 輕量與 Linkwarden 手機端。
- [2026-09 網頁保存討論](https://www.reddit.com/r/selfhosted/comments/1w5hmcb/which_saver_of_webpages_to_use/)：人們不一定重視 AI，實際在乎複雜網頁能否完整封存和找回。
- [2026-10 bookmark 討論](https://www.reddit.com/r/selfhosted/comments/1x6kbyg/opinions_about_bookmark_apps/)：簡單、輕量、穩定本身就是強大差異化。
- [2025-01 RSS+AI 問題](https://www.reddit.com/r/selfhosted/comments/1i5r5vh/rss_with_ai_selfhosted_llama/)：想從大量 RSS 中得到個人化推薦與簡短概覽，是清楚存在的需求。

以上屬開放社群零散意見，不可推論成普遍市占、NPS 或產品比較結果。

## 9. 比較結論與選型

1. **研究價值第一名：CondenseIt**。看排序系統、顯示原因、成本／預算與管理介面；解法最直接打到 OmniKeep 的推薦品質缺口。
2. **設計理念第一名：Brain／Prismis**。看如何把使用者及專案語意轉成「值得注意、值得行動」；兩者均非成熟大規模產品。
3. **讀者體驗標竿：Readwise Reader**。時間戳來源、段落標註、跨庫引用式問答。
4. **收藏底座標竿：Karakeep／Linkwarden**。把來源保存、擴充套件、跨裝置、搜尋等基礎做好。
5. **資訊處理與擴充標竿：Folo／SurfSense**。不同來源的專用適配、使用者自訂流程與知識檢索。
6. **保留 OmniKeep 的獨有賭注**：受控地連結外部資訊和使用者本地專案，提出「證據明確、可審核、可驗證成效」的建議。

最不應急著做的是重寫既有基礎為全新平台；最該先驗證的是 **提供更少、更準、可追溯而且真的對當下專案有益的情報**。

## 調查限制

- 實際讀過 OmniKeep README、Watch/Pipeline/Radar 相關實碼與現有交接文件；未修改現有業務程式、資料庫與服務。
- 競品的功能整理以作者原始 README／官方文件為主；個別功能可能是近期加入、實驗中，未透過安裝驗證。
- GitHub metadata 的更新日為 repo `pushed_at`，不是「正式發布日」。Star 高低不等於軟體成熟度或評估結果。
- 沒有對任何競品進行性能基準測試，所提「較完整」專指公開說明的設計涵蓋度。
