# 🔍 審查交接簡報 — 給 GPT-6.1 完整檢查用

> 寫於 2026-10-25。本專案剛由 **ZCode（GLM-5.3-Flash）** 在同一天內完成三輪大型開發（P0 提案引擎 → P1 滑卡系統 → P2 品味學習）。
> 開發過程**多次意外斷線、中途更換模型**——本文件列出所有已知事故點與債務，讓你知道該往哪裡查、用什麼順序查。

---

## ✅ 已解決：工作已全部提交（2026-10-25）

三個 commit（`383165a` 前端重建與基礎設施 → `4caddeb` P0 提案引擎 → `bd6e821` P1+P2 學習迴路）。審查時請以這三個 commit 的 diff 為主要檢視範圍（`git show --stat` 逐一過），`backups/`、`.zcode/`、`tests/.tmp/`、`node_modules/` 已加入 .gitignore 排除。

## 斷線／中斷事故清單（審查優先區）

| # | 事故 | 發生位置 | 現狀 | 建議檢查方式 |
|---|---|---|---|---|
| 1 | **heredoc 截斷**：寫入 database.py 時 heredoc 被截斷，Backup Runs DAO 只寫進一行註解 | `app/database.py` 尾端 | 已用 Edit 補完整，語法與 import 驗證通過 | 通讀檔尾 Backup Runs DAO 區塊前後，確認無重複定義或孤兒代碼 |
| 2 | **用戶中途重組桌面**：`CatOS_Astra`＋`cat-os` 合併成 `CatOS`，監看目標指向舊路徑 | `watch_targets` 表 | 已自動清理過期目標＋孤兒卡片，重新註冊 | `SELECT path FROM watch_targets` 逐一確認路徑存在；孤兒 `watch://`/`proposal://` items 已刪但可再驗 |
| 3 | **測試殘留洩漏正式 DB ×2**：測試直接寫 live DB，外洩 24+32 筆 `p1-test.example`/`p2-test.example` 項目、孤兒 behavior_events、測試用 topic weights | `tests/test_behavior_deck.py`、`tests/test_taste_relevance.py` | 已手動清理三輪 | 全庫搜尋 `p1-test.example`、`p2-test.example`、`taste-`/`rank-tag-` 開頭的 topic weights 應為 0 筆 |
| 4 | **線上服務多次強殺重啟**：P0/P1/P2 各重啟一次，遷移（`ALTER TABLE items ADD origin`、新建三張表）是在服務運行中對 live DB 執行 | `app/database.py init_db()` | 功能正常，51 測試全綠 | 檢查 init_db 的遷移邏輯是否冪等；重複呼叫無副作用 |
| 5 | **前端多次 build**：PWA Service Worker 有已知 stale precache 前科 | `static/dist/` | 最新 build 成功 | 手機端若載到舊殼，檢查 sw.js 版本與 precache 清單 |
| 6 | **中途換模型/斷線導致的風格斷層**：`app/watch/` 四個模組跨多輪撰寫 | `app/watch/redact.py`、`scanner.py`、`taste.py`、`relevance.py` | 各自通過測試 | 模組間命名與錯誤處理風格不一致處，屬可接受的債，列出即可 |

## 已知債務（有意留下、非遺漏）

1. **公網 API key 是預設值** `omnifs888`（`.env` + `app/config.py:12`），且 Cloudflare Tunnel 公開暴露 `/mcp`。**開源前第一優先修復**。
2. **CORS 全開**：`app/main.py` `allow_origins=["*"]`。
3. **測試無 DB 隔離**：測試直接寫正式 `omnikeep.db`（見事故 #3）。開源前應加測試專用 `DATABASE_PATH`。
4. **`test_queue_and_db` 與線上伺服器有競態**：live worker 會搶走測試佇列任務，單跑即過——非回歸。
5. **備份迴圈未經實戰夜**：`app/backup.py` 的 `backup_loop` 剛上線，還沒度過真實的每日 4 點觸發。rclone/git sink 完全未實測。
6. **relevance 的 Agnes 評審用寬鬆 except**：`app/watch/relevance.py` LLM 失敗時靜默回落本地卡（設計如此，但 except 範圍偏大）。
7. **radar relevance 每則情報開一個 fire-and-forget asyncio task**：只 print 錯誤，無重試/上限（`app/radar/scheduler.py::_safe_relevance_check`）。

## 快速驗證清單

```bash
python -m pytest -q                 # 應 51 passed（唯一容許失敗：test_queue_and_db 若伺服器同時在跑）
curl localhost:5000/health          # status: healthy, mcp_enabled: true
curl localhost:5000/api/watch/targets   # 3 個目標：CatOS / 桌面（L0 風險掃描）/ OmniKeep（自身），路徑皆存在
curl localhost:5000/api/behavior/deck   # 純 radar origin、未決策項目
# Telegram：/deck（四鍵滑卡會自動前進）、/proposals（提案核可）、/stats
```

## 三輪功能地圖

| 輪次 | 交付 | 核心新檔 |
|---|---|---|
| P0 | 監看中心：兩軸權限矩陣（讀取/外送）、L0 風險掃描、Agnes 指紋、提案卡＋分數修正、多 sink 備份、機密遮蔽層 | `app/watch/redact.py` `scanner.py`、`app/backup.py`、`app/routers/watch.py`、前端 `WatchDialog.vue` |
| P1 | Telegram 四鍵滑卡（👍/👎/⭐/💤）、行為事件表、origin 五路分流（radar/manual/agent/watch/proposal）、前端埋點＋📡雷達徽章 | `app/routers/behavior.py`、`telegram_bot.py` deck/proposals 區、`tests/test_behavior_deck.py` |
| P2 | 滑動→雷達主題權重（14 天半衰期）、deck ε-greedy 排序、雷達×指紋關聯提案、雷達摘要 Telegram 推播 | `app/watch/taste.py`、`app/watch/relevance.py`、`scheduler.py` 掛鉤 |

鐵律（有測試把關，勿破壞）：**💤 snooze 永遠不是訓練標籤**（`SWIPE_LABEL_EVENTS` 不含 snooze）；**外送雲端前一律過 `redact_text()`**（連「全開放」預設集也不能跳過）。

## 文件指針

- `docs/watch_proposals.md` — 監看/提案/備份/品味學習全功能文檔（P0-P2 已同步）
- `docs/mcp_integration.md` — MCP 工具清單（含新增 list_proposals / decide_proposal / scan_watch_target）
- `HANDOFF_TO_ZCODE.md` — 前一輪交接（UI 重構），內容仍有效
- 測試：`tests/test_watch_and_backup.py`（9）、`test_behavior_deck.py`（5）、`test_taste_relevance.py`（5）為三輪新套件
