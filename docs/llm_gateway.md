# 本機 AI 轉接端點（給 claude-mem 用 Vertex 抵免額）

2026-11-18 起。程式在 `app/llm_gateway.py`，啟動檔 `run_gateway.py`。

## 做什麼

在 `127.0.0.1:5101` 開一個 OpenAI 相容的 `/v1/chat/completions`（另有 `/v1/models`、`/health`），內部用 OmniKeep 存在 `omnikeep.db` 的 Vertex AI 連線回答。別的程式（目前是 claude-mem）不必拿 Google 金鑰：金鑰仍加密存在資料庫，只在這個程式的記憶體裡解密；花的是 Vertex 專案的 GCP 抵免額。

- 只聽 127.0.0.1。呼叫要帶 `Authorization: Bearer <權杖>`，權杖每個來源一把，隨機產生、加密存在 `app_settings` 的 `_gateway.token.<來源>`。
- 思考程度固定 high，設定檔寫更低也會拉回 high。
- 支援串流（claude-mem 預設用串流）：等答案時每 15 秒送一行 SSE 註解，避免對方 90 秒閒置逾時；前 15 秒內就全部失敗時，照實回 429／502。

## 順序（`llm_gateway.json`，放在資料庫旁邊）

```json
{"port": 5101, "connections": [15, 16], "models": ["gemini-4-hydrogen", "gemini-3.8-flash"],
 "thinking_level": "high", "deadline_seconds": 280}
```

- 依序試每個連線；每個連線內依序試每個模型。
- 429、401／403（含 Spend cap）、餘額用完：同一個專案的其他模型也會被擋，直接換下一個連線。被 429 跳過的模型，等所有連線都輪過後再補試。
- 其他失敗（模型下架 404、5xx、空白回答）：同一個連線換下一個模型。
- 剛被限流或拒絕的連線，接下來一段時間（限流 60 秒、拒絕 10 分鐘）排到最後。
- 只會用 Vertex AI 卡片的連線；其他服務商的 id 寫進來也會略過。
- 改檔立即生效，不用重啟。2026-11-18 的設定是 c15 優先（帳號 2 的抵免額 2026-12-03 到期）；過了那天把 `connections` 改成 `[16, 15]`。

## 用量

每次嘗試都記兩處：`ai_usage`（照連線累計，和 OmniKeep 自己的呼叫一起出現在設定頁）與 `ai_usage_sources`（連線、日期、來源、模型）。查 claude-mem 花了多少：

```sql
SELECT day, connection_id, model, requests, failures, prompt_tokens, completion_tokens
FROM ai_usage_sources WHERE source = 'claude-mem' ORDER BY day DESC;
```

每次呼叫另有一行 log：`%LOCALAPPDATA%\OmniKeep\logs\llm_gateway.log`，例如
`chat source=claude-mem ok via=c15 model=gemini-4-hydrogen thinking=high ... attempts=c15/gemini-4-hydrogen:ok`。

## 安裝與啟動

```powershell
python scripts\llm_gateway_setup.py --claude-mem
```

建立 `llm_gateway.json` 與 claude-mem 的權杖，把 `~\.claude-mem\settings.json` 改成 `openai-compatible`（先備份成 `settings.json.bak-<時間>`；權杖直接寫進去，不會印出來）。之後 `scripts\watchdog.ps1`（每分鐘）看到 `llm_gateway.json` 就會啟動 `run_gateway.py`，停掉也會再拉起來。它和 `run.py` 是分開的程式，任一邊重啟都不影響另一邊。

要停用：刪掉 `llm_gateway.json`、結束 `run_gateway.py`，再把 claude-mem 的設定還原成備份。
