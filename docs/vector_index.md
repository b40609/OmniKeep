# 語意搜尋的向量索引：檢查與重建

每個項目收錄時，會由「標題＋摘要＋標籤」算出一個向量存在 `item_embeddings`（有 sqlite-vec 時同步到 `vec_items`）。查詢時用同一種方法算出查詢向量再比對。兩邊必須是**同一個模型**算出的，否則語意搜尋不會命中，只剩全文搜尋在運作。

依序嘗試，第一個成功的就是這個向量的來源，標記一律寫實際算出它的模型：

| 設定 | 向量來源 | 標記 |
|---|---|---|
| `OLLAMA_BASE_URL` 非空白（預設 `http://127.0.0.1:11434`） | 本機 Ollama 的 `/api/embed`、`EMBEDDING_MODEL` | 例如 `embeddinggemma-2` |
| Ollama 不通，且有 `OPENAI_API_KEY` | `OPENAI_BASE_URL` 的 embeddings 端點；`EMBEDDING_MODEL` 是 `embeddinggemma-2` 時改用 `text-embedding-3-small` | 例如 `text-embedding-3-small` |
| 都沒有，或端點失敗 | 本機雜湊投影 | `local-hash-v1` |

查詢時只比對和查詢向量同一個標記的列。Ollama 暫時不通、查詢退到雲端模型時，語意搜尋只會命中雲端模型算的列，其餘交給全文搜尋。

## 什麼時候需要處理

- **從 2026-11-03（`a7954f4`）之前的版本升級**：舊版遇到沒金鑰或端點失敗時，會用本機雜湊算向量，卻標成 `text-embedding-3-small`。舊版的端點又固定是 `api.openai.com`，用 DeepSeek、Ollama 等相容服務時一律失敗，所以舊資料很可能全是這種向量。
- 改了 `OLLAMA_BASE_URL`、`OPENAI_API_KEY`、`EMBEDDING_MODEL`、`OPENAI_BASE_URL` 或 `EMBEDDING_DIM` 之後。
- 伺服器日誌出現 `Query embeddings use model … stored vector(s) were indexed with …`。

## 指令

在專案目錄執行，使用和伺服器相同的 `.env`；伺服器可以繼續執行。

```bash
python scripts/rebuild_embeddings.py
```

只檢查、不寫入：列出各標記的數量、實際來源，以及需要處理的列。

- **實際來源怎麼判斷**：本機雜湊向量是確定性的，用項目目前的文字重算一次，結果完全一樣就是本機向量，不必呼叫任何 API。項目文字在建立索引之後改過的話，就無法證明，這類列會照標記計算。
- **被誤標的本機向量**：`--repair` 把標記改正，向量不變，不呼叫 API。
- **不是目前查詢模型算的**：`--reembed` 用目前設定重算。有金鑰時每個項目呼叫一次 embeddings API，計畫會先列出呼叫次數。
- **已分析但沒有向量的項目**：`--reembed --include-missing` 會一併計算。雷達還沒分析的暫存項目不算在內。
- **已刪除項目的向量**：不影響搜尋，不處理。

```bash
python scripts/rebuild_embeddings.py --repair            # 只顯示會改什麼
python scripts/rebuild_embeddings.py --repair --yes      # 執行
python scripts/rebuild_embeddings.py --reembed --yes
```

## 安全設計

- 沒加 `--yes` 一律只列出計畫，不寫入。
- 寫入前先存 `BACKUP_DIR/omnikeep-prerebuild-<時間>.zip`。要復原時，用 `python scripts/restore_backup.py <那個 zip> --yes` 還原（先停止 OmniKeep，見 [backup_restore.md](backup_restore.md)）。
- 重算時只有拿到目前模型的向量才會覆蓋舊的。端點失敗時會退回本機雜湊，這種結果直接丟棄；連續 3 次就停止並回報，不會把整個索引換成本機向量。

## 建議的升級步驟（主力桌機）

1. 先執行檢查，看「Queries use」是哪個模型，以及各類各有幾列。
2. 沒有設 `OPENAI_API_KEY`：通常只需要 `--repair --yes`。
3. 有設 `OPENAI_API_KEY`：`--reembed --yes`，必要時加 `--include-missing`。計畫列出的次數就是 API 呼叫次數。
