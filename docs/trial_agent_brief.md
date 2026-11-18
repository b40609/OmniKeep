# OmniKeep 新使用者實測任務書（給測試 agent）

你扮演第一次用 OmniKeep 的同事：從零安裝、照安裝 skill 設定、大量丟連結、找收藏，然後交一份詳細的實測回報。目標是找出新使用者會卡住、看不懂、覺得品質差的地方，不是證明它能用。

建議模型：Gemini 3.8 Flash，thinking_level high。全部用繁體中文（台灣用語）回報。

## 硬性限制

這台電腦上已經有一套正式的 OmniKeep 在跑，不能碰到它：

- 不要讀寫 `C:\Users\user\Desktop\OmniKeep`，不要結束或重啟 5000 埠上的程式，不要動排程工作「OmniKeep Watchdog」。
- 安裝時一定要加 `-NoWatchdog -NoStart -AgentHome`（下面的指令已經寫好），否則會蓋掉正式那套的排程和 agent 設定。
- 不 commit、不 push、不開 issue、不對外發送訊息（Telegram 測試只用你自己建的測試機器人，沒有就略過）。
- 不讀、不印 `.env` 裡的金鑰。要呼叫 API 時，用 PowerShell 把 `API_KEY` 讀進變數再帶進請求標頭，不要把值印出來。
- 不要自己改 OmniKeep 的程式碼來繞過問題：遇到問題就記下來，換下一項繼續測。
- 伺服器、watcher 這類不會自己結束的程式，一律用下面的 `Start-Process` 在背景啟動，絕對不要在前景執行 `run.py`：前景會一直卡住，直到工具逾時、回合被中斷（2026-11-18 第一輪實測就是這樣斷掉的）。
- 先把回報寫進檔案，最後的回覆只用 10 行以內的摘要，並附上回報檔路徑。在 T3 上，Antigravity 交完最後回覆後有時不會結束回合，T3 等 15 分鐘沒動靜就會中斷它；只要檔案已經寫好，工作就不會白做。

## 1. 安裝（照新使用者會做的方式）

```powershell
$T = "$HOME\OmniKeep-trial"
git clone https://github.com/b40609/OmniKeep.git $T
powershell -NoProfile -ExecutionPolicy Bypass -File "$T\scripts\install.ps1" -InstallDir $T -NoWatchdog -NoStart -AgentHome "$HOME\OmniKeep-trial-agenthome"
Add-Content "$T\.env" "`nPORT=5097"
Start-Process "$T\.venv\Scripts\python.exe" run.py -WorkingDirectory $T -WindowStyle Hidden -RedirectStandardOutput "$T\..\omnikeep-trial.out.log" -RedirectStandardError "$T\..\omnikeep-trial.err.log"
```

等 `http://127.0.0.1:5097/health` 回 200。記下：安裝花了多久、哪一步最久、有沒有看不懂的訊息或警告。

`$T` 已經存在（之前測過）時，先問使用者要不要刪掉重來，不要自己刪。

## 2. 照安裝 skill 設定

讀 `$T\skills\omnikeep-setup\SKILL.md`，把自己當成那個 agent，從「1. 掃描」開始照著做。你的環境沒有掛 OmniKeep 的 MCP，所以 skill 裡的每個工具都改用 REST API 或網頁完成，對應關係自己從 `$T\app\routers` 和 `$T\mcp_server.py` 找。哪一步在 skill 裡寫得不清楚、跟畫面對不起來，都記下來。

用瀏覽器打開 `http://127.0.0.1:5097`（在這台電腦上不用登入）：

- 有沒有出現首次設定？每一步看得懂嗎？
- 「設定 › AI › 目前能用的功能」每一列寫的是真的嗎？試著照「想更好」的說明做，看說明夠不夠。
- 沒有自己的 AI 金鑰也要能分析：這是重點，確認免註冊的服務真的在工作。

## 3. 大量收錄（至少 30 筆）

每一類至少 3 筆，用你自己挑的真實、公開的連結，中英文都要有：

| 類型 | 要特別看 |
|---|---|
| GitHub 專案（大、小、冷門各有） | 有沒有架構圖、圖對不對、說明有沒有抓到重點 |
| 技術文章、部落格 | 摘要正確嗎、有沒有原文沒有的內容 |
| 新聞 | 分類、標題 |
| YouTube（有字幕、沒字幕、很長） | 沒字幕時怎麼處理、提示看得懂嗎 |
| Threads、X 貼文 | 抓不抓得到內容 |
| Instagram Reels、短影音 | 畫面上的字有沒有讀到 |
| PDF、論文 | 長文怎麼處理 |
| 直接貼一段文字當筆記 | |
| 抓不到的網址（要登入、404、亂打） | 錯誤訊息看不看得懂、會不會卡住佇列 |

收錄可以用網頁的「新增」，也可以用 `POST /api/ingest`。每一筆記下：

- 網址、類型、花了幾秒、成功或失敗
- 標題和摘要的品質（1 到 5 分，寫一句理由）
- 簡體字、中國用語、原文沒有的內容、明顯錯誤：抄原句當證據
- 由哪個 AI 服務回答（伺服器日誌 `omnikeep-trial.err.log` 裡看得到）

## 4. 找收藏（至少 15 次）

- 用口語描述去找（不要用標題裡的字），例如「上次那個比 grep 快的工具」。記下第一筆是不是你要的。
- 一分鐘內連續查好幾次，看超過免註冊每分鐘 2 次的限制時會怎樣：有沒有錯誤、警告，結果還合不合理。
- 試「提問」：問一個要綜合好幾篇收藏才能回答的問題，看答案和引用。

## 5. 其他順手看

- 閱讀頁：架構圖、表格、長文排版，在 1920x1080 和手機寬度各看一次。
- 設定頁每一頁點一遍，找看不懂的用詞。
- 重新整理、關掉分頁再打開，看會不會被要求登入。

## 6. 回報

寫成一份 Markdown，存到 `$HOME\OmniKeep-trial-report.md`，結構如下：

1. **一句話結論**：新同事照這個流程能不能自己裝好、用起來。
2. **卡住或出錯的地方**（最嚴重的放前面）：每一項寫重現步驟、實際看到什麼、預期是什麼、證據（日誌原文、截圖路徑、API 回應）。
3. **看不懂的地方**：用詞、說明、skill 和畫面對不起來的地方。
4. **收錄明細表**：每一筆一列（第 3 節的欄位）。最後統計：成功率、各類型的平均秒數與平均分數。
5. **搜尋明細表**：查詢、第一筆是什麼、對不對。
6. **建議**：最多 5 條，依影響排序。

沒測到的項目要寫明原因，不要略過不提。測完不要關掉 5097 的伺服器，讓使用者能接著看。
