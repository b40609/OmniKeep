# OmniKeep 競品程式碼深讀與決策稿

調研日期：2026-10-25。狀態：完成指定範圍的原始碼調研，等待與 Ryan 討論；尚未開始產品功能實作。

## 1. 直接結論

你的懷疑有根據。指定專案已分別把「蒐集 → 篩選 → 摘要」、「使用者偏好 → 個人化」、「語意搜尋 → 引用」做得比 OmniKeep 完整。這些功能本身不宜再當成差異化主張。

但原始碼也顯示，沒有證據支持「其中某一套已完整覆蓋 OmniKeep 想做的全部工作，而且各方面都更好」。較合理的策略是保留目前能運作的收件、滑卡、watch consent 與 proposal 決策流程，採用數個已被具體實作的機制。

最重要的五個判斷：

1. **CondenseIt 是改善每日雷達最值得優先參考的實作。** 先排序、去重與限量，再做摘要；有分類配額與可解釋的分數構成。OmniKeep 的主要問題是先跑完整分析，再決定是否保留。
2. **Prismis 是 SQLite 路線最直接的語意搜尋參考。** 它真的使用 sqlite-vec，並把來源與種類過濾放進 KNN 候選查詢。Brain 使用 SQLite BLOB 加 NumPy 全量掃描；Karakeep 此版本使用 Meilisearch 向量外掛。
3. **Brain 已經有與使用者專案連動的具體建議。** schema 包含 project、action、why、effort_days 與 must-have / nice-to-have，並讀取過往反應。「新知轉專案建議」並非未被做過的題目。
4. **OmniKeep 值得驗證的方向是證據足夠的專案適用性判斷。** 每張建議能指出外部實作、自己專案的具體檔案／符號、版本、適用前提與最小驗證方式。目前 relevance prompt 只有新情報摘要、專案名稱與重疊標籤數，還不足以支撐這種判斷。
5. **不能照抄所有競品。** Pace 的預設分群有中文與同網域誤合併風險；Cruxwire 的偏好主要是正向 centroid；CondenseIt 的預算檢查不是原子預留；trend-radar 未找到授權宣告。應搬機制並補上適合 OmniKeep 的邊界。

以上是靜態原始碼評估，沒有實測它們在 Ryan 的資料上優於 OmniKeep，也沒有宣稱某模型的推薦準確率。

## 2. 範圍、版本與證據規則

先讀取 AUDIT_HANDOFF_GPT61.md 與 docs/competitive_landscape.md，包含第 F 節。之後直接檢查 GitHub 原始碼與本機 clone，不以 README、stars 或宣傳文案推定功能。

競品 clone 保存在研究者本機的獨立研究目錄（未納入本倉庫），六套深讀、四套定向讀。固定版本如下；文內程式碼連結一律使用完整 commit，不指向會移動的 main。

| 專案 | 讀取深度 | 固定 commit | 根目錄授權 |
|---|---|---|---|
| condenseit | 深讀 | [d6d4453caff0](https://github.com/wildlifechorus/condenseit/tree/d6d4453caff0e7416faf88f0682e1b76ed12edd7) | MIT |
| cruxwire | 深讀 | [822944e33742](https://github.com/philoking/cruxwire/tree/822944e33742a466eaadb5ff95852a4e34d5d206) | MIT |
| prismis | 深讀 | [2128b36ff804](https://github.com/nickpending/prismis/tree/2128b36ff80473c03e4ffefe2fa33e086fd4e8b2) | MIT |
| brain | 深讀 | [8dc7d1c818dd](https://github.com/mstick3/brain/tree/8dc7d1c818dd442f90f9a660bb25125ec0581d16) | MIT |
| pace | 深讀 | [3741e45cb180](https://github.com/screenfluent/pace/tree/3741e45cb180eca1e7e237836f8f06eaed171986) | MIT |
| trend-radar | 深讀 | [297b5afa611b](https://github.com/DawnZYC/trend-radar/tree/297b5afa611b0a4b5a44a52fe30d2e7b9570cabc) | 未找到授權宣告 |
| karakeep | 定向讀 | [cab2615d9843](https://github.com/karakeep-app/karakeep/tree/cab2615d9843afc72edb2b34a620349c56d03c98) | AGPL-3.0 |
| Folo | 定向讀 | [68edee907003](https://github.com/RSSNext/Folo/tree/68edee907003a90877f2ffa6bd9ed9bedababfd4) | AGPL-3.0 |
| SurfSense | 定向讀 | [e3de9e0d293b](https://github.com/MODSetter/SurfSense/tree/e3de9e0d293b2ebb1fb813628ecc1d6f26909396) | Apache-2.0 |
| khoj | 定向讀 | [ae229ca894c0](https://github.com/khoj-ai/khoj/tree/ae229ca894c0b80ad84664afcfdde523b5e87057) | AGPL-3.0 |

可重現清單：`research_manifest_2026-10-25.json`（研究時產生的本機紀錄，未隨本倉庫發布）。包含完整 SHA、clone 路徑、授權、研究範圍及 OmniKeep 重要檔案 SHA-256。

OmniKeep 比較基準是 HEAD a7ad9d4e46c207035b05d3004cf438486255724f **加上當時已存在的未提交稽核修正**，最後核對時間 2026-10-25T15:47:15.615Z。初次擷取後，並行稽核更新了 relevance.py；本輪已重讀、刷新其雜湊，核心比較結論不變。因此不能只 checkout HEAD 就重現目前比較結果；須搭配 manifest 的檔案雜湊。本輪沒有改動這些產品檔案。

判讀強度：

- 「已實作」：找到被呼叫的函式、查詢或資料處理路徑。
- 「設計限制／風險」：由讀到的控制流程推論，未當成實際事故或品質測試結果。
- 「建議搬入」：OmniKeep 的設計提案，尚未實作、未估算實際成效。
- 未檢查完整部署、封閉後端、所有 connector 或所有平台相容性；各段明列定向範圍。

## 3. OmniKeep 現況：應修正的比較基準

| 面向 | 本次讀到的程式碼 | 影響 |
|---|---|---|
| 雷達成本 | [app/radar/scheduler.py:60](../app/radar/scheduler.py#L60) 先逐項 run_pipeline，才依分析後 tags 評分、刪除 blocked item | 明確排除或低價值候選也可能先付完整分析成本；應加前段候選層 |
| 偏好 | [app/radar/recommender.py:35](../app/radar/recommender.py#L35) 使用 tag 權重、最大值與平均值、來源 tier；[app/watch/taste.py:19](../app/watch/taste.py#L19) 只從真實標籤學習 | 已有可保留的規則基礎；snooze 是延後，不是喜歡或討厭 |
| 探索 | [app/radar/recommender.py:64](../app/radar/recommender.py#L64) 依分數切前後段，再固定 4:1 插入尾段 | 名稱寫 epsilon-greedy，但程式沒有隨機抽樣或新穎性計算；不能把註解當演算法保證 |
| 事件分群 | [app/radar/clustering.py:7](../app/radar/clustering.py#L7) 只有標題關鍵字 Jaccard，48 小時、門檻 0.35 | 連續中文缺少斷詞；跨語、同義改寫難合併；summary、tags 雖讀取但未參與相似度 |
| 來源數 | [app/radar/clustering.py:59](../app/radar/clustering.py#L59) 每次合併把 unique_source_count 加 1 | 這是合併文章次數，不是不同來源的去重數；不宜拿來當交叉佐證強度 |
| 檢索 | [app/database.py:78](../app/database.py#L78) 建立 FTS5；[app/database.py:401](../app/database.py#L401) 查詢路徑仍是詞彙檢索 | 本次範圍未找到已接通的 embedding 索引或語意搜尋 |
| 專案建議 | [app/watch/relevance.py:54](../app/watch/relevance.py#L54) 先找至少兩個相同 tags 的最強單一 target；[app/watch/relevance.py:107](../app/watch/relevance.py#L107) prompt 只有情報、名稱、重疊數 | 無法據此確認本地模組缺口、API 相容性或修改位置；較接近相關性提示 |
| 本地指紋 | [app/watch/scanner.py:107](../app/watch/scanner.py#L107) 已依 read_scope 納入摘要、README、依賴、程式碼、git；[app/watch/scanner.py:132](../app/watch/scanner.py#L132) 版本雜湊包含材料、範圍與同意狀態 | 不能延用「只看檔名／mtime」的舊結論；但指紋不等於 proposal 已取得可引用的本地程式證據 |
| 影片 | [app/pipeline.py:106](../app/pipeline.py#L106) Gemini 分支可直接分析影片；fallback 用標題／頻道／URL | 不能把全部影片路徑描述成只看標題；仍缺可保存、可定位的 transcript／timestamp 證據層 |
| 引用與流程 | [app/database.py:921](../app/database.py#L921) 已有 citation 儲存；[app/database.py:1279](../app/database.py#L1279) 已有 proposal 與決策狀態 | 應延伸既有模型，先確認與 chunk／版本／locator 的差距，避免另建平行系統 |

此外，[app/security.py:8](../app/security.py#L8) 已有 API key 驗證，[app/network.py:1](../app/network.py#L1) 已有對外 URL／連線限制，[app/background.py:12](../app/background.py#L12) 已有有界後續處理 pool，[tests/conftest.py:1](../tests/conftest.py#L1) 已有測試環境隔離。這些修正仍需由原稽核工作完成驗證，本報告沒有把「尚未加上這些機制」列為待辦，也沒有替它們宣告測試通過。

## 4. 六套深讀

### 4.1 CondenseIt：最完整的雷達候選與偏好組合

**實際路徑。** orchestrator 先蒐集並去除重複，執行 preference rank、故事去重、可選 LLM rerank、每日數量與分類平衡，再平行摘要入選項目，最後依序寫入資料庫。關鍵順序可直接從 [rank 與候選處理：327–425](https://github.com/wildlifechorus/condenseit/blob/d6d4453caff0e7416faf88f0682e1b76ed12edd7/src/condenseit/pipeline/orchestrator.py#L327)、[入選後摘要及序列寫入：439–477](https://github.com/wildlifechorus/condenseit/blob/d6d4453caff0e7416faf88f0682e1b76ed12edd7/src/condenseit/pipeline/orchestrator.py#L439) 追到。

**比 OmniKeep 完整的部分。**

- 偏好分數有多個具名來源：keyword、TF-IDF、category、source、implicit、embedding、topic 等，最後保存 score_breakdown；不是只輸出一個 LLM 總分。見 [PreferenceEngine.rank：400 起](https://github.com/wildlifechorus/condenseit/blob/d6d4453caff0e7416faf88f0682e1b76ed12edd7/src/condenseit/learning/preference_engine.py#L400) 與 [分數構成與排序：639–647](https://github.com/wildlifechorus/condenseit/blob/d6d4453caff0e7416faf88f0682e1b76ed12edd7/src/condenseit/learning/preference_engine.py#L639)。
- 分類配額先保障各類一個位置，再依全域排序補齊並限制單類數量；持續負向偏好的類別可以降額或排除。見 [分類政策：64–73](https://github.com/wildlifechorus/condenseit/blob/d6d4453caff0e7416faf88f0682e1b76ed12edd7/src/condenseit/pipeline/article_balance.py#L64)、[先覆蓋再補齊：104 起](https://github.com/wildlifechorus/condenseit/blob/d6d4453caff0e7416faf88f0682e1b76ed12edd7/src/condenseit/pipeline/article_balance.py#L104)。orchestrator 另用最少評分數限制，減少冷啟動時少量負評就蓋過明示興趣的情況。
- 語意去重可選用 embedding；輸入是標題與部分正文，先有排名再保留較高項目。見 [故事去重：743 起](https://github.com/wildlifechorus/condenseit/blob/d6d4453caff0e7416faf88f0682e1b76ed12edd7/src/condenseit/pipeline/orchestrator.py#L743)。
- embedding 快取的實作鍵包含 URL、model_name、content_hash；失效重算，而非只用 URL 判斷。見 [get_or_compute_embedding：214–236](https://github.com/wildlifechorus/condenseit/blob/d6d4453caff0e7416faf88f0682e1b76ed12edd7/src/condenseit/learning/embeddings.py#L214)。
- 學習含評分、時間衰減與隱性行為；read、read-later、dismiss 的虛擬分數不同。見 [learn 與最少樣本條件：318 起](https://github.com/wildlifechorus/condenseit/blob/d6d4453caff0e7416faf88f0682e1b76ed12edd7/src/condenseit/learning/preference_engine.py#L318)、[隱性行為：849–944](https://github.com/wildlifechorus/condenseit/blob/d6d4453caff0e7416faf88f0682e1b76ed12edd7/src/condenseit/learning/preference_engine.py#L849)。

**適合搬的最小模組。** 候選排序與分析分開、每批數量上限、分類配額、逐項理由／分數構成、帶版本的 embedding cache。OmniKeep 不必搬整個偏好引擎；先把來源 tier、既有 tags、明示 profile 和排除條件拆成可觀察的欄位即可。

**不能直接沿用的部分。**

- category balancing 在全部被排除時有回退到全域前幾名的安全網；OmniKeep 的明確 mute 應維持絕對排除，不能被配額／探索／回退重新放回。
- [_apply_blend：344–365](https://github.com/wildlifechorus/condenseit/blob/d6d4453caff0e7416faf88f0682e1b76ed12edd7/src/condenseit/learning/reranker.py#L344) 直接混合 classical score 與 LLM relevance。兩者尺度不一致時要先校準，或採依名次融合，不能只搬權重。
- [can_spend 與 record_spend：49–65](https://github.com/wildlifechorus/condenseit/blob/d6d4453caff0e7416faf88f0682e1b76ed12edd7/src/condenseit/providers/budget.py#L49) 是查目前花費後記錄，兩者不是一次原子預留；thread lock 保護單次 DB 存取，無法保證多個工作不共同超額。若加入金額預算，應使用 Decimal、TEXT 儲存與 reserve／settle／release。
- read-later 的正向訊號不能直接映射 OmniKeep snooze。這是不同產品語意。

授權：MIT，可在保留適當授權資訊的前提下評估移植小型模組；仍需改介面、測試與上述邊界。

### 4.2 Cruxwire：語意事件分群與正向偏好的小型參考

**實際路徑。** 抓取文章、LLM 評分／摘要、產生 embedding，之後做語意封鎖、taste、cluster，最後寫入 digest 與向量 sidecar。見 [enrich：354 起](https://github.com/philoking/cruxwire/blob/822944e33742a466eaadb5ff95852a4e34d5d206/pipeline.py#L354)、[排序後段：956–975](https://github.com/philoking/cruxwire/blob/822944e33742a466eaadb5ff95852a4e34d5d206/pipeline.py#L956)。它也不是所有成本都先擋住的示範。

**有價值的實作。**

- [build_system_prompt：249–265](https://github.com/philoking/cruxwire/blob/822944e33742a466eaadb5ff95852a4e34d5d206/pipeline.py#L249) 把自由文字興趣帶入評分，比單純 tag 權重更能表達「正在做什麼、為何需要」。
- [apply_taste：558–608](https://github.com/philoking/cruxwire/blob/822944e33742a466eaadb5ff95852a4e34d5d206/pipeline.py#L558) 從 saved／history 取樣，saved 權重大於 opened，依新近程度取前段，再建正向加權 centroid，對相似文章加分。向量不是每個請求傳到瀏覽器。
- [cluster：611–663](https://github.com/philoking/cruxwire/blob/822944e33742a466eaadb5ff95852a4e34d5d206/pipeline.py#L611) 依高分項目先當 anchor，新項目與 anchor 比較；沒有 embedding 的文章維持 singleton。這能避開「A 像 B、B 像 C，就把 A 與 C 一路串成大群」的單連結問題。
- 每群選代表項目，再依群大小給有上限的 log2 加分；[semantic_search：510–534](https://github.com/philoking/cruxwire/blob/822944e33742a466eaadb5ff95852a4e34d5d206/pipeline.py#L510) 也重用同一批向量做搜尋。

**與 OmniKeep 的差異。** OmniKeep 是標題詞重疊，Cruxwire 是語意 anchor。對跨來源改寫與中英同事件，後者是更合理的候選設計，但是否真的改善仍須用我們的資料測量。

**適合搬。** anchor 型分群、缺向量時保留單筆的降級方式、搜尋與分群共用 embedding、群內保留所有來源並選代表。

**要改。** taste 缺少對等的負向 centroid；依新近樣本上限不等於連續時間衰減。群大小是文章數，不是不同來源數。greedy anchor 受排序影響，代表文章 id 也不應取代 OmniKeep 需要長期穩定的 event_id。保留交易式 SQLite，不用整套改成 JSON／sidecar。

授權：MIT。

### 4.3 Prismis：自由文字脈絡、分層分析與真正的 sqlite-vec

**實際路徑。** 每輪重讀 context；先做輕摘要與脈絡評估，再依 priority、來源與設定決定是否深抽取，之後存內容與 embedding。見 [refresh_context：82 起](https://github.com/nickpending/prismis/blob/2128b36ff80473c03e4ffefe2fa33e086fd4e8b2/daemon/src/prismis_daemon/orchestrator.py#L82)、[輕摘要與評估：160–223](https://github.com/nickpending/prismis/blob/2128b36ff80473c03e4ffefe2fa33e086fd4e8b2/daemon/src/prismis_daemon/orchestrator.py#L160)、[深抽取閘門與存入：246–292](https://github.com/nickpending/prismis/blob/2128b36ff80473c03e4ffefe2fa33e086fd4e8b2/daemon/src/prismis_daemon/orchestrator.py#L246)。它仍先付輕摘要／評估成本，不能描述成完全免費的初篩。

**有價值的實作。**

- 評估器區分「成功但沒有符合興趣」與「輸出格式／分析失敗」。見 [評估結果解析：180 起](https://github.com/nickpending/prismis/blob/2128b36ff80473c03e4ffefe2fa33e086fd4e8b2/daemon/src/prismis_daemon/evaluator.py#L180)。比把錯誤默認成中等分數更可觀察。
- config 驅動的 deep extract 可以只給高優先內容；失敗會留下狀態，而不是當成根本沒做過。這適合影片、長文與程式庫的分層分析。
- [載入 sqlite-vec：219–225](https://github.com/nickpending/prismis/blob/2128b36ff80473c03e4ffefe2fa33e086fd4e8b2/daemon/src/prismis_daemon/database.py#L219)，以及 [更新 embedding／vec：1945–1989](https://github.com/nickpending/prismis/blob/2128b36ff80473c03e4ffefe2fa33e086fd4e8b2/daemon/src/prismis_daemon/storage.py#L1945) 證明是真正的 SQLite 向量索引；更新時先移除舊向量，再寫入新向量並交易提交。
- [過濾進入 KNN 候選查詢：2055–2079](https://github.com/nickpending/prismis/blob/2128b36ff80473c03e4ffefe2fa33e086fd4e8b2/daemon/src/prismis_daemon/storage.py#L2055) 把來源／種類篩選放在候選查詢中，避免先取全庫 top 100 再篩導致指定範圍的有效結果被擠掉。後段以語意、priority、來源權威加權，見 [重排：2117–2135](https://github.com/nickpending/prismis/blob/2128b36ff80473c03e4ffefe2fa33e086fd4e8b2/daemon/src/prismis_daemon/storage.py#L2117)。
- [analyze_context：1758–1808](https://github.com/nickpending/prismis/blob/2128b36ff80473c03e4ffefe2fa33e086fd4e8b2/daemon/src/prismis_daemon/api.py#L1758) 讀近期 upvote 與既有 context，回傳 profile 建議。[建議解析：235 起](https://github.com/nickpending/prismis/blob/2128b36ff80473c03e4ffefe2fa33e086fd4e8b2/daemon/src/prismis_daemon/context_analyzer.py#L235) 區分 add、expand、narrow、split；這條已確認路徑是產生建議，不能據此宣稱它會自動改寫使用者偏好。
- [drift decide：77–138](https://github.com/nickpending/prismis/blob/2128b36ff80473c03e4ffefe2fa33e086fd4e8b2/daemon/src/prismis_daemon/drift.py#L77) 用足夠歷史日窗、null-priority 占比、中位數基準、告警鎖存與較低解除門檻。這是評分／不匹配比例漂移的代理訊號，不是推薦品質的真值。

**適合搬。** 明示 context、分層分析閘門、結構化分析狀態、SQLite 向量查詢、範圍先過濾、profile 修改提案、最低樣本才判定的監測。

**要改。** [embedding 模型與輸入：35–61](https://github.com/nickpending/prismis/blob/2128b36ff80473c03e4ffefe2fa33e086fd4e8b2/daemon/src/prismis_daemon/embeddings.py#L35) 的模型與截斷策略不能直接當成中英混合資料的最佳選項；要比較多語模型、文件長度、模型版本與本機成本。此處的固定權重也未在 OmniKeep 資料上校準。本輪未證實設定中的 learn_from_votes 能直接提供完整的自動負向偏好學習，不把設定名稱當作已接通功能。

授權：MIT。這套的後端邏輯比移植 TUI 更值得投入。

### 4.4 mstick3/brain：新知轉專案建議已有直接先例

**蒐集與成本。** [evaluate_candidates：206–225](https://github.com/mstick3/brain/blob/8dc7d1c818dd442f90f9a660bb25125ec0581d16/brain/discover.py#L206) 把標題、頻道、長度、部分 description 與 profile 組成一批 LLM 評估，再決定下載／分析。[run_discover：244–304](https://github.com/mstick3/brain/blob/8dc7d1c818dd442f90f9a660bb25125ec0581d16/brain/discover.py#L244) 依分數與每日加入數量控制自動收錄與 suggestions。AUTO_ADD_SCORE = 8 是評分門檻，不是每批八筆；daily_budget_left 也是收錄數量額度，不是美元成本上限。

**真正與本專案重疊的部分。**

- [BUILD_SCHEMA：46–72](https://github.com/mstick3/brain/blob/8dc7d1c818dd442f90f9a660bb25125ec0581d16/brain/tasks.py#L46) 明確要求 project、source、action、why、verdict、effort_days，輸出三到五個建議。
- [BUILD_SYSTEM：74–95](https://github.com/mstick3/brain/blob/8dc7d1c818dd442f90f9a660bb25125ec0581d16/brain/tasks.py#L74) 要求考慮現有專案進度、過往 👍／👎 及是否過早擴張，並能產生 foundation_warning。
- [build_ideas：221–243](https://github.com/mstick3/brain/blob/8dc7d1c818dd442f90f9a660bb25125ec0581d16/brain/tasks.py#L221) 把近期筆記、profile 與偏好材料送入這個流程。因此「不是摘要，而是幫我決定能做什麼」已經有具體實作。

**其他值得搬的部分。**

- [get_transcript：168–192](https://github.com/mstick3/brain/blob/8dc7d1c818dd442f90f9a660bb25125ec0581d16/brain/fetchers.py#L168) 優先取得字幕，否則下載音訊轉 Whisper，並標記來源。比影片 fallback 只用 metadata 更有可驗證的內容底座。
- [run_dream：152–198](https://github.com/mstick3/brain/blob/8dc7d1c818dd442f90f9a660bb25125ec0581d16/brain/dream.py#L152) 產生興趣更新提案；[apply_dream：200–238](https://github.com/mstick3/brain/blob/8dc7d1c818dd442f90f9a660bb25125ec0581d16/brain/dream.py#L200) 經套用動作後才更新、備份，並標記 applied。可參考它的「觀察 → 提案 → 確認」流程。

**要辨清的限制。**

- [search：114–139](https://github.com/mstick3/brain/blob/8dc7d1c818dd442f90f9a660bb25125ec0581d16/brain/indexer.py#L114) 每次從 SQLite 讀取所有 chunk embedding，NumPy vstack 後矩陣乘 query；不是 sqlite-vec。資料增加時是全量掃描與配置記憶體，不是 OmniKeep 向量索引的首選範本。
- 建議建立在筆記、profile 與反應；上述路徑沒有提供本地 repository 的檔案／符號／行號證據，也沒有證明 effort_days 的估算準確。
- discover 將所有候選放一批，移植時需獨立設定 batch 大小與 token 上限。
- apply_dream 有備份與 applied guard，但所讀路徑沒有生成時 profile base hash 的比對；生成後使用者再編輯，套用舊提案仍可能覆寫新內容。應增加版本檢查及差異預覽。
- [whisper_transcribe：145–165](https://github.com/mstick3/brain/blob/8dc7d1c818dd442f90f9a660bb25125ec0581d16/brain/fetchers.py#L145) 使用 CPU／int8；若搬入，應讓裝置與精度可設定，再測試 Ryan 的 GPU，不能把它描述成現成 GPU 管線。

**適合搬。** metadata 候選閘門、字幕／轉錄來源鏈、具體行動 schema、反應紀錄與 profile 更新提案。OmniKeep 的差異化應提升到「建議有兩邊程式證據與可測試前提」，而不是重做這些欄位。

授權：MIT。

### 4.5 screenfluent/pace：可組合處理階段與來源追溯

**實際機制。**

- [TRANSFORM_RUNNERS 與 runPipeline：33–81](https://github.com/screenfluent/pace/blob/3741e45cb180eca1e7e237836f8f06eaed171986/src/transforms.ts#L33) 定義 latest、filter、exclude、sort、dedupe、keyword-score、time-decay、cluster、LLM 等 transform，依設定順序執行。當結果是 passthrough 原陣列，避免誤記 applied_transforms。
- [summarizeRows：59–82](https://github.com/screenfluent/pace/blob/3741e45cb180eca1e7e237836f8f06eaed171986/src/transform-llm.ts#L59) 只摘要尚無 summary 的 rows，必要時也只抓這些 rows 的正文，再依 id 合併。比每次全部重做更節省。
- [mergeOrigins：161–170](https://github.com/screenfluent/pace/blob/3741e45cb180eca1e7e237836f8f06eaed171986/src/dedupe.ts#L161) 把重複項目的 origins 聯集留在代表項目，避免去重把來源脈絡一起丟掉。

**容易誤讀的分群。** [分群圖與 union-find：19–81](https://github.com/screenfluent/pace/blob/3741e45cb180eca1e7e237836f8f06eaed171986/src/cluster-graph.ts#L19) 是相似邊加連通分量；[分群輸出：17–35](https://github.com/screenfluent/pace/blob/3741e45cb180eca1e7e237836f8f06eaed171986/src/cluster-result.ts#L17) 仍輸出群中所有項目，只排序／加標籤，不是把一個新聞事件壓成一張代表卡。

預設 auto similarity 的 domain、keyword、source 權重是 0.5／0.45／0.05，見 [computeClusterSimilarity：79–97](https://github.com/screenfluent/pace/blob/3741e45cb180eca1e7e237836f8f06eaed171986/src/cluster-signals.ts#L79)。同網域訊號若為 1，單靠它便超過預設 0.3 門檻；[預設參數：14–32](https://github.com/screenfluent/pace/blob/3741e45cb180eca1e7e237836f8f06eaed171986/src/cluster.ts#L14)。更關鍵的是 [extractClusterKeywords：35–40](https://github.com/screenfluent/pace/blob/3741e45cb180eca1e7e237836f8f06eaed171986/src/cluster-signals.ts#L35) 只保留 a-z、數字與部分符號，中文被移除。這不適合原樣套進 OmniKeep 中文新聞。

**適合搬。** 明確階段契約、每項處理 provenance、去重保留 origins、對未完成項目補做。最初只拆幾個 Python 函式與資料結構即可，不必為此引入通用流程引擎。

**要改。** summary 快取要帶 content hash、prompt／model 版本；不能只看是否已有 summary。分群採可測量的語意事件規則，避免同網域自動代表同事件，也避免連通鏈過度合併。

授權：MIT。TypeScript 實作以設計參考為主，直接移植至 Python 的收益低於重寫小型介面。

### 4.6 DawnZYC/trend-radar：收集與付費分析分離的精簡流程

**實際順序。** [collect：38–43](https://github.com/DawnZYC/trend-radar/blob/297b5afa611b0a4b5a44a52fe30d2e7b9570cabc/main.py#L38) 只蒐集入庫；[digest：46–96](https://github.com/DawnZYC/trend-radar/blob/297b5afa611b0a4b5a44a52fe30d2e7b9570cabc/main.py#L46) 取未報候選與 surge、排序、截斷 MAX_ANALYZE 後才 enrich 與分析、產生總覽、存檔及寄送。

- [record 與 unreported_new：66–109](https://github.com/DawnZYC/trend-radar/blob/297b5afa611b0a4b5a44a52fe30d2e7b9570cabc/store.py#L66) 保存每日快照，用近期首次出現、前段歷史與 reported 狀態組合篩選，避免只看當次 trending 清單。
- [find_surges：47–63](https://github.com/DawnZYC/trend-radar/blob/297b5afa611b0a4b5a44a52fe30d2e7b9570cabc/store.py#L47) 比較前七日內參考星數與現值，預設 ratio 1.5；這是星數比例訊號，不能描述成已校準的技術價值或成長加速度。
- [分析、寄送與標記：80–94](https://github.com/DawnZYC/trend-radar/blob/297b5afa611b0a4b5a44a52fe30d2e7b9570cabc/main.py#L80) 先寄送，成功後才把有分析結果的 repo 標成 reported；失敗結果可在後續再次被選取。
- [analyze_repo：56–85](https://github.com/DawnZYC/trend-radar/blob/297b5afa611b0a4b5a44a52fe30d2e7b9570cabc/analyzer.py#L56) 用 repo 中繼資料與 README，結構化輸出評分；[analyze_all：98–107](https://github.com/DawnZYC/trend-radar/blob/297b5afa611b0a4b5a44a52fe30d2e7b9570cabc/analyzer.py#L98) 平行分析與第二次總覽。它沒有在這條路徑讀實際程式模組。

**比 OmniKeep 好用的地方。** 成本閘門和狀態機小而清楚，適合 GitHub 來源 adapter：蒐集頻率與付費 digest 頻率分開，先過濾已報與舊項目，再分析有額度的候選。

**限制。** 新候選接上 surges 後統一截斷，前者過多時後者可能沒有位置。send 成功後、mark_reported 前若中斷，仍可能重送；不是 exactly-once。dry_run 之前仍會 scrape／record，不能把這個模式當成完全唯讀測試。README 評分也不等於專案適用性或程式碼審查。

**適合搬。** collect／digest 分離、候選額度、成功送達後的狀態更新與可重試分析。應以自己的程式重新實作設計；本次根目錄與已檢查程式檔未找到授權宣告，不能當成 MIT 程式碼直接複製。

## 5. 四套定向閱讀

### 5.1 Karakeep：保存原始材料、分離背景工作與混合搜尋

本段定向檢查 crawler、embedding worker、vectorstore 與 search ranking，沒有把全部產品功能納入評估。

- **離線保存是真的有程式路徑。** [archiveWebpage：2136–2215](https://github.com/karakeep-app/karakeep/blob/cab2615d9843afc72edb2b34a620349c56d03c98/apps/workers/workers/crawlerWorker.ts#L2136) 將已取得 HTML 經 stdin 交給 monolith，帶 base URL、timeout，產出 HTML asset；另外檢查實際檔案大小及儲存額度。[正文 HTML 與 asset 更新：1070–1120](https://github.com/karakeep-app/karakeep/blob/cab2615d9843afc72edb2b34a620349c56d03c98/apps/workers/workers/crawlerWorker.ts#L1070) 將解析文字、HTML 與截圖等關聯分開保存。這比只留下摘要更適合來源失效後回看。
- **embedding 是獨立失敗域。** [EmbeddingsWorker：31–75](https://github.com/karakeep-app/karakeep/blob/cab2615d9843afc72edb2b34a620349c56d03c98/apps/workers/workers/embeddingsWorker.ts#L31) 有獨立 queue runner、concurrency、timeout、validator、重試後的永久失敗狀態；embedding 最終失敗仍安排不依賴相似度的 tagging fallback。可借鏡「收錄成功」與「向量化成功」分開。
- **這個版本的向量後端是 Meilisearch 外掛。** [向量查詢：80–99](https://github.com/karakeep-app/karakeep/blob/cab2615d9843afc72edb2b34a620349c56d03c98/packages/plugins/vectorstore-meilisearch/src/index.ts#L80) 呼叫 vector／semanticRatio；不應引用為 sqlite-vec 範例。
- **混合搜尋的融合與降級可直接追。** [reciprocalRankFusion：13–47](https://github.com/karakeep-app/karakeep/blob/cab2615d9843afc72edb2b34a620349c56d03c98/packages/trpc/lib/searchRanking.ts#L13) 依各結果名次加分、同一清單內去重、穩定處理同分。[固定候選池與降級：1158–1178](https://github.com/karakeep-app/karakeep/blob/cab2615d9843afc72edb2b34a620349c56d03c98/packages/trpc/routers/bookmarks.ts#L1158) 同時執行 FTS／semantic，固定候選視窗避免分頁重排；semantic 失敗時回 FTS。

**搬入判斷。** 可自行實作 asset／extracted text／analysis 分層、embedding 背景工作與 RRF；不必為 OmniKeep 連帶引入 Meilisearch。monolith 可獨立評估，但它會抓取外部資源，不能因主頁 URL 已驗證，就繞過現有網路防護；需對子資源建立同等限制、timeout、大小配額與失敗隔離。也不必讓每篇候選都先產生完整快照。

授權：AGPL-3.0。先採架構參考並獨立實作；若決定直接移植程式，需先確定 OmniKeep 的授權與發佈方式相容。

### 5.2 Folo：應借鏡讀取與操作可靠性，不推定封閉 AI 後端能力

本段定向檢查摘要 store、同步佇列與 AI transport。[createChatTransport：50–64](https://github.com/RSSNext/Folo/blob/68edee907003a90877f2ffa6bd9ed9bedababfd4/apps/desktop/layer/renderer/src/modules/ai-chat/store/transport.ts#L50) 將對話送往 API 的 /ai/chat；此次可讀 client 原始碼不能用來推定伺服器端的推薦或推理演算法。

- [SummarySyncService：102–181](https://github.com/RSSNext/Folo/blob/68edee907003a90877f2ffa6bd9ed9bedababfd4/packages/internal/store/src/modules/summary/store.ts#L102) 以 entry、language、content target 取得現有摘要；同狀態 pending 時共用 promise，避免同一項目同時送多次摘要請求，並明列 pending／success／error。
- [enqueue：205–234](https://github.com/RSSNext/Folo/blob/68edee907003a90877f2ffa6bd9ed9bedababfd4/packages/internal/store/src/sync/transaction-queue.ts#L205) 先 apply 本地動作，再建立待同步交易並寫入 outbox；[restore：240 起](https://github.com/RSSNext/Folo/blob/68edee907003a90877f2ffa6bd9ed9bedababfd4/packages/internal/store/src/sync/transaction-queue.ts#L240) 能重播前次工作階段留下的交易。
- [runFlush：476–535](https://github.com/RSSNext/Folo/blob/68edee907003a90877f2ffa6bd9ed9bedababfd4/packages/internal/store/src/sync/transaction-queue.ts#L476) 在同步前確認 owner／session，處理離線、暫停、重試與 batch；[failBatch：620–633](https://github.com/RSSNext/Folo/blob/68edee907003a90877f2ffa6bd9ed9bedababfd4/packages/internal/store/src/sync/transaction-queue.ts#L620) 對無法完成的動作執行 rollback。
- 要留意 enqueue 的持久化失敗只記錄錯誤，仍繼續排送；不能把「有 outbox 設計」描述成所有情境都保證不丟操作。

**搬入判斷。** 適合 OmniKeep 滑卡／收藏的即時回饋、失敗回復、去重請求與離線後重送；應配合伺服器 idempotency key。這是後續操作體驗階段，優先順序低於雷達品質與來源證據。簡化成少數 mutation 的佇列即可，不必移植整個前端 store 生態。

授權：AGPL-3.0，架構參考與獨立實作優先。

### 5.3 SurfSense：引用定位與增量索引最值得看

本段定向檢查主 backend 的 hybrid retriever、reranker、chunk reconciler 與 citation registry；沒有假設整個 repository 的所有版本／部署都只用同一組後端。

- **混合搜尋先界定範圍。** [workspace／狀態與其他條件：236–266](https://github.com/MODSetter/SurfSense/blob/e3de9e0d293b2ebb1fb813628ecc1d6f26909396/surfsense_backend/app/retriever/documents_hybrid_search.py#L236) 先建立 workspace、未刪除、文件種類與時間條件；[兩路候選與 RRF：269–323](https://github.com/MODSetter/SurfSense/blob/e3de9e0d293b2ebb1fb813628ecc1d6f26909396/surfsense_backend/app/retriever/documents_hybrid_search.py#L269) 同時套用到 semantic／keyword 候選，再 FULL JOIN 融合。避免先搜全庫再限制專案。
- **rerank 保留原始 chunks。** [引用資料與失敗降級：105–121](https://github.com/MODSetter/SurfSense/blob/e3de9e0d293b2ebb1fb813628ecc1d6f26909396/surfsense_backend/app/services/reranker_service.py#L105) 保留 chunk 結構以供引用，失敗回原排序。
- **更新時不必全部重算。** [reconcile：63–101](https://github.com/MODSetter/SurfSense/blob/e3de9e0d293b2ebb1fb813628ecc1d6f26909396/surfsense_backend/app/indexing_pipeline/chunk_reconciler.py#L63) 以完全相同文字的 multiset 配對舊／新 chunks；原文沒變只更新 position／line，只有新增文字進 embedding，未使用舊 chunk 才列為刪除。模型版本改變仍應讓 cache 失效，不能只看文字相同。
- **引用有獨立識別與解析層。** [CitationRegistry：16–58](https://github.com/MODSetter/SurfSense/blob/e3de9e0d293b2ebb1fb813628ecc1d6f26909396/surfsense_backend/app/agents/chat/multi_agent_chat/shared/citations/registry.py#L16) 用 source_type 與穩定序列化 locator 去重、分配編號，再 resolve 回來源；未知編號無法解析。這是可追溯結構，並不自動證明 LLM 句子真的被引文支持。
- [attach_line_spans：73–100](https://github.com/MODSetter/SurfSense/blob/e3de9e0d293b2ebb1fb813628ecc1d6f26909396/surfsense_backend/app/indexing_pipeline/document_chunker.py#L73) 在順序不重疊的 chunk 上建立行號；找不到或 chunk 重寫／重疊時會退回 cursor，因此不能盲信所有輸出行號都精確。OmniKeep 如做程式碼引用，應由已知原始 offset／parser span 取得定位並驗證。

**搬入判斷。** 最值得取的是 evidence locator、穩定 source id、保留原文 chunk、增量 embedding，以及 rerank 不破壞引用。可以在 SQLite 上重新實作相同契約；不用整套搬 PostgreSQL／agent 框架。此檢索檔案的 FTS 設為 english，見 [FTS 語言：232–234](https://github.com/MODSetter/SurfSense/blob/e3de9e0d293b2ebb1fb813628ecc1d6f26909396/surfsense_backend/app/retriever/documents_hybrid_search.py#L232)，不能當成已解決中文詞彙檢索。

授權：Apache-2.0。若移植小型純函式，須保留適用授權／NOTICE，並先處理定位假設與模型版本。

### 5.4 Khoj：先過濾資料範圍，再搜尋與決定是否通知

本段定向讀 text search、EntryAdapters、automation 與通知判斷。

- [apply_filters：2090–2147](https://github.com/khoj-ai/khoj/blob/ae229ca894c0b80ad84664afcfdde523b5e87057/src/khoj/database/adapters/__init__.py#L2090) 建立 owner、word、file path 與日期條件；沒有 user／agent owner 時回空結果。
- [search_with_embeddings：2150–2178](https://github.com/khoj-ai/khoj/blob/ae229ca894c0b80ad84664afcfdde523b5e87057/src/khoj/database/adapters/__init__.py#L2150) 先套 filters，再計算 CosineDistance、門檻、排序與 limit。這條路徑使用資料庫向量查詢，不是 sqlite-vec。
- [rerank_and_sort_results：192–206](https://github.com/khoj-ai/khoj/blob/ae229ca894c0b80ad84664afcfdde523b5e87057/src/khoj/search_type/text_search.py#L192) 視設定與候選數量執行 cross-encoder，再排序。[deduplicated_search_responses：167–189](https://github.com/khoj-ai/khoj/blob/ae229ca894c0b80ad84664afcfdde523b5e87057/src/khoj/search_type/text_search.py#L167) 的去重依相同 compiled text，不等於語意事件分群。
- [排程入口：53 起](https://github.com/khoj-ai/khoj/blob/ae229ca894c0b80ad84664afcfdde523b5e87057/src/khoj/routers/api_automation.py#L53) 已有排程提問。[should_notify：2489–2521](https://github.com/khoj-ai/khoj/blob/ae229ca894c0b80ad84664afcfdde523b5e87057/src/khoj/routers/helpers.py#L2489) 另以模型判斷是否通知；[通知送出路徑：2612–2621](https://github.com/khoj-ai/khoj/blob/ae229ca894c0b80ad84664afcfdde523b5e87057/src/khoj/routers/helpers.py#L2612) 才決定寄送。模型判斷失敗時預設通知，因此不是「一定只在有新進展時通知」的保證。

**搬入判斷。** 專案／同意範圍應在檢索候選前生效；跨專案資料不可先進 prompt 再過濾。通知可以獨立於內容生成，但最好加入確定性的新事件／變更／已送達狀態，避免只交給 LLM。

授權：AGPL-3.0，以設計參考與獨立實作為主。

## 6. 哪些能力已是基本配備，哪些值得繼續驗證

| 能力 | 已找到的具體先例 | OmniKeep 判斷 |
|---|---|---|
| 多來源收錄、摘要、分類 | CondenseIt、Cruxwire、Pace | 基本配備；繼續比 connector 數量收益低 |
| 自由文字興趣＋行為偏好 | Prismis context、CondenseIt preference、Cruxwire taste | 明顯可補；先保留可解釋規則，再加語意訊號 |
| 每日低成本候選分析 | CondenseIt shortlist、Brain discover、trend-radar cap | 優先補，對目前「先分析再丟棄」有直接改善機會 |
| 語意搜尋／混合搜尋 | Prismis sqlite-vec、Karakeep／SurfSense RRF | 已有成熟設計；SQLite 整合可從最小介面開始 |
| 同事件合併 | Cruxwire anchor cluster；Pace 為另一種連通分群 | 使用語意候選＋來源證據，別照搬標題 Jaccard 或網域權重 |
| 影片可回溯內容 | Brain 字幕／Whisper fallback | 明確內容缺口；轉錄與模型判斷狀態要分開保存 |
| 專案導向行動建議 | Brain build_ideas | 已有直接先例；只增加 impact／effort 欄位不夠 |
| 可定位證據 | SurfSense chunks／citations；Karakeep 原始保存 | 對 OmniKeep 的資訊品質與專案建議都有價值 |
| 精確指出自己與外部程式的適用差異，再用測試驗證 | 本輪所讀建議路徑未看到完整等價流程 | 值得做小型原型；這是待驗證的產品假設，不能據此宣稱全市場沒人做 |
| scoped consent＋watch fingerprint＋proposal 決策 | OmniKeep 目前已有骨架 | 保留並加強證據；此次未做所有競品的同意機制全面比較，不能宣稱獨有 |

這一輪不能推導「換掉 OmniKeep、直接用某個競品一定比較好」。若需求只有個人 RSS 摘要，直接使用現成工具很有吸引力；若仍要把外部材料連到 Ryan 自己的 repository 與工作，整合既有 watch／proposal 路徑有合理價值。是否值得持續投入，應由下一節的可用性實驗決定。

## 7. 可搬模組：切到能實作與驗收的大小

以下為提案，不是本輪已修改的產品設計或資料庫 schema。

| 模組 | 最小責任與輸出 | 參考來源 | 主要接點／依賴 |
|---|---|---|---|
| M1 候選層 | metadata、來源、canonical URL、明示排除、理由、候選狀態；限量後才走深分析 | CondenseIt、Brain、trend-radar | radar adapter → scheduler；可先不加向量 |
| M2 明示 profile 與評分說明 | 正在做的專案、近期目標、偏好、排除、來源權重；輸出 reason codes／score breakdown | Prismis、CondenseIt | 現有 taste／topic 權重；profile 有版本 |
| M3 共用 embedding 服務 | 批次計算、model／dimension／normalization／content hash／chunker version、失敗狀態與快取 | Prismis、CondenseIt | 後台工作；FTS 降級；安裝 extension 先做環境驗證 |
| M4 語意事件與混合搜尋 | 搜尋 RRF、事件 anchor、stable event_id、來源聯集與不同來源數 | Cruxwire、Karakeep、Pace | M3；搜尋／分群共用向量但各自評估門檻 |
| M5 原始材料與引用 | 原文／transcript／選擇性快照、版本 hash、chunk／timestamp／檔案符號 locator、coverage 狀態 | Brain、Karakeep、SurfSense | 可與 M1 並行；引用本身不必等向量 |
| M6 有證據的專案建議 | 外部證據＋本地 target 證據＋適用前提＋改動候選＋驗證方案＋不確定處 | Brain schema、SurfSense evidence、OmniKeep proposal | M5 與 scope／consent；M3 讓候選查找更有效率 |
| M7 操作與送達可靠性 | 摘要請求 coalescing、mutation outbox／idempotency、通知去重與錯誤狀態 | Folo、trend-radar、Khoj | 放在內容品質穩定後；可獨立小步做 |

### M1 的具體流程

    adapter 蒐集 metadata
    → canonical URL／已收錄／硬排除檢查
    → 規則初排＋明示 profile；必要時才小批 LLM 輕評估
    → 來源／分類配額＋每批與每日上限
    → 入選者走既有 run_pipeline
    → 保存分析狀態、證據與最終評分
    → 事件／deck／digest

前段資訊不足時應標成 unknown，或進保留探索名額；不能把「沒有 tags」直接當成不相關。早期只能排除已有充分依據的項目，深分析後仍保留既有 tag mute 檢查。探索應依目標決定採樣規則與可重播 seed，或者誠實標成多樣性配額，不再把固定尾段插入叫作 epsilon-greedy。

有金額額度時要處理並行預留、實際結算、失敗釋放；先只有數量上限就明確叫數量上限。對外模型費用使用 Decimal，不複製 float 帳務。

### M3 的邊界

第一版保留目前 SQLite，先驗證 sqlite-vec 在 Windows、現有 Python／SQLite runtime 與備份還原路徑可用。這是環境風險，尚未在本輪安裝或測試。

搜尋應保留詞彙路徑，尤其精確的套件名、錯誤碼、符號。語意候選先套來源／project／consent 範圍，再與 FTS 名次融合；向量失敗回 FTS，不能讓收藏／收錄本身失敗。模型版本更換時禁止把不同維度或不同模型的向量混用。

### M5／M6 的最小證據契約

建議每則證據至少有 source_id、source_version／content_hash、locator、extracted_at、coverage 與可顯示片段。locator 依材料型態使用段落、影片起訖秒數、repository commit＋path＋symbol／行號。引用須能從實存來源解析，不能讓模型自造編號後直接顯示。

一張「可搬模組」建議至少回答：

1. 外部哪個函式／資料流程解決了什麼問題？
2. 自己哪個版本、哪個檔案或符號存在對應缺口？
3. 技術棧、資料量、授權、來源權限或執行環境有何適用前提？
4. 最小變更與驗收方式是什麼？哪些效果仍是推測？
5. 使用者拒絕的原因是無關、已做過、成本太高、時機不對，還是證據不足？

本地 evidence 仍受 read_scope／outbound_consent 限制；「能讀本地」不代表「能送雲端」。生成前與存 proposal 前都重驗 target／材料版本；本地檢索後若不允許傳出片段，就以本地規則輸出或降低判斷強度。沒有足夠材料時輸出待確認，不用預設 confidence 代替證據。

## 8. 第 F 節路線圖的修訂建議

原第 F 節方向可保留，但要修正「既有安全修正狀態」、「向量基礎的先後依賴」與「專案建議的差異化假設」。不直接覆寫原文件，避免把待討論提案混進既有工作。

| 原方向 | 本輪證據帶來的修訂 |
|---|---|
| Phase 0：驗證、權限與安全 | 目前已有多項稽核修正，應完成其原有驗證；不重新當作全部未做，也不在這輪代為宣告完成 |
| Phase 1：可信資料、snapshot、transcript、vector 去重 | 原文與 transcript 可獨立做；向量去重必須先有帶版本的 embedding 基礎。完整 monolith snapshot 不必對所有 radar 候選開啟 |
| Phase 2：sqlite-vec、profile、門檻與解釋 | 明示 profile／score breakdown／候選上限可提前，不必等 embedding；sqlite-vec 的直接參考是 Prismis |
| Phase 3：專案建議、模組與成本 | Brain 已有專案建議；提升門檻為外部與本地兩邊證據、適用前提、版本檢查及最小驗證，不以多一張 LLM 卡片當成果 |

建議施工順序：

**第一切片：讓每日雷達更值得讀、成本可見。** M1＋M2 的小版本：先保留來源 metadata、明示 profile、硬排除／unknown 邊界、入選數量、逐項理由與統計，再接回既有分析。同步建立固定比較資料，避免新增權重後只能憑感覺。先不做自動 profile 改寫。

**第二切片：可查證內容與共享向量。** M5 先確立原文與 locator；M3 只接一個多語模型與有版本快取，再做 M4 的搜尋與 anchor 事件原型。字幕／轉錄及完整快照依主要輸入類型選一個先做，不同時全面展開。

**第三切片：只針對 OmniKeep 做有證據的建議原型。** 選一個外部模組、查出 OmniKeep 對應檔案與版本，產出完整證據卡；由 Ryan 判斷是否確實省下調研與試錯時間。先驗證這個價值，再擴到其他專案與自動監測。

**第四切片：操作同步與通知。** 內容品質成立後補 M7。除非現在確有滑卡丟操作或通知重送的資料，否則不把重造同步框架放到第一階段。

工作量只做相對評估：M1／M2 為中等；M3／M4 為中到大，受中文效果與 Windows extension 相容性影響；M5 中的原文定位為中等、通用網頁保存與影音轉錄為較大；M6 為較大且需反覆標註。本輪沒有以未驗證的天數當承諾。

## 9. 驗證：先證明比現在好，再增加複雜度

本輪沒有讀取正式資料庫來抽樣，也沒有跑外部 repository、下載模型或呼叫付費 LLM。以下是討論後施工需要建立的驗收資料與實驗，不是已通過的結果。

### 9.1 固定資料與人工真值

先做一份能重播的小型資料集，例如 50–100 則 metadata／文章，加上 Ryan 的相關性標註；涵蓋中英同事件、同網域不同主題、版本更新、標題相似但內容不同、未知領域、硬排除與來源失效。

另準備少量專案建議案例，包含「tags 相同但根本不適用」、「已在專案中實作」、「有實際缺口」、「有技術／授權／資料限制」。標註者需看來源與現有程式，不能用另一個 LLM 分數充當唯一真值。上述筆數是起始提案，非統計充分性的宣稱。

### 9.2 最小必要驗收

| 變更 | 必要驗收 |
|---|---|
| 候選閘門 | 明確 mute 不進深分析；缺資料不被當負向；數量額度可重播；每個排除／入選都有理由 |
| 評分／profile | snooze 不訓練偏好；顯式排除不被探索／配額覆蓋；profile 修改需差異確認與 base version |
| 成本 | 記錄候選數、入選數、各階段呼叫數／token、cache 命中、失敗數；有金額上限時測並發預留與失敗釋放 |
| 向量／搜尋 | 同模型同內容重用、變更失效、不混用模型；範圍先過濾；embedding 失敗仍可 FTS |
| 事件 | 中英改寫能成候選；同網域不同事件不誤合併；A-B-C 連鎖不成巨群；event_id 穩定、distinct sources 真去重 |
| 證據 | 引用能解析到保存材料；行號／秒數有效；重寫內容無法定位時不偽造精確位置；移動段落更新 locator |
| 專案建議 | 缺本地材料時不宣稱找出程式缺陷；生成期間撤回 consent／材料改版就中止或重算；顯示兩邊證據與未決前提 |
| 可靠性 | 分析失敗、沒有匹配、未分析分開；重試不重複建立 proposal／通知；備份還原包含來源與索引重建策略 |

### 9.3 決定是否繼續的觀察值

- 每日 top 10 中 Ryan 認為值得讀的比例，以及漏掉的重要候選；與目前排序在同一份候選上比較。
- 每個「值得讀」項目的分析呼叫數與成本；限制額度是否確實生效。
- 事件誤合併率與漏合併率分開記，不能只看文章數下降。
- 搜尋的已知問題能否在前幾名找回證據；中英查詢、精確套件名與符號分開看。
- 專案卡的採納／拒絕理由、證據可驗證率與節省的實際調研時間。單看「產出幾張卡」不代表有價值。

沒有先訂「提升 30%」之類數字，因為目前缺同一份資料的 baseline。先記錄現況，再與 Ryan 決定可接受門檻。

## 10. 討論入口與目前建議

需先決定 OmniKeep 下一階段的主要用途，因為三個入口會改變施工順序：

| 選項 | 先驗證的價值 | 第一刀 | 代價 |
|---|---|---|---|
| A：每日技術雷達，建議優先 | 少看廢文、知道為何推薦、限制分析成本 | M1＋M2＋固定評估資料 | 專案證據卡較晚出現，但先讓輸入品質站穩 |
| B：可查證的個人知識庫 | 存下的文章／影片之後找得到、能回到原文 | M5＋M3 的單一輸入類型 | 原始保存、轉錄與索引工作較重 |
| C：專案研究助理 | 新情報能指出自己專案的具體缺口與可搬模組 | 用 OmniKeep 做一張人工可驗證的 M6 原型 | 自動化覆蓋小，但最快驗證差異化假設 |

**我的建議是 A 做成最小可用版本，接著儘早做一個 C 原型；M5 只補原型所需的證據，完整 snapshot 與通用轉錄再依需求擴張。** 如果你最想要的其實就是專案研究助理，則直接選 C，暫時接受蒐集與比對仍有人工步驟。

這比同時重做收藏工具、RSS reader、影音轉錄、RAG 與 agent framework 更容易判斷值不值得持續做。討論確認 A／B／C 的主要目標後，才將第一切片轉成程式變更。

## 11. 本輪交付與限制

- 完成指定十個 GitHub clone，固定 commit；六套沿實際呼叫路徑深讀，四套依目標模組定向讀取。十個研究 clone 在 manifest 擷取時皆無工作樹變更。
- 新增本報告與 research manifest；保留原 competitive_landscape 與前份 survey，未覆寫待討論路線圖，也未修改產品功能、資料庫、既有稽核變更或外部 repository。
- 證據連結指向所讀 commit。授權以本次固定版本根目錄 LICENSE 與已讀檔案為依據；未逐一稽核所有子依賴或確認將來的發佈法務結論。
- 靜態檢查通過：81 個固定 commit 的競品程式引用、19 個本機程式引用，其檔案與行號均有效；十個 clone 的 HEAD 與 manifest 相符且工作樹乾淨。核對紀錄：`research_verification_2026-10-25.json`（研究時產生的本機紀錄，未隨本倉庫發布）。這些檢查確認引用位置與版本，並不代表功能或效果已通過測試。
- 未執行 OmniKeep 測試套件、競品測試、模型效能或正式推薦 A/B。不要把本報告當成這些驗證已通過。
- 下一步是與 Ryan 決定主要目標及第一切片；尚未進入產品開工。


