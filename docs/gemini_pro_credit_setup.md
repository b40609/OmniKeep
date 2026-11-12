# 用 Google AI Pro 的每月 10 美元抵免額跑 OmniKeep（Vertex AI 教學）

適用：有 Google AI Pro（或 Ultra）訂閱的個人 Google 帳號。大約 15 分鐘，要準備一張信用卡（建付款帳戶用；照第 6 步設好上限，正常不會被扣款）。

2026-11-06 實際走過一次整理而成，下面每一步都是走得通的路；走不通的路列在最後的「踩過的坑」。Google 的畫面常改，名稱可能略有不同。

## 先看懂三件事

1. AI Pro 每月送 10 美元的 Google Cloud 抵免額（台灣帳戶顯示 NT$325），掛在你指定的**付款帳戶**上，有效一年。
2. 抵免額只能扣 **Vertex AI（畫面上叫 Agent Platform）** 的用量。AI Studio 的 Gemini API 在專案連結付款帳戶後會變成「預付制」，要另外儲值，抵免額付不了。所以 OmniKeep 要用「Google Vertex AI」卡片，不是「Google Gemini（AI Studio）」卡片。
3. 全部步驟都要用**同一個有 Pro 的 Google 帳號**做。專案、付款帳戶、金鑰只要有一個在別的帳號，就扣不到抵免額。

## 開始前

- **用一個只登入這個帳號的瀏覽器**（Chrome 新設定檔或訪客視窗）。同一個瀏覽器登入多個 Google 帳號時，網址會帶 `authuser=1`、`authuser=2`，一不小心就會在別的帳號上操作。
- 帳號以前用過 Google Cloud 的，先到 https://console.cloud.google.com/billing 看看：已經有「直接」類型、運作中的付款帳戶，就跳過第 1 步；福利頁的抵免額卡片已經選好付款帳戶並勾了「Always use」，就跳過第 2 步。

## 步驟

### 1. 建付款帳戶（要信用卡）

1. 打開 https://console.cloud.google.com/billing ，按「建立帳戶」。
2. 名稱隨意，國家選台灣，按「繼續」。
3. 在「設定您的帳單資料」頁往下捲，填信用卡，按「提交資訊並啟用計費功能」。
4. 回帳單首頁，確認新帳戶狀態是「運作中」、類型是「直接」（不能是「免費試用」）。

### 2. 領抵免額

1. 打開 https://developers.google.com/program/my-benefits 。
2. 找到「$10 monthly Gen AI & Cloud credits」卡片。如果顯示「No billing accounts available」，等幾分鐘再重新整理。
3. 下拉選單選第 1 步的付款帳戶，勾「Always use this billing account」，按「Apply」。按下去畫面可能沒反應，**不要一直按**。
4. 到 Cloud Console › 帳單 › 你的付款帳戶 › 「抵免額」頁，確認有一筆「Google Developer Program premium benefit - CREDIT_TYPE_MONTHLY」，狀態「可使用」。

### 3. 建專案（組織一定要選「無組織」）

1. 打開 https://console.cloud.google.com/projectcreate 。
2. 專案名稱例如 `omnikeep-vertex`。
3. 「帳單帳戶」選第 1 步的付款帳戶。
4. **「組織」選「無組織」**。選了你的組織的話，第 5 步的金鑰會被組織政策擋住（見最後的坑）。
5. 按「建立」。有些帳號的建立頁沒有「帳單帳戶」欄位：建好後到 https://console.cloud.google.com/billing/projects 確認專案的「帳單帳戶」欄有值；沒有的話在專案的「帳單」頁手動連結。
6. 建好後畫面可能跳回別的專案的首頁，不代表失敗。專案 ID 會自動加上數字（例如 `omnikeep-vertex-513910`），之後的網址要用這個 ID。

### 4. 啟用 Agent Platform API

1. 打開 https://console.cloud.google.com/apis/library/aiplatform.googleapis.com ，上方確認選的是第 3 步的專案。
2. 按「啟用」，等十幾秒。

### 5. 建 API 金鑰

1. 打開 https://console.cloud.google.com/agent-platform/api-keys ，上方確認是第 3 步的專案。
2. 按「Create API Key」。剛啟用 API 時按鈕可能是灰的，等十幾秒重新整理。
3. 跳出的視窗會顯示金鑰（`AQ.` 開頭），限制保持勾「Agent Platform API」。按複製鈕，存好。

### 6. 設強制支出上限（決定會不會扣卡）

1. 打開 https://console.cloud.google.com/billing ，選你的付款帳戶 › 左側「Budgets & caps」 › 「Create new」。
2. 「定義」選「**強制執行支出上限**」，名稱例如 `Vertex-cap`，按「下一步」。
3. 「範圍」：專案選第 3 步的專案，服務選「**Vertex AI** (aiplatform.googleapis.com)」。只能選單一專案、單一服務。
4. 「金額」：填**比每月抵免額低**的數字，例如抵免額 NT$325 就填 `250`。
5. 「動作」：保留 50%、80%、100% 的 email 通知，按「完成」。列表上「支出上限狀態」顯示「已設定」就好。

### 7. 填進 OmniKeep

1. OmniKeep 右上角頭像選單 ›「設定」› AI，在「AI 連線」按「新增連線」，選「Google Vertex AI（Agent Platform）」。
2. 貼上第 5 步的金鑰，模型用 `gemini-3.5-flash`（約 3 秒一次）或 `gemini-3.5-flash-lite`（約 1 秒一次）。
3. 按「測試」，看到「連線成功（Vertex AI）」再按「儲存」。
4. 在下面的「用途與備援順序」把它加到「分析」（或「提問」、「探索」）的順序裡。
5. YouTube 影片解析不能用這條連線（見下面的坑），影片用途請另外接 AI Studio 的 Gemini 免費金鑰。

## 踩過的坑

| 現象 | 原因 | 解法 |
|---|---|---|
| 福利卡片「No billing accounts available」，連結指向 Free Trial 註冊頁 | 還沒有一般付款帳戶，或剛建好還沒同步 | 照第 1 步建一般付款帳戶，等幾分鐘重新整理 |
| AI Studio 設付款時「This Free Trial billing account can't be used for billing setup」 | 免費試用的付款帳戶不能用 | 第 1 步建一般付款帳戶 |
| 按「Apply」畫面沒反應 | 頁面沒有成功提示 | 到付款帳戶的抵免額頁確認（第 2 步第 4 點），不要重複按 |
| AI Studio 金鑰呼叫回 402「Your prepayment credits are depleted」 | 專案連結付款帳戶後，AI Studio 改成預付制，要另外儲值；抵免額不能付 | 改走 Vertex（本教學的路線） |
| Agent Platform 的 API 選項是灰的，提示「組織政策 constraints/iam.managed.disableServiceAccountApiKeyCreation 禁止…」 | 專案在你的組織底下，組織預設只允許金鑰用 Gemini API | 專案改建在「無組織」（第 3 步）。改組織政策要另外加「組織政策管理員」角色，比較麻煩 |
| 改組織政策時「您的權限不足」 | 組織管理員預設沒有「組織政策管理員」角色 | 不用改政策，照第 3 步用「無組織」專案 |
| 建金鑰時「Gemini API can't be added to this key in a project without an organization」 | 無組織專案的金鑰不能開 Gemini API | 不影響：OmniKeep 的 Vertex 卡片只需要 Agent Platform API |
| 「API 和服務 › 憑證」建一般 API 金鑰，選不到 Agent Platform API | Agent Platform 規定金鑰要綁服務帳戶 | 改在 Agent Platform 的金鑰頁建（第 5 步），它會自動綁好 |
| 打開 Vertex express mode 被導到免費試用的付款帳戶 | express mode 走試用帳戶 | 不用 express mode，照本教學 |
| 抵免額沒在扣 | 金鑰的專案是別的 Google 帳號建的，或專案沒連結有抵免額的付款帳戶 | 全部用同一個 Pro 帳號；確認第 3 步選了付款帳戶 |
| Vertex 解析 YouTube 回 401「Expected OAuth 2 access token」 | Vertex 用 API 金鑰不能讀 YouTube 網址 | 影片用途接 AI Studio 的 Gemini 免費金鑰 |
| 同一個瀏覽器登入多個帳號，操作跑到別的帳號 | 網址的 `authuser` 參數決定用哪個帳號 | 用只登入這個帳號的瀏覽器設定檔（見「開始前」） |
| 建專案頁沒有「帳單帳戶」欄位，建好後跳到別的專案首頁 | 介面依帳號狀態不同 | 專案其實建好了；到帳單的「您的專案」確認有連結付款帳戶 |
| 帳單頁同時有好幾筆抵免額（Pro 每月一筆、GCP 新用戶免費抵免額） | 抵免額會累積，新用戶另有 90 天的免費抵免額 | 免費抵免額可以付 Vertex 上 Google 自家模型，不能付 AI Studio 的 Gemini API；注意它的到期日 |
| `gemini-2.5-flash` 回 404「no longer available to new users」 | 舊模型對新用戶停用，2026-12-01 起全面導向新模型 | 改用 `gemini-3.5-flash` 或 `gemini-3.5-flash-lite` |

## 關於「保證不扣卡」

- 支出上限算的是**扣抵免額之前**的總費用，所以上限設得比抵免額低，用量就不會超過抵免額。
- Google 寫明上限**不是即時**生效，到上限後服務才會暫停，延遲期間的超額用量仍要付費。所以要留緩衝（NT$325 的抵免額設 NT$250）。
- 上限每月月初自動解除、恢復服務，和抵免額每月發放對齊。
- 上限只管你選的那個專案的 Vertex AI。同一個付款帳戶下的其他專案或服務不受管。
- 第一週到付款帳戶的抵免額頁看「剩餘的抵免額」有沒有在減少，確認是扣抵免額。
- 上限會一直沿用。某個月為了用掉累積的抵免額把上限調高，下個月開始前要調回比每月抵免額低的數字。

## 參考

- Google Developer Program 福利常見問題：https://developers.google.com/profile/help/benefits
- 方案與價格：https://developers.google.com/program/plans-and-pricing
- Gemini 模型停用時程：https://aistudio.google.com/docs/deprecations
