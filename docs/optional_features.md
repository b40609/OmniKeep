# 選用功能與相依套件

`pip install -r requirements.txt` 會裝好所有基本功能。下面三項功能會用到較重或有平台限制的套件，因此另外處理：

| 功能 | 套件 | 怎麼安裝 | 沒裝的話 |
|---|---|---|---|
| 自動化 Chrome 登入、CDP cookie 橋接、網頁瀏覽器回退 | `playwright` | Windows：`requirements.txt` 會自動安裝。其他系統：不安裝 | 會話面板顯示「這台沒有安裝 playwright」，按「登入」會出現安裝說明；cookies.txt 匯入仍然可用 |
| 本機語音轉錄（YouTube、Reels、Bilibili、X、Threads） | `faster-whisper`、`ctranslate2`、`opencc` | `pip install -r requirements-stt.txt` | Reels 改用雲端轉錄（主要 LLM 端點的 `whisper-1`，其次是 Gemini）；沒有字幕的 YouTube 影片標成擷取失敗；沒有字幕的 Bilibili 影片不會有逐字稿 |
| 長影片的畫面文字（OCR） | `scenedetect`、`opencv-python-headless`、`imagehash`、`rapidocr`、`onnxruntime` | `pip install -r requirements-ocr.txt` | 跳過畫面層，log 記一行；逐字稿與分析照常 |

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

- **大小**：在 Windows、Python 3.12 上實測，安裝後多 213 MB。第一次轉錄時，還會從 Hugging Face 下載模型，存在 Hugging Face 快取目錄（見下一點）。之前用的 `tiny` 中文錯字太多。
- **用哪個模型**（`app/parsers/reel.py`）：
  | 機器 | 影片語言 | 模型 | 下載 | VRAM |
  |---|---|---|---|---|
  | 有 NVIDIA GPU | 中文，或影片沒標語言（Reels、X、Threads 多半沒標） | [Breeze-ASR-25](https://huggingface.co/MediaTek-Research/Breeze-ASR-25)（聯發科，台灣華語與中英夾雜微調） | 約 2.9 GB | 約 4.5 GB |
  | 有 NVIDIA GPU | 影片標明是其他語言（英文、日文……） | `large-v3-turbo` | 約 1.6 GB | 約 2 GB |
  | 只有 CPU | 任何語言 | `small`（int8） | 約 480 MB | — |

  2026-11-09 用 4 支台灣 YouTube 影片（共 40 分鐘，對上傳者的人工字幕）實測：Breeze 錯字率 7.7%、輸出繁體；`large-v3-turbo` 9.4%，而且 24% 是簡體。英文演講則是 turbo 較準（6.0% 對 7.0%）。turbo 和 small 的中文輸出會用 OpenCC（`s2twp`）轉成台灣繁體。
- **Breeze 從哪裡來**：faster-whisper 讀不了官方權重，所以用社群轉好的 CTranslate2 版本 [`shdennlin/breeze-asr-25-ct2`](https://huggingface.co/shdennlin/breeze-asr-25-ct2)（Apache-2.0，跟官方同授權）的 `float16` 資料夾，鎖定 revision `70660216b01a6f6b7b8c5690767a4763df61755f`（`reel.py` 的 `BREEZE_REVISION`）。CT2 的 `model.bin` 是純權重，不是 pickle，載入時不會執行程式碼。下載失敗（離線、Hugging Face 掛掉）時改用 `large-v3-turbo`，一小時後再試，轉錄不會因此失敗。
- **VRAM**：一次只放一個模型。需要另一個時先卸載現在的（顯示卡跟 Ollama 共用）；轉錄一次一支（`transcript.py` 的 `_stt_lock`）。
- **時間戳與章節**：逐字稿約每 30 秒標一次 `[MM:SS]`（一小時以上是 `[H:MM:SS]`），字幕用字幕的時間，本機轉錄用 faster-whisper 每段的起點；影片有章節時，每章加一個 `### [MM:SS] 章節名` 小標。
- **CPU 與 GPU**：預設用 CPU（int8）；偵測到 NVIDIA GPU 時改用 CUDA。GPU 需要 CUDA 12 的 cuBLAS 與 cuDNN 9（pip 套件 `nvidia-cublas-cu12`、`nvidia-cudnn-cu12==9.*`，合計約 1.3 GB），安裝方式見 [faster-whisper 的說明](https://github.com/SYSTRAN/faster-whisper#gpu)。在 Windows 上，程式會自動載入 pip 安裝在 `site-packages/nvidia/*/bin` 的 DLL（`app/parsers/reel.py` 的 `_preload_cuda_dlls`）。
- **為什麼不放進 `requirements.txt`**：它會一起安裝 onnxruntime 等需要編譯的套件。Python 3.14 在 2025-10-07 推出，但 onnxruntime 到 2026-02-05 才提供 3.14 的安裝包；如果放在基本需求，這段期間在 3.14 上連基本安裝都會失敗。分開之後，新版 Python 最多只是暫時無法使用本機轉錄。

## 長影片的畫面文字（OCR）

```bash
pip install -r requirements.txt -r requirements-ocr.txt
```

YouTube 長影片的逐字稿讀到之後，OmniKeep 會另外下載一份 720p、沒有聲音的影片（優先 H.264，解碼比 AV1 快好幾倍），把畫面上的字讀出來，只留下**旁白沒講到**的部分，加在逐字稿後面（`app/parsers/screen.py`）：

```
## 畫面重點（OCR，可能有錯字）
影片畫面上的字（投影片、圖表、截圖），只列旁白沒講到的部分。
- [04:39] Alignment Research / Constitutional AI: Harmlessness / from AI Feedback / ...
- [08:34] 亞馬遜再砸250億美元押Anthropic！綁十年 / 2026年4月21日—...先撥50億，其餘200億綁定「商業里程碑」...
```

- **怎麼做**：ffmpeg 把影片轉成每秒 2 格的 MJPEG 暫存檔 → PySceneDetect 的 AdaptiveDetector 找場景切換，取每個場景中間一格，再每 20 秒保底一格 → pHash 跟已保留的所有影格比對，重複的畫面只讀一次 → RapidOCR（PP-OCRv6，模型在套件裡，執行時不下載）→ 跟逐字稿比對：中文用雙字、英文和數字用整個詞，旁白說過或前面畫面出現過（台標、浮水印）的就不列。
- **耗時**（2026-11-09 實測，20 核桌機 CPU，10 分鐘新聞評論影片）：先前 720p AV1 原檔、單一 OCR 引擎要 223 秒（偵測 67.5 秒、OCR 155.5 秒）；現在 720p H.264、4 個 OCR 引擎各 5 執行緒，共 29.6 秒（轉檔 2.3 秒、偵測 7.3 秒、OCR 19.8 秒），列出 12 個畫面。480p 會把小字的數字讀錯（「53」讀成「63」），所以下載 720p。
- **上限**：短於 60 秒的影片不跑（Shorts、Reels 沿用現有的 12 格拼貼圖）；長於 2 小時的不下載；只讀前 60 分鐘；解碼、偵測與 OCR 合計 8 分鐘，時間到就保留已讀到的部分並註明；下載超過 600 MB 就放棄。一次只處理一支影片。
- **什麼時候跑**：只有逐字稿讀到（`ok`）時；逐字稿失敗的影片會整筆重抓，畫面層到時候再跑。分析 prompt 會把畫面文字跟逐字稿分開給，並說明那是畫面上的字、可能有 OCR 錯字；逐字稿那段仍是前 30000 字。
- **沒有裝的話**：log 記一行「not installed」，畫面層跳過，逐字稿與分析照常。
- **大小**：在 Windows、Python 3.14 上實測，安裝後約多 165 MB（`cv2` 113 MB、`rapidocr` 33 MB，其餘約 19 MB）；之前沒裝過 `scipy`（`imagehash` 要用）再多約 116 MB。`scenedetect` 要 `opencv-python`、`rapidocr` 要 `opencv-python-headless`，兩者裝的是同一個 `cv2`，版本要一致。Docker 映像目前不含這項。

## Docker

映像預設不含本機語音轉錄。要加入的話，在 `.env` 設定 `LOCAL_STT=true`，再重新建置：

```bash
docker compose up -d --build
```

模型快取放在 `/data/huggingface`（`omnikeep_data` volume），重建容器後不必重新下載。快取不會被納入備份。

Docker 映像沒有 playwright 和 Chrome，要使用平台登入狀態請改用 cookies.txt 匯入（見 [帳號會話](account_sessions.md)）。

## 防止漏列套件

`tests/test_optional_dependencies.py` 會用 [deptry](https://deptry.com/) 掃描 `app/` 與 `scripts/`。只要程式 import 了沒有寫進 `requirements.txt`、`requirements-stt.txt` 或 `requirements-ocr.txt` 的套件，測試就會失敗，CI 也會擋下來。
