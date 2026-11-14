# 本機模型執行方式調研（2026-11-14）

目標：安裝 OmniKeep 時，依使用者的電腦自動挑合適的本機模型並裝好，使用者不必自己裝 Ollama、排錯。

## 一、OmniKeep 現在用本機模型做什麼

| 用途 | 現況 | 重要性 |
| --- | --- | --- |
| 語意搜尋的向量 | Ollama 的 embeddinggemma-2，`app/vector.py` 呼叫 `/api/embed` | 必要：每篇收藏都要算，本機掛了搜尋就退化 |
| 提問（Ask Brain）的回答 | Ollama 的 qwen3:8b，`app/brain.py` 呼叫 `/api/chat`，失敗時改走雲端 | 可選：有雲端可以接手 |
| 文章分析 | 雲端（Vertex Gemini 等） | 不用本機 |

真正非本機不可的只有向量。2026-11-13 到 14 的停擺，就是 Ollama 這個獨立程序停掉、沒人重啟，見 `scripts/watchdog.ps1` 的修正。

## 二、候選方案

| 方案 | 怎麼跑 | 依硬體自動選加速 | 向量 | 對話 | 授權 | 主要限制 |
| --- | --- | --- | --- | --- | --- | --- |
| Foundry Local（Microsoft） | Python SDK 在 OmniKeep 程序內執行，不必另裝服務；也有選用的本機伺服器 | 有，官方：偵測裝置、選最佳執行方式，GPU、NPU 優先，沒有就退回 CPU；執行元件與驅動自動更新 | 有，SDK 內建，範例模型 qwen3-embedding-0.6b | 有，目錄含 Qwen、Phi、Mistral、DeepSeek、GPT OSS | SDK 為 MIT；模型依各自授權 | 只能用官方目錄的模型；第一次使用要下載模型與執行元件；條款可能包含診斷資料 |
| llama.cpp `llama-server` | 獨立程序，OmniKeep 要自己下載對應的版本並看顧它 | 上游沒有；Windows 版分 CPU、CUDA 12/13、Vulkan、HIP、SYCL，要安裝程式自己判斷 | 有，`--embedding`、`/v1/embeddings` | 有，任何 GGUF；新版有 router 模式可多模型 | MIT | 選版本、看顧程序都要自己做，等於重寫一個 Ollama |
| Ollama（現況） | 獨立程序，托盤程式只在登入時啟動 | 有 | 有 | 有 | MIT | 要使用者另外安裝；這台在 11 月停過兩次、沒有當機紀錄；托盤程式 11/04 有記憶體洩漏報告 |
| LM Studio（llmster 無介面版） | 獨立常駐程序，`lms daemon up` | 有，內建 llama.cpp 與 MLX | 有 | 有 | 主程式為閉源，CLI 為 MIT | 官方沒有 Windows 服務的做法；閉源不適合包進開源專案 |
| Lemonade（AMD） | 獨立伺服器 | 會依電腦設定推論引擎；官方 FAQ 說 NVIDIA 走 Vulkan，但有 release note 寫已加入 CUDA，兩者矛盾，待驗證 | FAQ 沒提，待驗證 | 有 | Apache 2.0 | 以 AMD Ryzen AI 為主 |
| onnxruntime／fastembed 直接算向量 | OmniKeep 程序內 | 預設 CPU | 有 | 沒有 | MIT／Apache 2.0 | 只解決向量；EmbeddingGemma 不在 fastembed Python 版的模型清單，要自己接 ONNX |

## 三、建議

**向量：改用 Foundry Local SDK，在 OmniKeep 程序內直接算。**
- 不再有獨立的模型服務，「模型服務停掉沒人重啟」這類問題整個消失；OmniKeep 自己有 watchdog。
- 硬體由 SDK 自動挑：有 GPU 用 GPU，沒有就用 CPU。安裝時只需 `pip install foundry-local-sdk`，第一次使用自動下載模型。
- `foundry-local-sdk` 2.4.1（2026-11-11）是 abi3 wheel，支援 Python 3.11 到 3.14，有 Windows、Linux、macOS 版本，這台的 Python 3.14 可以裝。
- 代價：換成 qwen3-embedding-0.6b 要全部重算向量，這台 941 筆，本機算幾分鐘。

**提問：也走 Foundry Local 目錄裡的 Qwen，維持雲端接手。** 依硬體自動挑版本，不必使用者選量化格式。

**Ollama、llama.cpp、LM Studio 留在 AI 連線選單裡**，給想自己接的人選，但不再是安裝必要條件。

## 四、還沒驗證、要先實測的

1. 在 OmniKeep 這種長時間執行的伺服器程序裡載入 SDK，記憶體與穩定度如何。官方定位是「單一使用者的用戶端應用程式」，OmniKeep 正是單人使用，但要實測。
2. 桌機等級的 NVIDIA 顯示卡在 Windows 上是否真的走 GPU；向量模型小，用 CPU 可能也夠快。
3. qwen3-embedding-0.6b 和 embeddinggemma 在中文收藏上的搜尋品質：用現有收藏做小型檢索測試，例如拿標題搜摘要，比較前 5 名命中率。
4. 目錄裡實際有哪些 Qwen 對話模型、各自大小。
5. 條款裡的診斷資料規定。

## 出處

- Foundry Local 官方介紹（2026-10-22 更新）：https://learn.microsoft.com/en-us/azure/foundry-local/what-is-foundry-local
- Foundry Local 產生向量（2026-10-22 更新）：https://learn.microsoft.com/en-us/azure/foundry-local/how-to/how-to-generate-embeddings
- foundry-local-sdk on PyPI：https://pypi.org/project/foundry-local-sdk/
- Foundry Local GA 報導（2026-04-13）：https://lilting.ch/en/articles/microsoft-foundry-local-bundled-ai-runtime
- llama.cpp server README：https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md
- llama.cpp Windows 預編譯版說明（第三方）：https://knightli.com/zh-tw/2026/05/18/llama-cpp-windows-cuda-vulkan-gguf/
- LM Studio 無介面版：https://lmstudio.ai/docs/developer/core/headless_llmster
- Lemonade FAQ：https://lemonade-server.ai/docs/guide/faq/
- onnxruntime on PyPI：https://pypi.org/project/onnxruntime/
- fastembed：https://github.com/qdrant/fastembed
- 綜合比較（第三方）：https://infrabase.ai/alternatives/ollama 、https://www.storagereview.com/best/local-llm-tools
