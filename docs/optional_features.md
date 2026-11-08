# 選用功能與相依套件

`pip install -r requirements.txt` 會裝好所有基本功能。下面兩項功能會用到較重或有平台限制的套件，因此另外處理：

| 功能 | 套件 | 怎麼安裝 | 沒裝的話 |
|---|---|---|---|
| 自動化 Chrome 登入、CDP cookie 橋接、網頁瀏覽器回退 | `playwright` | Windows：`requirements.txt` 會自動安裝。其他系統：不安裝 | 會話面板顯示「這台沒有安裝 playwright」，按「登入」會出現安裝說明；cookies.txt 匯入仍然可用 |
| 本機語音轉錄（Reels、Bilibili） | `faster-whisper`、`ctranslate2` | `pip install -r requirements-stt.txt` | Reels 改用雲端轉錄（主要 LLM 端點的 `whisper-1`，其次是 Gemini）；沒有字幕的 Bilibili 影片不會有逐字稿 |

## playwright：只在 Windows 安裝

- 用途：連到 OmniKeep 專用的 Chrome 取得 cookie（`app/parsers/cookie_manager.py`）、開啟平台登入頁（`app/routers/session.py`），以及 `ENABLE_BROWSER_FALLBACK=true` 時以 Chrome 開啟網頁（`app/parsers/web.py`）。
- 它只控制電腦上已安裝的 Google Chrome，**不需要**另外執行 `playwright install` 下載瀏覽器。Windows 上裝好後約占 110 MB（Python 3.12 實測）。
- 只在 Windows 安裝的原因：自動啟動 Chrome 時只會找 Windows 的安裝路徑（`cookie_manager.py` 的 `_CDP_LAUNCH_PATHS`），Docker 映像裡也沒有 Chrome，其他系統裝了也用不到。Linux 或 macOS 如果要自己用除錯埠啟動 Chrome 來搭配，可以手動執行 `pip install playwright`。
- 最低版本 1.48：`web.py` 用到的 `route_web_socket` 是 [1.48 新增的](https://github.com/microsoft/playwright-python/releases/tag/v1.48.0)。

## 本機語音轉錄

```bash
pip install -r requirements.txt -r requirements-stt.txt
```

影片沒有字幕時（YouTube、Reels、Bilibili、X 與 Threads 附帶的影片），OmniKeep 會下載音訊用它轉成逐字稿再分析（`app/parsers/transcript.py`）。沒有裝的話，沒有字幕的影片會標成「擷取失敗」，不會只憑標題和說明欄分析。

裝好後要**重新啟動 OmniKeep**；程式在第一次轉錄時發現套件不存在，就會在這次執行期間停用本機轉錄。

- **大小**：在 Windows、Python 3.12 上實測，安裝後多 213 MB。第一次轉錄時，還會從 Hugging Face 下載模型，存在 Hugging Face 快取目錄：有 NVIDIA GPU 時是 `large-v3-turbo`（約 1.6 GB，佔約 2 GB VRAM），只有 CPU 時是 `small`（約 480 MB）。之前用的 `tiny` 中文錯字太多。
- **CPU 與 GPU**：預設用 CPU（int8）；偵測到 NVIDIA GPU 時改用 CUDA。GPU 需要 CUDA 12 的 cuBLAS 與 cuDNN 9（pip 套件 `nvidia-cublas-cu12`、`nvidia-cudnn-cu12==9.*`，合計約 1.3 GB），安裝方式見 [faster-whisper 的說明](https://github.com/SYSTRAN/faster-whisper#gpu)。在 Windows 上，程式會自動載入 pip 安裝在 `site-packages/nvidia/*/bin` 的 DLL（`app/parsers/reel.py` 的 `_preload_cuda_dlls`）。
- **為什麼不放進 `requirements.txt`**：它會一起安裝 onnxruntime 等需要編譯的套件。Python 3.14 在 2025-10-07 推出，但 onnxruntime 到 2026-02-05 才提供 3.14 的安裝包；如果放在基本需求，這段期間在 3.14 上連基本安裝都會失敗。分開之後，新版 Python 最多只是暫時無法使用本機轉錄。

## Docker

映像預設不含本機語音轉錄。要加入的話，在 `.env` 設定 `LOCAL_STT=true`，再重新建置：

```bash
docker compose up -d --build
```

模型快取放在 `/data/huggingface`（`omnikeep_data` volume），重建容器後不必重新下載。快取不會被納入備份。

Docker 映像沒有 playwright 和 Chrome，要使用平台登入狀態請改用 cookies.txt 匯入（見 [帳號會話](account_sessions.md)）。

## 防止漏列套件

`tests/test_optional_dependencies.py` 會用 [deptry](https://deptry.com/) 掃描 `app/` 與 `scripts/`。只要程式 import 了沒有寫進 `requirements.txt` 或 `requirements-stt.txt` 的套件，測試就會失敗，CI 也會擋下來。
