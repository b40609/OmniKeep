# 🔭 監看中心 — 本地提案引擎（Local Proposal Engine）

OmniKeep 不再只是被動收藏雷達：它會**監看你自己機器上的專案**，對你的裝置主動提出風險與優化提案。一切在本機運作，跨用戶共享不在設計內（也永遠不會有）。

## 核心概念：兩條獨立的權限軸

| 軸 | 意思 | 選項 |
|---|---|---|
| **讀取** | OmniKeep 這個程式「看得到」什麼 | 檔名與結構 → README → 依賴清單 → 原始碼 → git 歷史 |
| **外送** | 哪些內容「可以送 Agnes」做雲端分析 | 話題摘要 → 文件 → 依賴 → 程式碼片段 → git 歷史 |

**一條鐵律凌駕所有設定：任何文字送出雲端前一律通過機密遮蔽層**（`app/watch/redact.py`）——API key、token、私鑰、賦值型機密一律替換成 `[REDACTED:種類]`，即使「全開放」預設集也不例外。

### 預設集
- 🔓 **全開放**：全部可讀可送（機密仍遮蔽）——圖方便的自用者
- ⚖️ **平衡**：文件＋依賴可讀可送，程式碼不出門——開源用戶預設
- 🔒 **嚴謹**：只讀檔名＋README，只送話題摘要
- ⚙️ **自訂**：兩軸逐項開關

## 運作流程

1. **註冊監看目標**（Web UI 監看中心，或 API）— 本地資料夾或桌面根目錄（L0 純檔名風險掃描）
2. **掃描**（手動或觸發 `POST /api/watch/targets/{id}/scan`）：
   - **L0 風險檢查**：只看檔名，比對危險命名（password／api_key／交易所金鑰對／`.pem`／`.env`…），命中即產生「風險提案卡」。純本地，不開任何檔案內容。
   - **專案指紋**：依讀取軸組裝素材（README／依賴／結構統計／git log），遮蔽後（若同意外送）交 Agnes 兩段式解構成「專案認知卡」，存入 `監看` 分類。素材未變（版本雜湊相同）就跳過，省 token。
3. **提案卡**（`提案` 分類）：結論句開頭 + 三維分數（🎯影響／🔍信心／🏗️成本）。可在 UI **核准／忽略**，並可**逐維修正分數**——修正值與 AI 原始值一併保存，是未來本地評分模型的校準燃料。同目標同來源 30 天內自動去重。

## MCP 工具（手機端可用）

- `list_proposals(status)` — 列出提案（預設 pending）
- `decide_proposal(proposal_id, approve, user_impact?, user_confidence?, user_effort?, reason?)` — 核可／忽略＋分數修正
- `scan_watch_target(target_id?)` — 觸發掃描（空 = 全部）

## 備份（第二大腦保險）

`app/backup.py` 每日於 `BACKUP_HOUR` 後自動備份 SQLite（透過線上備份 API，服務不停機），sink 自選：`local`（輪替 zip，預設）／`rclone`（40+ 雲端）／`git`（版本歷史）／`off`。設定見 `.env.example`。

## 相關檔案

| 檔案 | 角色 |
|---|---|
| `app/watch/redact.py` | 機密遮蔽層（內容 pattern + 檔名風險判定） |
| `app/watch/scanner.py` | L0 風險掃描 + 指紋生成（Agnes / 本地統計雙路徑） |
| `app/backup.py` | 多 sink 每日備份 |
| `app/routers/watch.py` | 監看／提案／備份 API |
| `frontend/src/components/modals/WatchDialog.vue` | 監看中心 UI（權限矩陣 + 提案卡 + 備份） |

## 路線圖位置

P0（已上線）= 監看 + 風險提案 + 指紋 + 備份。P1（已上線）= Telegram 滑卡（👍/👎/⭐/💤稍後）+ 行為事件落庫 + origin 分流。P2（已上線）= **品味學習**（滑動標籤即時回饋進雷達主題權重，14 天半衰期衰減；deck 以同一套權重排序並保留 4:1 探索間奏）+ **雷達×指紋關聯提案**（新雷達情報與監看專案標籤重疊 ≥2 時出提案卡，外送同意者交 Agnes 評審、否則本地保守出卡）+ 雷達摘要 Telegram 推播。

### P2 模組

| 檔案 | 角色 |
|---|---|
| `app/watch/taste.py` | 滑動→主題權重橋接（💤 永不進權重）+ deck ε-greedy 排序 |
| `app/watch/relevance.py` | 雷達×指紋關聯比對與提案（每情報每目標 30 天去重，每情報至多一張卡） |
| `app/radar/scheduler.py` | 掛鉤：雷達循環後觸發 relevance 檢查 + digest 推播 Telegram |
