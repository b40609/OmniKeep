# 🔌 OmniKeep MCP (Model Context Protocol) 整合指南

OmniKeep 現已原生支援 **Anthropic Model Context Protocol (MCP)**，並提供 **雙模傳輸 (Local stdio / Remote SSE)**。
這意味著你的外部 Coding Agent（**Cursor、Codex、Claude Code、Claude Desktop、Antigravity**）以及手機端遠端 Agent（**ChatGPT App、Claude iOS**）可以直接把 OmniKeep 當作**長效外部第二大腦與決策回寫中樞**！

---

## 🛠️ MCP 提供的工具清單 (Exposed Tools)

| 工具名稱 | 參數 | 功能說明 |
| :--- | :--- | :--- |
| `search_brain` | `query`, `category`, `limit` (預設 5), `is_starred` | 毫秒級全文檢索（FTS5 + LIKE 混合容錯），回傳極簡輕量索引，**避免 Agent 上下文爆炸**。 |
| `get_item_architecture` | `item_id` | **Context 節食首選**：僅取得單一專案的 L1 白話痛點與 L2 深度技術架構/規格解構（無冗長原文）。 |
| `get_item_raw` | `item_id`, `max_chars` (預設 2500) | 僅在 Agent 需要審查原始程式碼、設定檔或原文逐字引述時單獨調用。 |
| `writeback_insight` | `title`, `summary`, `architecture_details`, `category`, `tech_tags`, `related_item_id` | **對話閉環**：將手機端深聊出的架構結論直接寫入 OmniKeep 第二大腦，並支援與庫存專案建立關聯圖譜。 |
| `save_to_brain` | `content_or_url`, `category` | 由 Agent 直接存入網址、程式碼片段或筆記，觸發 AGNES 3.0 自動兩段式解構。 |
| `list_recent_items` | `triage_status`, `category`, `limit` | 列出最近情報（支援 `inbox` 待讀、`starred` 星標、`archived` 封存、`all` 全部）。 |
| `update_item_status` | `item_id`, `is_read`, `is_starred` | 一鍵將項目標記為已讀／封存或加星標。 |
| `ask_brain_synthesis` | `topic`, `top_k` | 利用 AGNES 3.0 超大 Context Window，針對庫存多篇項目進行**跨篇橫向技術架構綜述與選型對比**。 |

---

## 🌐 遠端接入方式：Remote MCP (SSE over Cloudflare Tunnel)

OmniKeep FastAPI (Port 5000) 已原生掛載 FastMCP SSE 端點，配合 Cloudflare Tunnel，即可在公網安全調用。

### 1. 連線位址與路徑
- **SSE 連線端點**: `https://<你的-cloudflare-tunnel-網址>/mcp/sse`
- **訊息端點 (自動握手)**: `https://<你的-cloudflare-tunnel-網址>/mcp/messages`

### 2. 安全認證 (Bearer Token 防護)
REST 與遠端 MCP 請求均須攜帶 `.env` 中的 `API_KEY`，沒有預設憑證：
- **Header 方式**：`Authorization: Bearer <API_KEY>` 或 `X-API-Key: <API_KEY>`。
- 不接受 URL query token；SSE 連線與訊息請求均須帶入 Header。
- 執行 `python scripts/rotate_api_key.py` 可換 key，之後須重新啟動服務並私下更新客戶端設定。憑證不會顯示於命令輸出。

### 3. Remote Client 配置範例 (例如 Cursor / Claude Desktop Remote)
```json
{
  "mcpServers": {
    "omnikeep-remote": {
      "url": "https://<你的-cloudflare-tunnel-網址>/mcp/sse",
      "headers": {
        "Authorization": "Bearer <從本機 .env 私下填入 API_KEY>"
      }
    }
  }
}
```

---

## 💻 本地端接入方式：Local stdio

若在本機環境下使用 Cursor、Claude Desktop 或 Antigravity，可直接透過本機 stdio 模式連線：

### 1. Cursor IDE
在專案根目錄建立 `.cursor/mcp.json`，或於 Cursor Settings -> MCP 填入：
```json
{
  "mcpServers": {
    "omnikeep": {
      "command": "python",
      "args": [
        "C:/Users/user/Desktop/OmniKeep/mcp_server.py"
      ],
      "env": {
        "PYTHONIOENCODING": "utf-8"
      }
    }
  }
}
```

### 2. Antigravity IDE
在 `C:\Users\user\.gemini\antigravity\mcp_config.json` 的 `mcpServers` 區塊中加入：
```json
"omnikeep": {
  "command": "python",
  "args": [
    "C:\\Users\\user\\Desktop\\OmniKeep\\mcp_server.py"
  ],
  "env": {
    "PYTHONIOENCODING": "utf-8"
  }
}
```

### 3. Claude Desktop
編輯 `%APPDATA%\Claude\claude_desktop_config.json`：
```json
{
  "mcpServers": {
    "omnikeep": {
      "command": "python",
      "args": [
        "C:\\Users\\user\\Desktop\\OmniKeep\\mcp_server.py"
      ],
      "env": {
        "PYTHONIOENCODING": "utf-8"
      }
    }
  }
}
```
