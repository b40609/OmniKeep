# 🤖 OmniKeep Telegram 私人隨手採集 Bot

OmniKeep Telegram Bot 讓你無論在手機端（iPhone、Android）或電腦端，只要在任何 App（Twitter/X、Safari、Reddit、Telegram 群組）看到優質文章或技術段落，**「點擊分享傳給你的 Bot」**，後端即刻在數秒內完成 L1/L2 深度提煉與入庫！

---

## 🚀 3 步極速配置指南

### 第一步：取得 Telegram Bot Token
1. 在 Telegram 中搜尋官方機器人 **`@BotFather`**。
2. 發送 `/newbot`，依提示依序輸入：
   - 機器人名稱（例如：`Ryan Second Brain`）
   - 機器人帳號使用者名稱（必須以 `bot` 結尾，例如：`ryan_omnifs_bot`）
3. BotFather 會產生一組專屬 Token（格式如：`7123456789:AAFn_xxxxxxxxxxxxxxxx`）。
4. 開啟 `c:\Users\user\Desktop\Hub\.env`，填入：
   ```env
   TELEGRAM_BOT_TOKEN=7123456789:AAFn_xxxxxxxxxxxxxxxx
   ```

---

### 第二步：啟動 Bot 並取得你的 User ID
1. 在終端執行：
   ```powershell
   python run_bot.py
   ```
2. 打開 Telegram，搜尋你剛建立的 Bot，點擊 **Start** 或發送隨意文字。
3. Bot 會主動回覆：
   > ⚠️ **OmniKeep Bot 尚未綁定擁有者**  
   > 你的 Telegram User ID 是：`987654321`
4. 將該數字貼回 `.env`：
   ```env
   TELEGRAM_ALLOWED_USER_IDS=987654321
   ```
5. 重新啟動 `python run_bot.py`，即完成私有安全綁定（外人完全無法盜用你的 Bot 與 AI 額度）。

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
| `/stats` | 查看當前大腦庫存狀態（Inbox 待讀數、星標數、封存數、總計數）。 |
| `/inbox` | 快速列出最近 5 則未讀情報卡片，可直接在手機上點擊封存或星標。 |
| `/search [關鍵字]` | 隨身檢索大腦庫存，例如 `/search OpenHands`。 |
| `/help` | 查看使用說明與確認授權狀態。 |
