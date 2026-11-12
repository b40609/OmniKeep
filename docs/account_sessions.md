# 社群平台登入

OmniKeep 讀取 Instagram Reels、Facebook 貼文、YouTube 會員影片等內容時，有些要**登入**才看得到完整內容。登入一次，之後讀取時就會帶上登入狀態。有三種取得登入狀態的方式，都在你自己的電腦上完成，**登入狀態只存在這台電腦，不會上傳**。

入口：右上角頭像選單 ›「設定」› 收錄管道 ›「社群平台登入」。

---

## 三種方式總覽

| 優先級 | 機制 | 說明 | 適用 |
|---|---|---|---|
| 1 | **cookies.txt 匯入** | 於專案根目錄放置 `cookies.txt`（Netscape 格式），自動優先採用 | 所有平台，零依賴 |
| 2 | **CDP 登入狀態橋接**（建議） | 自動化 Chrome + DevTools Protocol，Chrome 自己吐解密後的 cookie | Windows Chrome 127+（App-Bound Encryption 時代標準解法） |
| 3 | **yt-dlp 直接提取** | 讀取本機瀏覽器 cookie DB | Firefox / 未啟用 ABE 的瀏覽器 |

> 為什麼不能直接 OAuth 綁定 IG/FB 帳號？Meta 已於 2024/12 廢止 Instagram Basic Display API，現行 API 需商業帳號 + App 審核且拿不到影片本體。Self-hosted 生態（yt-dlp、RSSHub）的通行做法就是「帶自己的 session」。

---

## 快速開始：在設定頁登入（建議）

1. 打開 OmniKeep，按右上角頭像選單 ›「設定」› 收錄管道，找到「社群平台登入」。
2. 這個區塊會顯示：
   - 目前用哪一種登入狀態（OmniKeep 自己的 Chrome，或匯入的 cookies.txt）與 cookie 筆數
   - 各平台是「已登入」還是「未登入」（Instagram、Facebook、YouTube／Google、X）
3. 按目標平台的「登入」，會開一個 OmniKeep 自己的 Chrome 視窗並前往該平台。這個視窗和你平常用的瀏覽器分開。
4. 在那個視窗完成登入，幾秒內該平台會變成「已登入」。沒有更新的話按「重新檢查」。
5. 完成。登入狀態保存在這台電腦的獨立 profile 裡，之後讀取時會自動帶上。要換帳號就按「重新登入」。

**首次使用**：已經有社群平台的收藏、但還沒登入任何平台時，OmniKeep 載入後會提示一次，可以直接從提示進到這個區塊。

---

## 底層細節

### CDP 自動化 Chrome

- **獨立 profile**：`%LOCALAPPDATA%\OmniKeep\chrome-cdp`，與日常瀏覽器完全隔離，互不干擾。
- 為何不用你原本的 Chrome？Chrome 136+ 基於安全**封鎖預設 profile 的遠端除錯埠**，且 127+ 的 App-Bound Encryption 讓外部程式無法解密 cookie DB（yt-dlp #7271、#10927）。獨立 profile + CDP 是唯一穩定解。
- 橋接只會 `connect_over_cdp` 讀取 cookie，斷開時**不會關閉**該 Chrome。
- 需要 Python 套件 `playwright`。Windows 執行 `pip install -r requirements.txt` 時會自動安裝；其他系統與 Docker 不會安裝，「社群平台登入」會顯示提示，請改用 cookies.txt（見 [選用功能](optional_features.md)）。

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

yt-dlp 對公開影片免登入。若要更穩定的 metadata / 字幕來源，可申請免費的 YouTube Data API v3 key，未來版本打算以 `YT_API_KEY` 整合進探索的排程（與 `GITHUB_TOKEN` 同模式）；探索是預設關閉的實驗功能，在 設定 › 實驗功能 開啟。

---

## 健康檢查與排除問題

```powershell
curl http://localhost:5000/health
# → session_bridge: { "mode": "cdp", "cdp_reachable": true, "connected_platforms": ["google"] }
```

| 症狀 | 處理 |
|---|---|
| mode 一直是 `none` | OmniKeep 自己的 Chrome 還沒啟動：在「社群平台登入」按任一平台的「登入」就會啟動；或確認 `BROWSER_CDP_PORT` 沒有被占用 |
| 登入後仍顯示「未登入」 | 按「重新檢查」；如果是在平常用的瀏覽器登入，而不是 OmniKeep 開的那個視窗，登入狀態不會被讀到 |
| 解析仍失敗 | 平台改版屬正常週期， OmniKeep 的無 cookie 降級路徑仍會嘗試公開內容 |

## 隱私

- Session cookie 只存在於**你自己的機器**（automation profile / cookies.txt）。
- 解析某個網址時，只取出**那個網站**的 cookie（例如 `fb.watch` 算 facebook.com），其他網站的登入狀態不會被帶上，也不會寫進任何檔案。
- yt-dlp 需要檔案時，cookie 寫進一個只有你（與系統管理員）能開的暫存資料夾，下載完就刪除；當機留下的會在下次啟動或下次匯出時清掉。你的 `cookies.txt` 不會直接交給 yt-dlp，所以不會被它改寫。
- 舊版曾把所有網站的 cookie 明文留在 `%TEMP%\omnikeep-cookies\session.cookies`，新版啟動時會自動刪除。
- OmniKeep 不含任何遙測；cookie 不會被傳送到 OmniKeep 以外的任何伺服器（解析目標網站本身除外）。
