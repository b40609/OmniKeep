---
name: omnikeep-review
description: 在桌機開發對話處理 OmniKeep 手機端送出的待決／核准實測工具，並按需求動態召回情境備案工具（Progressive Disclosure）。使用者說「清一下 OmniKeep 待實測清單」「看我核准的工具」「從 OmniKeep 找備案工具」時使用。Reviews approved OmniKeep tool candidates in desktop sessions and recalls on-demand tools.
---

# OmniKeep 工具評估與桌機實測閉環

這份 Skill 用來把使用者在 iPhone 17 Pro 端滑手機拍板後的工作，無縫銜接到桌機開發對話中完成實測與結果回寫。

## 核心原則

1. **只對人類核准的項目進 Layer 2**：背景推研固定止於 Layer 0（查重＋安全掃描）與 Layer 1（唯讀對照）；只有使用者在手機按過「核准進 L2 實測」（狀態為 `approved_l2`）的項目，才可以在隔離沙盒或專案副本實際執行或驗證。
2. **嚴格檢查安全徽章**：若安全狀態為 `executable_needs_review`（含可執行 CLI/MCP 或無 `SKILL.md`）或 `risk_flagged`，務必先檢視來源檔與安裝指令才可測試，不直接對主力環境執行未檢查腳本。
3. **不膨脹常駐上下文（Progressive Disclosure）**：低頻高價值的備案只保留在 OmniKeep `on_demand` 清單，不寫進全域常駐設定；真正遇到該場景再透過 `search_on_demand_tools` 召喚。

## 標準工作流程

> 呼叫方式：若目前 session 的 MCP 以 `review`／`full` profile 啟動，直接呼叫下列 MCP 工具；若為預設精簡 `core`（7 工具）模式，請以專案 `.venv` Python 呼叫 `<OmniKeep>/scripts/setup_cli.py` 對應子指令（`queue`、`decide`、`on-demand`），並用預設核心工具 `get_item_detail`、`writeback_insight`。

### 1. 拉取待實測項目

- 呼叫 `list_agent_queue(status="approved_l2")`（或執行 `scripts/setup_cli.py queue --status approved_l2`）查看使用者在手機核准進 Layer 2 的工單。
- 對要處理的項目呼叫 `get_item_detail(item_id)`；若需要檢查貼文一樓指令或社群留言反例細節，呼叫 `get_item_detail(item_id, include_raw=True)`。

### 2. 在隔離環境執行 Layer 2 驗證

- 對照評估紀錄裡的 `claims`（原作者宣稱）與 `community_counterpoints`（社群反例）：
  - 在臨時工作區或專案測試副本執行最小可行驗證。
  - 若本機同時安裝 OmniKit（`omnikit-eval`），依其定義的 `Keep / Improve / Update / Retire / Merge` 五態判定與現任工具對照。

### 3. 回寫實測定案

驗證完成後，呼叫 `record_agent_decision(...)` 將最終狀態寫回 OmniKeep（讓手機 App 的待辦與卡片狀態同步推進）：
- 確定導入並升級現有工作流：`decision="adopted"`，`note` 寫明導入位置與實測前後對比。
- 確認有用但僅限特定場景：`decision="on_demand"`，`trigger_when` 寫清楚精準觸發條件（供之後 `search_on_demand_tools` 召回）。
- 實測效果不如預期或相容性差：`decision="rejected"`，`note` 寫明拒絕證據，避免日後重複評估。
- 產出跨工具比較結論時，可額外呼叫 `writeback_insight(...)` 存進長期知識庫並關聯 `related_item_id`。

### 4. 按需召回情境備案

當使用者遇到特定瓶頸（例如大檔案解析太慢、特定框架除錯）時，先呼叫 `search_on_demand_tools(query="<情境關鍵字>")` 查看是否早已收過評估通過的備案工具，命中後再調用。
