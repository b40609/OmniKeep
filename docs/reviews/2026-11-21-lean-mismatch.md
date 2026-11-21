# 修復報告：開源專案比對同名跨領域誤判與清單筆數不一致

- **日期**：2026-11-21
- **Commit SHA**：`f9be7358cc3297521dd1b2919a6b4c44cd76544d`（`f9be735`，已 push 至 `origin/main`）
- **對應問題**：摘要標題「AI 照抄你的程式碼，糾正要寫成自動檢查」（DB item `d487c00735ae`）中，演講提及「用 Lean 證明捲動清單元件不閃不抖」（應為 `leanprover/lean4`），卻連到 `QuantConnect/Lean`；且深析清單標示 `(4)` 與實際開源專案條數不一致、未連結項目缺少安全防碰撞與標示。

---

## 原因與證據（file:line）

1. **同名快速路徑未核對上下文與領域**（[app/research/tool_resolver.py:219-231](file:///C:/Users/user/Desktop/OmniKeep/app/research/tool_resolver.py#L219-L231)）
   - `judge_best_matching_repo` 先檢查 `c["name"].lower() == clean_target` 且 `stars >= 20` 時，直接回傳 `confidence = 0.95`，完全沒有核對 `mention_context` 與候選專案的 `description` / `topics`。
   - GitHub Search API 依星數降冪排序後，`QuantConnect/Lean`（★22,633，量化交易引擎）排在前面且 repo 名稱恰好為 `Lean`，於是跳過 LLM 評審直接誤判為吻合，連 `leanprover/lean4`（★10,095，名稱為 `lean4`）都沒機會進評審。
2. **比對失敗後未標記「待確認」且無連結項目會互相覆寫**
   - [app/research/tool_resolver.py:422-480](file:///C:/Users/user/Desktop/OmniKeep/app/research/tool_resolver.py#L422-L480)：當候選均不符領域時，原本設為 `status = "unverified"` 後又在收尾被濾除，若整個 `sub_entities` 全軍覆沒則 `pipeline.py` 會回退保留原始未處理資料。
   - [app/database.py:1772-1778](file:///C:/Users/user/Desktop/OmniKeep/app/database.py#L1772-L1778)：`save_citation` 僅以 `(source_parent_id, target_canonical_url)` 去重；若同時有多個無連結（`canon_url == ""`）的待確認專案，第二筆會覆寫第一筆。
3. **Telegram 深析清單把「庫內重複」混進「提及開源專案清單 (N)」**（[app/bot/telegram_bot.py:1217-1231](file:///C:/Users/user/Desktop/OmniKeep/app/bot/telegram_bot.py#L1217-L1231)）
   - 摘要卡片（`build_item_card_html`）有把 `[庫內重複]` / `[庫內競品]` / `[上位替代]`、`[台灣對等資源]`、`[疑似候選]` 與已驗證開源專案分開；但深析展開（`action == "detail"`）沒有分類，直接把 3 個開源專案加上 1 筆 `[庫內重複]` YouTube 影片通通算進 `📦 提及開源專案清單 (4)`。
   - `pstack` 在該則影片描述欄的連結為 `https://github.com/cursor/plugins/tree/main/pstack`，經 `normalize_canonical_url(..., repo_level=True)` 規範化後變成 `https://github.com/cursor/plugins`，未走 GitHub API 搜尋因此也沒有 `GitHub: owner/repo (★...)` 後綴，看起來像缺少對應的專案連結。

---

## 改了什麼

1. **[app/research/tool_resolver.py](file:///C:/Users/user/Desktop/OmniKeep/app/research/tool_resolver.py)**
   - 新增 `_extract_domain_tokens` 與 `_context_aligns_with_candidate`：exact-name fast-path 必須先確認 `mention_context` 與候選 `description` / `topics` 有非純語言名稱的實質領域交集（含中英核心概念對應），對不上時不走快速路徑，交由 LLM 評審或判定不吻合。
   - 更新 `TOOL_JUDGE_SYSTEM_PROMPT`（第 4 點）：明確要求同名但不同領域的候選必須拒絕（`matched_index: null`、`confidence < 0.4`）。
   - `resolve_mentioned_tools` 傳入包含 `default_title` 的 `judge_context` 供評審核對；若找不到領域吻合的專案，清空 `canonical_url`、設為 `status = "unverified"`、在 `reason` 加上 `[待確認]`，並於清單保留該 `unverified` 項目（不附錯誤連結）。
2. **[app/database.py](file:///C:/Users/user/Desktop/OmniKeep/app/database.py)**
   - `save_citation` 當 `canon_url == ""` 時，改以 `(source_parent_id, target_canonical_url='', LOWER(target_name))` 去重，避免多筆未附連結的 `[待確認]` 專案互相覆寫。
3. **[app/bot/telegram_bot.py](file:///C:/Users/user/Desktop/OmniKeep/app/bot/telegram_bot.py)**
   - 抽出共用方法 `_render_sub_entities_sections(sub_entities, *, detail_mode=False)`，讓摘要卡片與深析展開使用同一套分類規則（將 `[庫內競品]` / `[上位替代]` / `[庫內重複]`、`[台灣對等資源]`、`[疑似候選]` / `[待確認]` 與已驗證開源專案分區呈現），確保深析的 `📦 提及開源專案清單 (N)` 只計算並全量列出開源專案／模型，計數與列出的筆數完全一致。
   - `build_item_keyboard` 亦排除 `[待確認]` 項目；`action == "detail"` 加上 `max(0, 3800 - len(tools_block))` 防負數切片保護。
4. **[tests/test_tool_resolver.py](file:///C:/Users/user/Desktop/OmniKeep/tests/test_tool_resolver.py)**
   - 新增 `test_same_name_different_domain_lean_not_linked_to_quantconnect`
   - 新增 `test_resolve_mentioned_tools_marks_mismatched_domain_unverified_without_url`
   - 新增 `test_telegram_detail_count_matches_listed_open_source_projects`

---

## 測試輸出

### 目標測試（`pytest tests/test_tool_resolver.py tests/test_telegram_ux_enhancements.py tests/test_competitor_detector.py -v`）

```text
20 passed in 3.12s
```

新增項目皆通過：
- `tests/test_tool_resolver.py::test_same_name_different_domain_lean_not_linked_to_quantconnect PASSED`
- `tests/test_tool_resolver.py::test_resolve_mentioned_tools_marks_mismatched_domain_unverified_without_url PASSED`
- `tests/test_tool_resolver.py::test_telegram_detail_count_matches_listed_open_source_projects PASSED`

### 全量後端測試（`pytest -q`）

```text
1406 passed, 2 skipped, 1 warning in 213.71s (0:03:33)
```

---

## 之後可以做

1. **monorepo 子路徑保留**：像 `https://github.com/cursor/plugins/tree/main/pstack` 這類明確指向子外掛目錄的連結，`normalize_canonical_url` 目前會截斷到 repo 根目錄 `cursor/plugins`；可評估對 `sub_entities` 的 `target_canonical_url` 保留 `/tree/.../subpath` 或另外記錄顯示網址，避免與單一獨立倉庫混淆。
2. **GitHub 搜尋補上下文查詢**：當專案名稱為短字或常見英文單字（例如 5 字元以下如 `Lean`、`Dash`）且首次純名稱搜尋結果未含目標領域 repo 時，可用 `名稱 + 領域英文關鍵字`（如 `Lean theorem prover`）補查一次 GitHub API，提升命中 `leanprover/lean4` 的機率。
3. **既有資料庫舊資料清理**：`omnikeep.db` 中已收錄的 `d487c00735ae` 與 `fc7c9f7e2f7e` 仍留有舊的 `QuantConnect/Lean` 關聯，若有需要可另行提供一次性腳本或以「重新分析」功能重跑修正（本次依規範未更動正式資料庫）。
