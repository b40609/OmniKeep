# 🔑 帳號會話管理（Account Sessions）

OmniKeep 解析 Instagram Reels、Facebook 貼文、YouTube 會員影片等內容時，部分資料需要**登入狀態**才能取得完整內容。OmniKeep 採用三層防線設計，全部由用戶在自己機器上完成，**Session 只存本機、絕不上傳**。

---

## 三層防線總覽

| 優先級 | 機制 | 說明 | 適用 |
|---|---|---|---|
| 1 | **cookies.txt 匯入** | 於專案根目錄放置 `cookies.txt`（Netscape 格式），自動優先採用 | 所有平台，零依賴 |
| 2 | **CDP 會話橋接**（推薦） | 自動化 Chrome + DevTools Protocol，Chrome 自己吐解密後的 cookie | Windows Chrome 127+（App-Bound Encryption 時代標準解法） |
| 3 | **yt-dlp 直接提取** | 讀取本機瀏覽器 cookie DB | Firefox / 未啟用 ABE 的瀏覽器 |

> 為什麼不能直接 OAuth 綁定 IG/FB 帳號？Meta 已於 2024/12 廢止 Instagram Basic Display API，現行 API 需商業帳號 + App 審核且拿不到影片本體。Self-hosted 生態（yt-dlp、RSSHub）的通行做法就是「帶自己的 session」。

---

## 🚀 快速開始：Web UI 一鍵連結（推薦）

1. 打開 OmniKeep 工作台，點擊頂欄 **🔑 會話連結** 按鈕。
2. 面板會顯示：
   - 橋接模式與 cookie 數量（CDP :9222 · N cookies）
   - 各平台連結狀態（Instagram / Facebook / YouTube / X）
3. 點擊目標平台的 **登入** 按鈕 → 自動彈出 OmniKeep 專屬自動化 Chrome 視窗並導向該平台。
4. 在該視窗完成登入 → 面板 5 秒內自動轉為 **✓ 已連結**。
5. 完成。Session 永久保存在本機 profile，之後所有解析自動帶上會員狀態。

**首次使用**：若有社群來源項目但尚未連結任何平台，工作台會在載入後顯示一次性提示（可關閉，不再打擾）。

---

## 🔧 底層細節

### CDP 自動化 Chrome

- **獨立 profile**：`%LOCALAPPDATA%\OmniKeep\chrome-cdp`，與日常瀏覽器完全隔離，互不干擾。
- 為何不用你原本的 Chrome？Chrome 136+ 基於安全**封鎖預設 profile 的遠端除錯埠**，且 127+ 的 App-Bound Encryption 讓外部程式無法解密 cookie DB（yt-dlp #7271、#10927）。獨立 profile + CDP 是唯一穩定解。
- 橋接只會 `connect_over_cdp` 讀取 cookie，斷開時**不會關閉**該 Chrome。

### 相關設定（.env）

```env
# CDP bridge（以下皆有預設值，可不填）
BROWSER_CDP_PORT=9222
BROWSER_CDP_PROFILE_DIR=%LOCALAPPDATA%\OmniKeep\chrome-cdp
BROWSER_CDP_AUTOLAUNCH=true

# 傳統方式
BROWSER_COOKIE_SOURCE=chrome        # yt-dlp 提取來源（非 Chromium 系瀏覽器才有意義）
BROWSER_COOKIE_FILE=cookies.txt     # 放專案根目錄即自動優先
```

### cookies.txt 匯入法（替代方案）

1. Chrome 安裝擴充 **「Get cookies.txt LOCALLY」**。
2. 登入 instagram.com / facebook.com 後，於該分頁匯出 cookies.txt。
3. 放到專案根目錄（與 `run.py` 同層）→ 重新啟動即生效。

### YouTube 加值（選配）

yt-dlp 對公開影片免登入。若要更穩定的 metadata / 字幕來源，可申請免費的 YouTube Data API v3 key，未來版本將以 `YT_API_KEY` 整合進雷達排程（與 `GITHUB_TOKEN` 同模式）。

---

## 🩺 健康檢查與排障

```powershell
curl http://localhost:5000/health
# → session_bridge: { "mode": "cdp", "cdp_reachable": true, "connected_platforms": ["google"] }
```

| 症狀 | 處理 |
|---|---|
| mode 一直是 `none` | 自動化 Chrome 未啟動：於設定面板按任一「登入」自動拉起；或手動確認 `BROWSER_CDP_PORT` 未被占用 |
| 登入後仍顯示未連結 | 按「重新檢測」；登入的是日常瀏覽器而非自動化視窗的話，session 不會被橋接看到 |
| 解析仍失敗 | 平台改版屬正常週期， OmniKeep 的無 cookie 降級路徑仍會嘗試公開內容 |

## 🔒 隱私聲明

- Session cookie 只存在於**你自己的機器**（automation profile / cookies.txt / 暫存檔）。
- OmniKeep 不含任何遙測；cookie 不會被傳送到 OmniKeep 以外的任何伺服器（解析目標網站本身除外）。
