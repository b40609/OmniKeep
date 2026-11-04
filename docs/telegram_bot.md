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
4. 開啟 `.env`，填入：
   ```env
   TELEGRAM_BOT_TOKEN=your_bot_token_here
   ```

---

### 第二步：啟動 Bot 並綁定你的帳號
1. **推薦：隨主服務自動啟動。** 只要 `.env` 設好 `TELEGRAM_BOT_TOKEN`，`python run.py` 會在 FastAPI 啟動時自動內嵌啟動 Bot 輪詢（同時帶起任務 Worker 與雷達排程），不需要另外開進程：
   ```powershell
   python run.py
   ```
   > 分離部署（可選）：若你想把 Bot 跑在另一台機器／進程，才使用 `python run_bot.py`。注意**兩者同時跑會造成 getUpdates 409 衝突**，擇一即可。
2. **用配對連結綁定（建議）**：登入 OmniKeep 網頁，開啟側欄底部的「通知」，按「產生 Telegram 配對連結」，再用你的 Telegram 帳號開啟連結並按「開始」。
   - 連結 10 分鐘內有效、只能用一次，只在與 Bot 的私人對話裡有效。
   - 綁定結果會寫進 OmniKeep 讀取的那個 `.env`（`TELEGRAM_ALLOWED_USER_IDS`），不用重新啟動。
   - 已經有擁有者時，新綁定的帳號會另外通知原擁有者。
   - 分離部署時，網頁上的「已綁定」要等網頁服務重新啟動才會更新；Bot 本身立即生效。
3. **或手動設定**：對 Bot 發任何訊息，它會回覆你的 User ID：
   > ⚠️ **OmniKeep Bot 尚未綁定擁有者**  
   > ……或把你的 User ID `987654321` 填入 .env 的 TELEGRAM_ALLOWED_USER_IDS 後重新啟動。

   將該數字填入 `.env` 後重新啟動 `python run.py`：
   ```env
   TELEGRAM_ALLOWED_USER_IDS=987654321
   ```

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
