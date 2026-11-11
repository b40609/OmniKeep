# 🔌 OmniKeep MCP 整合指南

外部的 coding agent（Claude Code、Codex、Antigravity 等）可以透過 Model Context Protocol（MCP）查詢、寫入 OmniKeep。

**一般使用者不用手動設定。** 安裝腳本（`scripts/install.ps1`、`scripts/install.sh`）最後會執行 `scripts/register_agents.py`，把 stdio MCP 與 `omnikeep-setup` Skill 註冊到這台電腦的 Claude Code、Codex、Antigravity。裝好後開一個新的 agent session 就能用。

下面是給要手動設定，或要從別台電腦連進來的人看的。

---

## 用哪一種連線

| 情況 | 連線方式 | 金鑰 |
| :--- | :--- | :--- |
| agent 和 OmniKeep 在同一台電腦 | stdio：agent 自己啟動 `mcp_server.py` | 不用。agent 的設定檔裡不放任何金鑰 |
| agent 在別台電腦 | Streamable HTTP：`/mcp-http`，經 Tailscale | 要。每個請求帶 `Authorization: Bearer <存取金鑰>` |

- 舊的 SSE 端點（`/mcp/sse`、`/mcp/messages`）還保留給只支援 SSE 的 client，一樣要帶金鑰。新的設定請用 Streamable HTTP。
- Docker 安裝沒有 stdio：映像裡沒有 `mcp_server.py`（見 `Dockerfile`）。`/mcp-http` 由主服務提供，容器裡也有，但沒有實測過，註冊也要自己來。

---

## 同一台電腦：stdio

`scripts/register_agents.py` 做的事：

| agent | 註冊方式 |
| :--- | :--- |
| Claude Code | `claude mcp add -s user omnikeep -- <python> <OmniKeep>/mcp_server.py` |
| Codex | `codex mcp add omnikeep -- <python> <OmniKeep>/mcp_server.py` |
| Antigravity | 在 `~/.gemini/config/mcp_config.json` 的 `mcpServers` 加上 `omnikeep` |

- `<python>` 是 OmniKeep 資料夾裡 `.venv` 的 Python：Windows 是 `.venv\Scripts\python.exe`，macOS、Linux 是 `.venv/bin/python`。沒有 `.venv` 時，才用執行這個腳本的 Python。
- 找不到 `claude`、`codex` 指令時，改成直接寫設定檔（`~/.claude.json`、`~/.codex/config.toml`）。
- Antigravity 的舊位置 `~/.gemini/antigravity/mcp_config.json` 不會動；裡面有 `omnikeep` 時只會提醒。
- 已經有別的 `omnikeep` 設定時不覆蓋；要換成這次的安裝，加 `--force`（會留 `.bak`）。
- 存取金鑰由 `mcp_server.py` 自己讀，所以 agent 的設定檔裡沒有金鑰。

重新註冊，或先看會做什麼：

```bash
python scripts/register_agents.py --dry-run      # 只列出會做的事
python scripts/register_agents.py                # 偵測到的 agent 全部註冊
python scripts/register_agents.py --agents codex,antigravity --skip-skills
```

### 其他 agent：手動設定

支援 stdio MCP 的 agent 都可以接。指令是 `.venv` 裡的 Python 加上 `mcp_server.py` 的完整路徑：

```json
{
  "mcpServers": {
    "omnikeep": {
      "command": "C:\\Users\\<你>\\OmniKeep\\.venv\\Scripts\\python.exe",
      "args": ["C:\\Users\\<你>\\OmniKeep\\mcp_server.py"]
    }
  }
}
```

- 不要寫 `"command": "python"`：安裝腳本把依賴裝在 `.venv`，系統的 Python 沒有這些依賴時，MCP 會啟動失敗。
- macOS、Linux 把指令換成 `<OmniKeep>/.venv/bin/python`。
- 設定檔的位置與外層格式每個 agent 不同，以該 agent 的文件為準。

---

## 別台電腦：Streamable HTTP

先照 [Tailscale 部署文件](tailscale_pwa_deploy.md) 用 `tailscale serve` 把 OmniKeep 開給自己的 tailnet。不要把服務公開到網際網路。

- **端點**：`https://<主機名>.<tailnet 名>.ts.net/mcp-http`
- **金鑰**：每個請求都要帶 `Authorization: Bearer <存取金鑰>`，或 `X-API-Key: <存取金鑰>`。不接受放在網址參數裡的金鑰。存取金鑰是 OmniKeep 主機 `.env` 裡的 `API_KEY`，請自己複製，不要貼進聊天。
- **Host 白名單**（`app/mcp_http.py`，防 DNS rebinding）：只接受下列名稱，其他一律回 421。
  - `127.0.0.1`、`localhost`、`[::1]`。
  - 這台主機的 Tailscale 名稱與 Tailscale IP。OmniKeep 啟動時用 `tailscale status --json` 找一次；Tailscale 比 OmniKeep 晚啟動的話找不到，要重啟 OmniKeep。
  - `.env` 的 `MCP_ALLOWED_HOSTS`：逗號分隔，例如 `MCP_ALLOWED_HOSTS=box.tail1234.ts.net`。用自訂網域或其他反向代理的名稱連線時，要加在這裡，改完重啟 OmniKeep。

**別台電腦的註冊目前沒有自動化。** `scripts/register_agents.py` 只做 stdio，要在那台電腦上自己加。Claude Code 的寫法（[官方文件](https://code.claude.com/docs/en/mcp)）：

```bash
claude mcp add --transport http omnikeep --scope user https://<主機名>.<tailnet 名>.ts.net/mcp-http \
  --header "Authorization: Bearer <存取金鑰>"
```

- 其他 agent：照它的文件新增一個 Streamable HTTP 的 MCP 伺服器，網址與標頭同上。
- 金鑰會留在那台電腦的 agent 設定裡，只在自己的裝置上做。
- 金鑰外洩時，在 OmniKeep 主機執行 `python scripts/rotate_api_key.py` 換一把，重啟服務，再更新每一台 client。指令不會把金鑰印出來。

---

## 🛠️ 工具清單（25 個）

以 `app/mcp_server.py` 裡的 `@mcp.tool()` 為準。

### 查詢（8 個）

| 工具 | 參數 | 說明 |
| :--- | :--- | :--- |
| `search_brain` | `query`、`category`、`limit`（預設 5，最多 20）、`is_starred` | 全文檢索，回傳精簡的摘要卡（標題、標籤、白話核心） |
| `hybrid_search_brain` | `query`、`category`、`is_starred`、`is_read`、`limit`（預設 5） | 全文檢索加向量語意檢索，用 RRF 合併；關鍵字對不上時也找得到相關內容 |
| `get_item_architecture` | `item_id` | 單一項目的 L1 摘要與 L2 深入分析，不含原文 |
| `get_item_raw` | `item_id`、`max_chars`（預設 2500） | 原文節錄；要看原始程式碼或逐字引述時才用 |
| `get_item_detail` | `item_id`、`include_raw`（預設 false） | 同 `get_item_architecture`；`include_raw=true` 時附上原文節錄 |
| `list_recent_items` | `triage_status`（`inbox`、`starred`、`archived`、`all`）、`category`、`limit`（預設 5） | 列出最近的項目 |
| `read_sql_query` | `query`、`limit`（預設 50） | 唯讀 SQL（`SELECT`、`PRAGMA`、`EXPLAIN`、`WITH`）；連線本身是唯讀的，寫入會被拒絕 |
| `ask_brain_synthesis` | `topic`、`top_k`（預設 5） | 找出和主題相關的多篇項目，交給 AI 寫跨篇比較 |

### 寫入（3 個）

| 工具 | 參數 | 說明 |
| :--- | :--- | :--- |
| `save_to_brain` | `content_or_url`、`category` | 存入網址、筆記或程式碼片段，照一般流程分析 |
| `writeback_insight` | `title`、`summary`、`architecture_details`、`category`、`tech_tags`、`related_item_id` | 把和 agent 討論出的結論寫成一筆新項目；給 `related_item_id` 會建立引用關聯 |
| `update_item_status` | `item_id`、`is_read`、`is_starred` | 標記已讀或加星標 |

### 專案監看與提案（3 個，實驗功能）

| 工具 | 參數 | 說明 |
| :--- | :--- | :--- |
| `list_proposals` | `status`（預設 `pending`）、`limit`（預設 10） | 列出提案卡 |
| `decide_proposal` | `proposal_id`、`approve`、`user_impact`、`user_confidence`、`user_effort`、`reason` | 核准或略過提案，可以修正分數 |
| `scan_watch_target` | `target_id`（留空掃全部） | 掃描監看目標 |

### 首次設定（11 個）

`omnikeep-setup` Skill 用的工具。只有 `omnikeep_apply_setup`、`omnikeep_ingest`、`omnikeep_run_radar`、`omnikeep_import` 會寫入；工具不會回傳任何金鑰，只回「已設定」與末四碼。

| 工具 | 說明 |
| :--- | :--- |
| `omnikeep_scan` | 硬體、OmniKeep 狀態、已接的 AI 管道、上次的答案、書籤與星標筆數 |
| `omnikeep_peek` | 解析一個網址，不跑 AI、不存 |
| `omnikeep_check_sources` | 驗證候選的雷達來源，首頁會自動找 RSS |
| `omnikeep_list_provider_options` | AI 管道的選項卡片與目前的設定 |
| `omnikeep_open_settings` | 指向設定頁某個分頁或某張卡片的連結 |
| `omnikeep_test_provider` | 用已存的金鑰送一筆小請求測試 |
| `omnikeep_preview_setup` | 驗證答案 JSON，回傳設定差異與確認碼，不寫入 |
| `omnikeep_apply_setup` | 套用設定，要帶確認碼 |
| `omnikeep_ingest` | 分析一個網址並存入 |
| `omnikeep_run_radar` | 跑一次雷達巡檢並產生摘要 |
| `omnikeep_import` | 匯入書籤、GitHub 星標、Pocket 匯出檔、OPML |

### 資源（4 個）

`omnikeep://stats`（各狀態筆數）、`omnikeep://schema`（資料表說明）、`omnikeep://golden-queries`（常用查詢範例）、`omnikeep://categories`（分類清單）。
