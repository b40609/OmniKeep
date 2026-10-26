# 🗺️ 競品全景調研（2026-10-25，深度版）

> 調研方法：Exa 網路搜索（英/中）、GitHub API 即時數據、Hacker News Algolia 檔案庫、多關鍵字組合掃描。
> 兩位審查者（ZCode / GPT）初輪結果不同，本版合併兩條搜尋線：主流成熟賽道 + 新興小專案叢集。

## A. 同題新興叢集（2025-2026 爆發期，與 OmniKeep「雷達＋品味學習」同題）

| 專案 | 星數/狀態 | 技術形態 | 與 OmniKeep 重疊 | 它做得好的 |
|---|---|---|---|---|
| [CondenseIt](https://github.com/wildlifechorus/condenseit) | 91★，2026-05 創立，活躍 | Python 3.11，Ollama/OpenRouter/任意 OpenAI 端點 | 雷達＋品味學習＋每日 digest | **8 種情報源**（RSS/YouTube/網頁變化偵測/Google News 搜尋/HN/Reddit/GitHub Releases/播客）；**星級評分＋互動訊號雙軌學習**；Admin 面板 |
| [Cruxwire](https://github.com/philoking/cruxwire) | 12★，2026-06 創立 | **純 stdlib 單容器**，零依賴，Ollama | 雷達＋聚類去重＋閱讀學習 | **用戶寫的興趣描述直接織進評分 prompt**；故事聚類；雜誌式版面；read/later/history 跨裝置 |
| [Prismis](https://github.com/nickpending/prismis) | 13★，2025-09 創立，alpha | Go + Python **TUI 守護進程** | 雷達＋AI 優先級 | 「研究部門不睡覺」定位；RSS/Reddit/YouTube；終端機重度用戶體驗 |
| [Brain](https://github.com/mstick3/brain) | 0★，2026-07 創立 | Python CLI + Telegram bot，Claude API，本地 embedding | **全鏈路最接近 OmniKeep**：偵察→評分→收藏→digest→連結自己專案 | **批次評分閘門（8+ 自動收、6-7 進建議、其餘丟棄）**；ideas tied to *your projects*（=提案引擎雛形）；morning digest／weekly reflection／**dream pass 自省更新興趣 profile**；語音進出；俄英雙語 embedding |

**叢集共同設計模式**（四家都在解同一道題，做法值得逐一比較）：
1. 評分 prompt 裡織入「用戶自己寫的興趣描述」（Cruxwire、Brain 的 profile.md）——比純標籤權重更有表達力
2. 批次評分＋閘門分級（Brain 的 8+/6-7/drop）——自動化收納與人工確認的分流
3. 學習訊號多元（CondenseIt：星級+互動；Cruxwire：實際閱讀行為）——不止按鈕回饋
4. 極簡部署（Cruxwire 零依賴單容器、pace 單 Docker、Brain `pip install -e .`）——自託管用戶的入場門檻是生死線

## B. 主流成熟賽道

| 專案 | 星數 | 定位 | 對 OmniKeep 的意義 |
|---|---|---|---|
| [Karakeep](https://github.com/karakeep-app/karakeep)（原 Hoarder） | 29,964★ | 自託管萬物收藏＋AI 標籤摘要 | 收藏層最強對手：語意搜尋、monolith 整頁快照、yt-dlp 影片存檔、3 瀏覽器擴充+雙原生 App、規則引擎、OCR、匯入器 |
| [Folo](https://github.com/RSSNext/Folo) | 39,167★ | 「AI 替你讀網路」RSS | 雷達層規模王；社群訂閱清單 |
| [Khoj](https://github.com/khoj-ai/khoj) | 37,815★ | 自託管 AI 第二大腦 | RAG 問答＋自動化通知；但有用戶負評「對自己筆記答非所問」→ 檢索品質是生死線 |
| [OpenKnowledge](https://github.com/inkeep/open-knowledge) | **4,686★**（HN 381 分，2026-06 創立） | AI 優先的 Obsidian/Notion 替代，Open Knowledge Format | **三個月爆衝**；CLI 管理 OKF bundles + Agent Skills——「知識格式標準化 + Agent 原生」是新風向 |
| [Mem0](https://github.com/mem0ai/mem0) | 67,779★ | Agent 記憶層 SaaS | 記憶賽道紅海（mcp.so 同類 652 個） |
| Particle News / Artifact | 商業 | AI 新聞聚類＋品味 | 故事聚類、演進式摘要、對故事提問；Artifact 已死→Yahoo |
| [pace](https://github.com/screenfluent/pace) | 小 | 單容器新聞儀表板（HN/Reddit/GitHub/RSS/Mastodon/arXiv 等 14+ 源） | 去重+評分+可選 LLM；零客戶端 JS |
| Cubox | 商業（中文圈主流） | 收藏+稍後讀融合 | 全端客戶端矩陣（中文用戶的對照組） |
| Reor | 8,536★（放緩） | 本地向量筆記 | 驗證本地 embedding 路線 |
| wallabag / Linkwarden | 13k★ / 20.2k★ | 老牌 read-later / 協作書籤 | 穩定但無 AI 深度 |

## C. OmniKeep 獨有（兩輪調研合併後仍無對手）

1. **監看本地專案 + 兩軸權限（讀取×外送）+ 機密遮蔽層**——無人做
2. **提案引擎**（雷達×指紋→對自己專案出卡→核准閉環）——Brain 的 "ideas tied to your projects" 是最接近的雛形，但無權限、無遮蔽、無核決流
3. **收藏→解構→雷達→品味→提案→MCP 回寫完整閉環**——每家只佔一格
4. 多模態 Reel 解構（IG/FB 影格 OCR）——獨有

## D. 修訂版借鑑清單（依投資報酬率）

| 優先 | 借什麼 | 從誰 | 備註 |
|---|---|---|---|
| 1 | sqlite-vec 語意搜尋 | Karakeep/Brain | 同時是 P2 本地評審層基建，一投資雙回報 |
| 2 | 整頁快照防連結腐爛 | Karakeep（monolith） | 第二大腦的信任地基 |
| 3 | **興趣描述織入評分 prompt** | Cruxwire/Brain | 現有 tech_tags 權重之上加一層「自由文字 profile」，表達力更高；實作一天 |
| 4 | **閘門分級（8+自動收/6-7建議/其餘丟）** | Brain | 現有相關性檢查的升級：relevant 機率+分數→三級分流 |
| 5 | **dream pass：畫像自省** | Brain | 週期性讓 LLM 看滑動歷史→提出 profile 修正建議→用戶核可（與兩軸權限哲學一致） |
| 6 | 規則引擎 | Karakeep | 硬規則與慢學習互補 |
| 7 | 故事聚類升級 | Particle/Cruxwire | radar_events 骨架已有 |
| 8 | 匯入器 + 單容器部署 | Karakeep/Cruxwire/pace | 開源發佈的採用門檻 |
| 9 | 情報源擴充 | CondenseIt（網頁變化偵測、Google News 搜尋運算子、播客） | 雷達 adapter 模式現成，加三個 adapter |

**不追**：多用戶、SaaS、原生 App（既定決策）；純 TUI（與 iOS-first 觸感路線相反）。

## E. 結論

「自託管情報雷達＋AI 摘要＋品味學習」在 2025-2026 已是**公認的好題目**（四個獨立小團隊同時在做），驗證了方向；但**無人擁有閉環**，且新興叢集全部 0-91★——市場上還沒有贏家。OmniKeep 的風險不在想法，在**執行槓桿**：單人對抗的應該是「別人沒有的閉環」，而非「別人已有成熟度的單點」。借鑑清單 1+2 補收藏層地基、3+4+5 把品味學習推到叢集最前線，是最高槓桿路徑。

## F. 與 GPT-6.1 獨立調研的收斂（2026-10-25）

GPT 對照本專案程式碼後提出五大缺口，與本調研交叉驗證後的收斂判斷：

| GPT 指出的缺口 | 本調研印證 | 判定 |
|---|---|---|
| **P0 安全：`verify_api_key` 定義未掛載，全部 /api/* 無應用層認證** | ✅ 程式碼確認（零 Depends 引用；middleware 僅護 /mcp） | **最優先修復**，兩份報告唯一共識的立即項 |
| 推薦演算法初階（僅標籤權重） | ✅ 與「興趣描述織入 prompt」借鑑項同源 | 第二階段主軸 |
| L2 缺證據鏈（段落/時間戳） | ✅ 補充：monolith 整頁快照屬同一問題族 | 融入借鑑清單 #2 |
| 事件去重靠標題 Jaccard | ✅ 屬實 | sqlite-vec 上線後一併升級為向量聚類 |
| 專案關聯停留在「相關」而非「哪個模組」 | ✅ 屬實，proposal engine 的下一級 | 第三階段主軸 |
| 缺跨庫語意研究（SurfSense 類能力） | ✅ 新名字 SurfSense 歸入同一借鑑簇 | sqlite-vec + 引用式問答 |

**三方（ZCode 調研 / GPT 調研 / GPT 程式碼審查）獨立收斂的最終路線**：
Phase 0 安全修復（掛認證＋換 key，一天）→ Phase 1 可信任（monolith 快照＋逐字稿＋向量去重）→ Phase 2 理解你（sqlite-vec＋興趣 profile＋閘門分級＋可解釋推薦）→ Phase 3 情報轉行動（提案升級到模組級：指出具體檔案/模組的改善點＋證據＋成本）。
