# 語意搜尋的向量索引：檢查與重建

每個收藏收錄時，會由「標題＋摘要＋標籤」算出一個向量存在 `item_embeddings`（有 sqlite-vec 時同步到 `vec_items`）。查詢時用同一種方法算出查詢向量再比對。兩邊必須是**同一個模型**算出的，否則語意搜尋不會命中，只剩全文搜尋在運作。

依序嘗試，第一個成功的就是這個向量的來源，標記一律寫實際算出它的模型：

| 設定 | 向量來源 | 標記 |
|---|---|---|
| `OLLAMA_BASE_URL` 非空白（預設 `http://127.0.0.1:11434`） | 本機 Ollama 的 `/api/embed`、`EMBEDDING_MODEL` | 例如 `embeddinggemma-2` |
| Ollama 不通，且有 `OPENAI_API_KEY` | `OPENAI_BASE_URL` 的 embeddings 端點；`EMBEDDING_MODEL` 是 `embeddinggemma-2` 時改用 `text-embedding-3-small` | 例如 `text-embedding-3-small` |
| 都沒有，或端點失敗 | 本機雜湊投影 | `local-hash-v1` |

查詢時只比對和查詢向量同一個標記的列。Ollama 暫時不通、查詢退到雲端模型時，語意搜尋只會命中雲端模型算的列，其餘交給全文搜尋。

## 模型、維度與查詢格式（依電腦自動配）

- 每個模型的查詢格式與存的維度寫在 `app/embedding_profiles.py`。查詢套上該模型自己的指令格式，收藏本文照原樣算。`EMBEDDING_DIM` 預設 0，表示照表上的維度；填數字則所有模型都截到那個維度。
- 安裝時的掃描（`omnikeep_scan` 的 `embedding`）依顯示卡與記憶體挑本機模型，安裝 Skill 會自動下載並套用。
- 本機模型換掉之後，背景回填（每 10 分鐘看一次）會把舊模型的向量全部重算，`vec_items` 也會依新維度重建，不用手動跑指令。雲端端點照舊不自動重算，因為每筆都要付費。
- 2026-11 在 300 篇收藏、口語中文查詢上實測，第一名就命中原文的比例：

  | 模型 | 存的維度 | 第一名命中 |
  | --- | --- | --- |
  | qwen3-embedding:8b | 1024 | 0.853 |
  | qwen3-embedding:4b | 1024 | 0.80 |
  | harrier-oss-v1-0.6b | 1024 | 0.79 |
  | harrier-oss-v1-270m | 640 | 0.737 |
  | embeddinggemma-2（舊設定） | 256 | 0.70 |

  數據與腳本在 `backups/local-runtime-poc-20261114/round3`（不進 repo）。

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

- **實際來源怎麼判斷**：本機雜湊向量是確定性的，用收藏目前的文字重算一次，結果完全一樣就是本機向量，不必呼叫任何 API。收藏文字在建立索引之後改過的話，就無法證明，這類列會照標記計算。
- **被誤標的本機向量**：`--repair` 把標記改正，向量不變，不呼叫 API。
- **不是目前查詢模型算的**：`--reembed` 用目前設定重算。有金鑰時每個收藏呼叫一次 embeddings API，計畫會先列出呼叫次數。
- **已分析但沒有向量的收藏**：`--reembed --include-missing` 會一併計算。探索（預設關閉的實驗功能，在 設定 › 實驗功能 開啟）抓到、還沒分析的暫存收藏不算在內。
- **已刪除收藏的向量**：刪除收藏時會一併刪掉它在 `item_embeddings` 與 `vec_items` 的向量。舊版沒有這一步，留下來的向量會佔掉近鄰查詢的名額（查到後才因為找不到收藏被丟掉）。`--prune-orphans` 把這些向量清掉，不呼叫 API。

```bash
python scripts/rebuild_embeddings.py --repair            # 只顯示會改什麼
python scripts/rebuild_embeddings.py --repair --yes      # 執行
python scripts/rebuild_embeddings.py --reembed --yes
python scripts/rebuild_embeddings.py --prune-orphans --yes
```

## 相似度怎麼算

`vec_items` 建表時沒有指定距離，近鄰查詢的 `distance` 是 L2 距離。程式不拿它當相似度：取回近鄰時用 sqlite-vec 的 `vec_distance_cosine` 算每一筆的 cosine 距離，相似度是 `1 - cosine 距離`，和沒有 sqlite-vec 時的 numpy 路徑算出來的數字一致。近鄰的挑選仍依 L2：向量都是單位長度時兩種順序相同，不是單位長度的向量（相容端點回傳後照原樣存的）可能排不進候選。

## 安全設計

- 沒加 `--yes` 一律只列出計畫，不寫入。
- 寫入前先存 `BACKUP_DIR/omnikeep-prerebuild-<時間>.zip`。要復原時，用 `python scripts/restore_backup.py <那個 zip> --yes` 還原（先停止 OmniKeep，見 [backup_restore.md](backup_restore.md)）。
- 重算時只有拿到目前模型的向量才會覆蓋舊的。端點失敗時會退回本機雜湊，這種結果直接丟棄；連續 3 次就停止並回報，不會把整個索引換成本機向量。

## 建議的升級步驟（主力桌機）

1. 先執行檢查，看「Queries use」是哪個模型，以及各類各有幾列。
2. 沒有設 `OPENAI_API_KEY`：通常只需要 `--repair --yes`。
3. 有設 `OPENAI_API_KEY`：`--reembed --yes`，必要時加 `--include-missing`。計畫列出的次數就是 API 呼叫次數。
