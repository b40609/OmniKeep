# 🤖 OmniKeep Telegram 私人隨手採集 Bot

OmniKeep Telegram Bot 讓你無論在手機端（iPhone、Android）或電腦端，只要在任何 App（Twitter/X、Safari、Reddit、Telegram 群組）看到優質文章或技術段落，**「點擊分享傳給你的 Bot」**，後端即刻在數秒內完成 L1/L2 深度提煉與入庫！

---

## 🚀 3 步極速配置指南

### 第一步：取得 Telegram Bot Token
1. 在 Telegram 中搜尋官方機器人 **`@BotFather`**。
2. 發送 `/newbot`，依提示依序輸入：
   - 機器人名稱（例如：`My OmniKeep Brain`）
   - 機器人帳號使用者名稱（必須以 `bot` 結尾，例如：`my_omnikeep_bot`）
3. BotFather 會產生一組專屬 Token（格式如：`7123456789:AAFn_xxxxxxxxxxxxxxxx`）。
4. 登入 OmniKeep 網頁，開啟側欄底部的「設定 › Telegram」，貼上 Token，按「測試 Bot」確認後儲存。Token 加密存進資料庫，Bot 立即連線，不必重新啟動。
   （舊做法：在 `.env` 寫 `TELEGRAM_BOT_TOKEN=...` 仍然有效，但 App 內的值優先。）

---

### 第二步：啟動 Bot 並綁定你的帳號
1. **推薦：隨主服務自動啟動。** 只要設好 Bot Token，`python run.py` 會在 FastAPI 啟動時自動內嵌啟動 Bot 輪詢（同時帶起任務 Worker 與雷達排程），不需要另外開進程：
   ```powershell
   python run.py
   ```
   > 分離部署（可選）：若你想把 Bot 跑在另一台機器／進程，才使用 `python run_bot.py`。注意**兩者同時跑會造成 getUpdates 409 衝突**，擇一即可。
2. **用配對連結綁定（建議）**：登入 OmniKeep 網頁，開啟側欄底部的「設定 › Telegram」（「通知」裡也有同一個按鈕），按「產生 Telegram 配對連結」，再用你的 Telegram 帳號開啟連結並按「開始」。
   - 連結 10 分鐘內有效、只能用一次，只在與 Bot 的私人對話裡有效。
   - 綁定結果存進資料庫（App 設定 `TELEGRAM_ALLOWED_USER_IDS`），不寫 `.env`，不用重新啟動。
   - 已經有擁有者時，新綁定的帳號會另外通知原擁有者。
   - 要移除某個帳號，在「設定 › Telegram › 已綁定的帳號」按 ✕ 後儲存，立即失效。
3. **或手動加入**：對 Bot 發任何訊息，它會回覆你的 User ID；把這個數字填進「設定 › Telegram › 已綁定的帳號」按「加入」並儲存。

Bot Token 也可以直接在「設定 › Telegram」輸入，儲存後 Bot 會用新的 Token 重新連線，不必重新啟動。

沒有配對連結、也不在名單裡的人，傳什麼都不會被綁定，也不能使用 Bot（舊版會把第一個傳訊息的人自動設為擁有者，已移除）。

---

## 📱 核心功能與互動卡片

### 1. 隨手轉發 / 貼上網址或長文
- 直接把任何網址（YouTube、GitHub、技術長文）或零散筆記傳給 Bot。
- Bot 會先回覆 `⚡ 已收到內容，正在由 AI 深入解析情報架構 (L1/L2)...`。
- 解析完成後自動原地更新為高密度情報卡：
  - **L1 標題與分類**
  - **白話核心痛點與解法**
  - **技術標籤清單**
  - **互動按鈕**：
    - `[⭐ 加星標 / ⭐ 已星標]`：即時寫入本地資料庫
    - `[📦 封存 / ✅ 已封存]`：看完隨手歸檔
    - `[📊 L2 深入剖析]`：點擊立即在 Telegram 吐出完整的技術架構解構報告
    - `[🌐 原始網址]`：跳轉至原始來源

---

### 2. 常用管理指令

| 指令 | 說明 |
| :--- | :--- |
| `/mode [heartbeat\|quiet]` | 切換互動模式（心跳原地推進 vs 安靜模式直接刷出卡片）。 |
| `/stats` | 查看當前大腦庫存狀態（Inbox 待讀數、星標數、封存數、總計數）。 |
| `/inbox` | 快速列出最近 5 則未讀情報卡片，可直接在手機上點擊封存或星標。 |
| `/search [關鍵字]` | 隨身檢索大腦庫存，例如 `/search OpenHands`。 |
| `/help` | 查看使用說明與確認授權狀態。 |
