# 🔌 OmniKeep MCP (Model Context Protocol) 整合指南

OmniKeep 現已原生支援 **Anthropic Model Context Protocol (MCP)**。
這意味著你的外部 Coding Agent（**Cursor、Codex、Claude Code、Claude Desktop、Antigravity**）可以直接把 OmniKeep 當作**長效外部第二大腦（Shared External Memory）**！

---

## 🛠️ MCP 提供的工具清單 (Exposed Tools)

| 工具名稱 | 參數 | 功能說明 |
| :--- | :--- | :--- |
| `search_brain` | `query`, `category`, `limit`, `is_starred` | 毫秒級全文檢索（FTS5 + LIKE 混合容錯），搜尋白話重點與技術標籤。 |
| `get_item_detail` | `item_id` | 取得單一項目的完整 L1/L2 深度架構剖析與原始內容快照。 |
| `save_to_brain` | `content_or_url`, `category` | 由 Agent 直接存入網址、程式碼片段、架構設計或技術筆記，自動兩段式解構。 |
| `list_recent_items` | `triage_status`, `category`, `limit` | 列出最近情報（支援 `inbox` 待讀、`starred` 星標、`archived` 封存、`all` 全部）。 |
| `update_item_status` | `item_id`, `is_read`, `is_starred` | 透過 Agent 一鍵將項目標記為已讀／封存或加星標。 |
| `ask_brain_synthesis` | `topic`, `top_k` | 利用 Agnes AI 超大 Context Window，針對庫存多篇項目進行**跨篇橫向技術架構綜述與選型對比**。 |

---

## ⚙️ 各平台配置方式

### 1. Claude Desktop
編輯 `%APPDATA%\Claude\claude_desktop_config.json`：
```json
{
  "mcpServers": {
    "omnikeep": {
      "command": "python",
      "args": [
        "C:\\Users\\user\\Desktop\\Hub\\mcp_server.py"
      ],
      "env": {
        "PYTHONIOENCODING": "utf-8"
      }
    }
  }
}
```

---

### 2. Cursor IDE
在專案根目錄建立 `.cursor/mcp.json`，或於 Cursor Settings -> MCP 填入：
```json
{
  "mcpServers": {
    "omnikeep": {
      "command": "python",
      "args": [
        "C:/Users/user/Desktop/Hub/mcp_server.py"
      ],
      "env": {
        "PYTHONIOENCODING": "utf-8"
      }
    }
  }
}
```

---

### 3. Antigravity IDE
在 `C:\Users\user\.gemini\antigravity\mcp_config.json` 的 `mcpServers` 區塊中加入：
```json
"omnikeep": {
  "command": "python",
  "args": [
    "C:\\Users\\user\\Desktop\\Hub\\mcp_server.py"
  ],
  "env": {
    "PYTHONIOENCODING": "utf-8"
  }
}
```

---

### 4. 終端命令列獨立測試
可以直接在終端以 Python 測試運行：
```powershell
$env:PYTHONIOENCODING="utf-8"
python C:\Users\user\Desktop\Hub\mcp_server.py
```
