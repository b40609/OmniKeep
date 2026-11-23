# 模型下架自動改用（Model Self-Heal）實作回報

- 日期：2026-11-23
- 範圍：備援鏈遇到 `not_found` 時，自動將已下架的卡片模型改用卡片目前的預設模型、同步更新用途 entry 與 `model_extra_body` 預設、清除冷卻、在設定頁顯示一行說明，並限制每條連線 1 小時內最多自動更換一次。

## 一、修改檔案與行號

1. `app/ai_connections.py`
   - `app/ai_connections.py:29`、`app/ai_connections.py:56-57`：新增 `import time`、`MODEL_SWITCH_COOLDOWN = 3600.0`、`_MODEL_SWITCH_PREFIX = "model_switch:"`。
   - `app/ai_connections.py:325-348`：新增 `_auto_extra_body()` 並調整 `apply_model_preset()`，改與前端 `frontend/src/lib/extraBody.ts` 的 `autoExtraBody` / `extraBodyAfterModelChange` 使用完全相同的規則——只有目前 `caps["extra_body"]` 等於舊模型的自動預設時，才會替換為新模型的預設（或回復卡片預設／移除）；使用者手動填寫的值（包含換往有 preset 的新模型時）一律保留不動。
   - `app/ai_connections.py:508-509`、`app/ai_connections.py:519`：手動 `update()` 更改模型或 `delete()` 刪除連線時，清除 `ai_meta` 內對應的 `model_switch:<id>` 紀錄；僅切換 `enabled` 等未改模型的更新則保留說明。
   - `app/ai_connections.py:531-557`：新增 `_read_model_switch()` 與 `model_switch_info()`，從既有 `ai_meta` 表讀出自動換模型說明（回傳 `{from, to, date, message}` 或 `None`）。
   - `app/ai_connections.py:560-632`：新增 `replace_retired_model(connection_id, dead_model, *, now=None)`：
     - 鎖內單一交易完成檢查與寫入；排除 `kind == "ollama"` 以及 `custom`、`omniroute`、`ollama` 或無 `models` 清單／無預設模型的卡片。
     - 僅在 `dead_model` 已不在卡片目前的 `models`、卡片預設 `model` 與 `dead_model` 不同，且距離上次自動換模型已滿 3600 秒（1 小時）時才更換。
     - 同步更新 `ai_connections.model`（若等於 `dead_model`，並以 `apply_model_preset` 處理 `caps["extra_body"]`）以及所有 `ai_slots` 中 `connection_id` 符合且 `model == dead_model` 的 entry（留空跟隨連線者維持空字串、指向其他模型者不動），並寫入審計紀錄。
     - 將「`模型 X 已下架，已自動改用 Y（YYYY-MM-DD）`」連同時間戳寫入 `ai_meta`，呼叫 `_changed(f"c{connection_id}")` 清除冷卻、失敗次數與舊 404 狀態並重置 provider 快取。
   - `app/ai_connections.py:727`：`describe_connection()` 回傳加上 `"model_switch": model_switch_info(conn.id)`，讓 `GET /api/ai/connections` 帶出說明。

2. `app/providers/__init__.py`
   - `app/providers/__init__.py:101-103`：建構 `Member` 時帶入 `conn.id` 與該 slot 實際解析出的 `model`（`Member(build_provider(conn, model), conn.status_key, conn.label, conn.id, model)`）。

3. `app/providers/chain.py`
   - `app/providers/chain.py:1-38`：更新模組開頭 docstring，寫明 `not_found` 會先呼叫 `ai_connections.replace_retired_model()`，符合條件則自動換模型、清冷卻、記錄說明並由下一條完成本次呼叫，否則才進 6 小時冷卻。
   - `app/providers/chain.py:75-97`：新增 `_try_replace_retired_model()`，並於 `Member.__init__` 新增選填參數 `connection_id` 與 `model`（保留舊 3 參數呼叫相容性）。
   - `app/providers/chain.py:145-155`：`ChainProvider._run()` 在 `info["kind"] == "not_found"` 時呼叫 `_try_replace_retired_model(member)`；若已更換，記錄 warning log 後直接 `continue` 換下一條連線（不同一次重試、不進入 `COOLDOWNS["not_found"]`、也不回寫舊 404 失敗到 `ai_status`）。

4. `frontend/src/lib/api.ts`
   - `frontend/src/lib/api.ts:456-457`：`AiConnection` 介面新增 `model_switch?: { from: string; to: string; date: string; message: string } | null`。

5. `frontend/src/components/settings/AiConnections.vue`
   - `frontend/src/components/settings/AiConnections.vue:519`：在「設定 › AI」的連線列標題區（模型與用途標籤下方）新增一行顯示 `conn.model_switch.message`，折疊與展開狀態下皆一眼可見。

6. `tests/test_model_self_heal.py`（新增）
   - `tests/test_model_self_heal.py:1-251`：新增 11 個測試案例，涵蓋會換與端對端備援鏈下一輪改用新模型、不換（仍在清單／`custom`／`omniroute`／`ollama`／卡片預設等於死模型）、用途 entry 同步更新與孤立覆寫更新、`extra_body` 預設新增／移除／回復卡片預設／保留手填值、1 小時節流與逾時後恢復、以及 `/api/ai/connections` 說明顯示與手動改模型後清除。

## 二、設計取捨

1. **說明與節流紀錄放 `ai_meta` 而非只放記憶體 `ai_status`**：
   - `ai_status.record_success()` / `record_failure()` 每次呼叫都會整筆覆寫該連線狀態，且重啟即清空；若放在 `ai_status`，只要下一次呼叫成功就會立刻洗掉「已自動改用」的說明，且會干擾 `ServiceStatusBanner`（判斷 `!o.ok`）與連線燈號。
   - 使用既有的 `ai_meta` 表（不改資料庫 schema）存 `model_switch:<id>`，重啟與後續成功呼叫都能保留說明，同時提供 1 小時內最多換一次的持久時間戳；`replace_retired_model()` 透過既有 `_changed(f"c{id}")` 直接清除 `ai_status` 的冷卻與剛剛寫入的 404 失敗，避免頂部誤亮錯誤橫幅。
2. **`Member` 顯式攜帶 `connection_id` 與 `model`**：
   - 直接從 `resolve(slot)` 帶入實際發送的模型名，而非只依賴 `provider.model`，可正確對應 slot 覆寫模型，也避免既有測試以 stub `Fake`（自帶假 `model` 名）取代 `build_provider` 時誤觸自動換模型。
3. **不原地重建舊 `ChainProvider` 的 `member.provider`**：
   - 經清點整個程式碼庫（`app/pipeline.py`、`app/brain.py`、`app/mcp_server.py`、`app/parsers/reel.py`），所有呼叫端每次執行皆經由 `get_provider()` / `get_primary_provider()` 取得備援鏈。
   - `_changed()` 已呼叫 `reset_providers()` 清空 `_chains` 快取，下一次呼叫會立即用新模型與新 `extra_body` 重建 provider，避免在舊 `ChainProvider` 裡多建一組不會再被用到的 `AsyncOpenAI` client。
4. **顯式排除 `ollama`**：
   - `provider_catalog.py` 中 `ollama` 卡片雖然填了 `models: ["qwen3:8b"]`，但本機 Ollama 模型為使用者自行 pull，並無固定官方清單，因此在 `replace_retired_model()` 中顯式排除 `kind == "ollama"` 與 `card_id == "ollama"`。
5. **說明放在連線折疊列頭（`.set-fold__head`）**：
   - 連線列預設折疊，將一行 `text-xs text-muted-foreground` 放在 `.set-fold__head` 內模型名下方，使用者進「設定 › AI」不需逐條點開即可看見自動更換紀錄，也不額外增加展開區重複文案。

## 三、測試實際輸出

1. **局部後端測試**（`python -X utf8 -m pytest -q tests/test_model_self_heal.py tests/test_ai_connections.py tests/test_extra_body.py tests/test_catalog_remote.py tests/test_ai_failure_handling.py --basetemp="$env:LOCALAPPDATA/Temp/okpt/selfheal-focused" -p no:cacheprovider`）
   ```text
   164 passed, 1 warning in 37.94s
   ```
2. **前端測試與建置**（`cd frontend && npm test && npm run build`）
   ```text
   ℹ tests 221
   ℹ suites 0
   ℹ pass 221
   ℹ fail 0
   ℹ cancelled 0
   ℹ skipped 0
   ℹ todo 0
   ℹ duration_ms 1637.929

   ✓ built in 5.03s
   ```
3. **全量後端測試**（`python -X utf8 -m pytest -q --basetemp="$env:LOCALAPPDATA/Temp/okpt/selfheal" -p no:cacheprovider`）
   ```text
   1442 passed, 2 skipped, 1 warning in 211.17s (0:03:31)
   ```
   （上述 1 則 warning 為既有的 `google/genai/types.py:42 DeprecationWarning: '_UnionGenericAlias' is deprecated`。）

## 四、未做項目與已知限制

- **未做項目**：依指示未執行 `git commit`、`git push`，未重啟正式站（埠 5000），亦未操作 `.env` 或正式資料庫 `omnikeep.db`；因此未在正式站開瀏覽器截圖目視檢視 `AiConnections.vue`（已通過 `vue-tsc -b` 型別檢查、`vite build` 與 221 項前端測試）。
- **`model_extra_body` 同步邊界**：與前端 `extraBodyAfterModelChange` 相同，判斷是否為舊模型預設依賴目前卡片上的 `card["model_extra_body"]`。若未來更新 `provider_catalog.py` 時將已下架的舊模型同時從 `models` 與 `model_extra_body` 移除（受 `tests/test_extra_body.py:96-100` 檢核限制），且舊連線未記錄 `extra_body` 來源，則該殘留的舊 preset 會被視為無法與手填區分而保留原樣；另外 `app/catalog_remote.py` 的 `FIELDS` 目前未同步 `model_extra_body`，這兩點本次未越權改動。
