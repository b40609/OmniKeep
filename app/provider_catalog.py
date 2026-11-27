"""AI provider cards shown in the settings page and the first-run wizard.

Grown out of frontend/src/lib/setup.ts SETUP_PRESETS and the option list in
docs/ai_provider_options_2026-11.md section 1. The list states options only:
nothing is preselected, and nothing here spends a subscription's quota
(Claude, Antigravity or ChatGPT plans are deliberately absent).

kind is the wire protocol a connection made from the card speaks:
  openai  OpenAI-compatible /v1 (chat/completions, models, embeddings)
  gemini  Google AI Studio (google-genai SDK; also native YouTube analysis)
  ollama  a local Ollama runner (native /api/embed for vectors, /v1 for chat)

Limits change often; `verified` is the date they were last checked.
`quota` is the free allowance the settings page measures OmniKeep's own usage against
({"tokens"|"requests": n, "period": "day"|"month"|"once"}; OpenRouter's 50 a day rises to
1,000 after a 10 USD top-up). `no_signup` marks a public service usable with no account at all (Kilo, OVHcloud): the
wizard lists those first and the setup Skill offers them to someone with no keys yet.
`ends` is the last day of a limited-time free offer (Itera); catalog() adds `ended` once it
has passed, so the settings page and the setup Skill say so instead of listing it as free.
`model_extra_body` holds extra request fields a particular model needs (NVIDIA's DeepSeek V4.1
Flash only answers with its reasoning switched off); a connection switched to that model, or a
task slot naming it, gets them (app/ai_connections.py extra_body_for).
"""
from datetime import datetime
from typing import Any, Dict, List, Optional

VERIFIED = "2026-11-05"

CARDS: List[Dict[str, Any]] = [
    {
        "id": "agnes", "label": "Agnes", "kind": "openai",
        "base_url": "https://apihub.agnes-ai.com/v1", "model": "agnes-3.0-flash",
        "models": ["agnes-3.0-flash", "agnes-2.5-flash"],
        "key_mode": "required", "key_url": "https://platform.agnes-ai.com/settings/apiKeys",
        "cost": "免費（體驗價 0 美元，截止日看官方公告）",
        "limits": "免費帳號是動態的每分鐘上限（2026-11-05 實測約 10 次），登入 API Console 可看；同類型的多把金鑰共用額度，不會疊加。沒有向量。建議間隔 7 秒。",
        "notes": "很適合當保底；context 512K。",
        "min_interval": 7.0, "max_concurrency": 1,
        "caps": {"json_mode": True, "embeddings": False, "context": 512000},
        "verified": "2026-11-22",
    },
    {
        "id": "gemini", "label": "Google Gemini（AI Studio）", "kind": "gemini",
        "base_url": "", "model": "gemini-3.5-flash",
        "models": ["gemini-3.5-flash", "gemini-3.6-flash", "gemini-3.8-flash", "gemini-3.5-flash-lite", "gemini-3.1-flash-lite"],
        "key_mode": "required", "key_url": "https://aistudio.google.com/apikey",
        "cost": "免費層",
        "limits": "免費層的每分鐘與每日次數依模型不同，以 AI Studio 的 Rate Limit 頁為準，每天太平洋時間午夜重置。gemini-3.5-flash 已自動轉到 gemini-3.6-flash。可以填多把金鑰，用逗號分隔，輪流使用。",
        "notes": "YouTube 影片解析只有 Gemini 能做。gemini-2.5-flash 對新用戶已停用（2026-12-01 起全面導向新模型）。專案連結付款帳戶後，AI Studio 會改成預付制，要另外儲值，Google AI Pro 的抵免額不能用；要用抵免額請改用 Vertex 卡片。",
        "min_interval": 12.0, "max_concurrency": 1,
        "caps": {"json_mode": True, "embeddings": False, "video": True, "context": 1000000},
        "verified": "2026-11-22",
    },
    {
        "id": "vertex", "label": "Google Vertex AI（Agent Platform）", "kind": "gemini",
        "base_url": "", "model": "gemini-4-hydrogen",
        "models": ["gemini-4-hydrogen", "gemini-4-carbon", "gemini-3.5-flash", "gemini-3.5-flash-lite",
                   "gemini-3.1-flash-lite"],
        "key_mode": "required", "key_url": "https://console.cloud.google.com/apis/credentials",
        "cost": "Google Cloud 計費（Google AI Pro 每月 10 美元抵免額可以用）",
        "limits": "用量先扣付款帳戶上的抵免額，用完才扣卡。到帳單的 Budgets & caps 為 Vertex AI 設「強制執行支出上限」，金額設得比每月抵免額低。",
        "notes": "用 Agent Platform 的 API 金鑰（express mode），不必填專案 ID。金鑰的 API 限制要允許 Agent Platform API；機構政策預設只允許 Gemini API，要先放行。不能解析 YouTube 影片（API 金鑰呼叫會回 401，要 OAuth），影片用途請用 AI Studio 的 Gemini 卡片。步驟見 docs/gemini_pro_credit_setup.md。",
        "min_interval": 1.0, "max_concurrency": 2,
        "caps": {"json_mode": True, "embeddings": False, "video": False, "context": 1000000, "vertex": True},
        "verified": "2026-11-22",
    },
    {
        "id": "groq", "label": "Groq", "kind": "openai",
        "base_url": "https://api.groq.com/openai/v1", "model": "openai/gpt-oss-120b",
        "models": ["openai/gpt-oss-120b", "qwen/qwen3.8-27b", "openai/gpt-oss-20b"],
        "key_mode": "required", "key_url": "https://console.groq.com/keys",
        "cost": "免費層",
        "limits": "每個模型分開算：每分鐘 30 次與 8,000 token（長文容易撞到），每日 1,000 次與 20 萬 token；沒有向量。Llama 模型 2026-11 已移出免費方案。",
        "notes": "速度快，支援嚴格 JSON schema；qwen/qwen3.8-27b 目前為 Preview 模型，可能提前下架。",
        "quota": {"requests": 1000, "period": "day"},
        "min_interval": 2.5, "max_concurrency": 2,
        "caps": {"json_mode": True, "embeddings": False, "context": 131072},
        "verified": "2026-11-23",
    },
    {
        "id": "cloudflare", "label": "Cloudflare Workers AI", "kind": "openai",
        "base_url": "https://api.cloudflare.com/client/v4/accounts/<帳號 ID>/ai/v1",
        "model": "@cf/openai/gpt-oss-120b",
        "models": ["@cf/openai/gpt-oss-120b", "@cf/meta/llama-3.1-8b-instruct"],
        "embedding_model": "@cf/baai/bge-m3",
        "key_mode": "required", "key_url": "https://dash.cloudflare.com/profile/api-tokens",
        "editable_url": True,
        "cost": "免費層",
        "limits": "每日 10,000 Neurons（推估約 400 則分析）；有 bge-m3 向量。部分模型才支援 JSON 格式。",
        "notes": "位址裡的 <帳號 ID> 要換成你的 Cloudflare 帳號 ID；API token 要有 Workers AI 權限。",
        "min_interval": 2.0, "max_concurrency": 2,
        "caps": {"json_mode": False, "embeddings": True, "context": 128000},
        "verified": "2026-11-22",
    },
    {
        "id": "openrouter", "label": "OpenRouter（:free 模型）", "kind": "openai",
        "base_url": "https://openrouter.ai/api/v1", "model": "google/gemma-4-31b-it:free",
        "models": ["google/gemma-4-31b-it:free", "google/gemma-4-26b-a4b-it:free", "inclusionai/ling-3.2-flash:free",
                   "nvidia/nemotron-3.5-lightning:free"],
        "key_mode": "required", "key_url": "https://openrouter.ai/keys",
        "oauth": "openrouter",
        "cost": "免費（:free 模型）",
        "limits": "每分鐘 20 次；每日 50 次，累計儲值滿 10 美元後變每日 1,000 次。",
        "notes": "免費模型常替換：按「測試」會列出目前可用的模型。",
        "quota": {"requests": 50, "period": "day"},
        "min_interval": 3.0, "max_concurrency": 1,
        "caps": {"json_mode": True, "embeddings": False, "context": 131072},
        "verified": "2026-11-22",
    },
    {
        "id": "zai", "label": "Z.AI（GLM Flash）", "kind": "openai",
        "base_url": "https://api.z.ai/api/paas/v4", "model": "glm-4.7-flash",
        "models": ["glm-4.7-flash", "glm-4.5-flash"],
        "key_mode": "required", "key_url": "https://z.ai/manage-apikey/apikey-list",
        "cost": "免費（Flash 模型）",
        "limits": "官方並發與每分鐘上限須登入控制台查詢（未公開，第三方說法為 1 個並發）。2026-11-06 實測（關閉推理）：glm-4.7-flash 一篇約 28 秒；不關閉時超過 300 秒逾時。",
        "notes": "適合單線程的背景工作。用 email 註冊即可，建金鑰時請選 Standard API Key。預設關閉推理（thinking disabled）。免費視覺模型另有 glm-4.6v-flash（還沒實測）。",
        "min_interval": 2.0, "max_concurrency": 1,
        "caps": {"json_mode": True, "embeddings": False, "context": 128000,
                 "extra_body": {"thinking": {"type": "disabled"}}},
        "verified": "2026-11-23",
    },
    # Added 2026-11-06 from docs/free_llm_channels_2026-11.md: each passed the full analysis
    # prompt in a live test (section 2 there). Times are one sample, not a guarantee.
    {
        "id": "inception", "label": "Inception（Mercury 3）", "kind": "openai",
        "base_url": "https://api.inceptionlabs.ai/v1", "model": "mercury-3",
        "models": ["mercury-3", "mercury-2.5"],
        "key_mode": "required", "key_url": "https://platform.inceptionlabs.ai/",
        "cost": "免費額度（新帳號一次送 100M token，服務 2026-12-28 結束）",
        "limits": "一次性額度，用完要綁卡；沒有向量。2026-11-06 實測一篇分析約 5 秒、每秒約 430 token。",
        "notes": "目前實測最快；context 1M。標題偶爾夾簡體。Mercury API 2026-12-28 停止服務，之後要從用途裡拿掉。",
        "ends": "2026-12-28",
        "quota": {"tokens": 100_000_000, "period": "once"},
        "min_interval": 1.0, "max_concurrency": 2,
        "caps": {"json_mode": True, "embeddings": False, "context": 1000000},
        "verified": "2026-11-22",
    },
    {
        "id": "tokenharbor", "label": "Token Harbor（:free 模型）", "kind": "openai",
        "base_url": "https://tokenharbor.ai/v1", "model": "deepseek-v4.1-flash:free",
        "models": ["deepseek-v4.1-flash:free", "mimo-v2.6-flash:free"],
        "key_mode": "required", "key_url": "https://tokenharbor.ai/dashboard/api-keys",
        "cost": "免費（:free 模型）",
        "limits": "每 7 天滾動的免費額度，從第一次免費請求起算、按金額計（金額沒公開）；每個帳號每分鐘 60 次、每小時 1,800 次。免費模型要先在 dashboard 手動開啟。2026-11-06 實測一篇約 19 秒。",
        "notes": "新加坡公司 TH TECHNOLOGY PTE. LTD.；位址沒有 api. 子網域。",
        "min_interval": 1.0, "max_concurrency": 1,
        "caps": {"json_mode": True, "embeddings": False},
        "verified": "2026-11-22",
    },
    {
        "id": "requesty", "label": "Requesty（免費模型）", "kind": "openai",
        "base_url": "https://router.requesty.ai/v1", "model": "google/gemma-4-31b-it",
        "models": ["google/gemma-4-31b-it", "novita/ling-3.1-flash"],
        "key_mode": "required", "key_url": "https://www.requesty.ai/free-models",
        "cost": "免費（免費模型）",
        "limits": "新組織每天 200 次、每分鐘 20 次（付費組織每天 1,000 次、每分鐘 60 次），所有免費模型共用；另有依餘額計算的同時請求數上限。2026-11-06 實測一篇約 57 秒。",
        "notes": "有公司實體與 DPA；/v1/models 目前有 8 個免費模型（只實測過這 2 個，其餘還沒實測）。ling-3.1-flash 不支援 JSON 格式參數，會改用一般請求再解析。",
        "quota": {"requests": 200, "period": "day"},
        "min_interval": 3.0, "max_concurrency": 1,
        "caps": {"json_mode": True, "embeddings": False},
        "verified": "2026-11-23",
    },
    {
        "id": "bazaarlink", "label": "BazaarLink（免費模型）", "kind": "openai",
        "base_url": "https://api.bazaarlink.ai/v1", "model": "auto:free",
        "models": ["auto:free", "qwen/qwen3.7-flash:free", "deepseek/deepseek-v4-flash-0731free:free",
                   "nvidia/nemotron-3.5-lightning-free:free", "stealth/glyph-cluster:free"],
        "key_mode": "required", "key_url": "https://bazaarlink.ai/free",
        "cost": "免費（:free 模型）",
        "limits": "沒儲值：每分鐘 10 次、每天 60 單位；儲值過：每分鐘 20 次、每天 120 單位（全站免費總上限每分鐘 20 次）。所有免費模型共用，"
                  "長輸入扣比較多單位，每天 UTC 00:00（台灣早上 8 點）重置；同時最多 2 個請求。",
        "notes": "台灣集聯科技營運。不帶 :free 後綴的直接模型 ID 多為付費，請用列出的 :free 路由或 auto:free。還沒實測。",
        "min_interval": 6.0, "max_concurrency": 1,
        "caps": {"json_mode": True, "embeddings": False},
        "verified": "2026-11-23",
    },
    {
        "id": "cheapllm", "label": "cheapllm.shop", "kind": "openai",
        "base_url": "https://cheapllm.shop/v1", "model": "deepseek-v4.1-flash-1017",
        "models": ["deepseek-v4.1-flash-1017"],
        "key_mode": "required", "key_url": "https://cheapllm.shop/docs",
        "cost": "免費（公測中不限量）",
        "limits": "公測期間每個帳號免費、不限次數。公測結束後保留永久免費層、不用綁卡：每個帳號每滾動一小時至少 5,000 輸入、"
                  "1,000 輸出 token（所有金鑰合計）。同時只能 1 個請求。",
        "notes": "公測結束後的額度只夠少量分析，適合當備援。還沒用金鑰實測過分析。",
        "min_interval": 2.0, "max_concurrency": 1,
        "caps": {"json_mode": True, "embeddings": False},
        "verified": "2026-11-23",
    },
    {
        "id": "nvidia", "label": "NVIDIA NIM（Free Endpoint）", "kind": "openai",
        "base_url": "https://integrate.api.nvidia.com/v1", "model": "minimaxai/minimax-m3.1-flash",
        "models": ["minimaxai/minimax-m3.1-flash", "mistralai/mistral-large-4-1t-a52b"],
        "key_mode": "required", "key_url": "https://build.nvidia.com/settings/api-keys",
        "cost": "免費（Free Endpoint 模型）",
        "limits": "約每分鐘 40 次，整個帳號共用（社群數據）。免費端點很擠：2026-11-06 實測一篇 80 到 190 秒。",
        "notes": "條款寫明不能用在 production。免費端點很擠，時間波動大；官方模型頁已將 deepseek-ai/deepseek-v4.1-flash 標示為 Deprecated 並移出 /v1/models。",
        "min_interval": 2.0, "max_concurrency": 1,
        "caps": {"json_mode": True, "embeddings": False},
        "verified": "2026-11-23",
    },
    {
        "id": "aihubmix", "label": "AIHubMix（-free 模型）", "kind": "openai",
        "base_url": "https://aihubmix.com/v1", "model": "glm-4.7-flash-free",
        "models": ["glm-4.7-flash-free"],
        "key_mode": "required", "key_url": "https://console.aihubmix.com/token",
        "cost": "免費（-free 模型）",
        "limits": "官方沒有集中的限額表。第三方整理：多數免費模型每分鐘 5 次、每天 100 次，glm-4.7-flash-free 每天 500 次與 100 萬 token。2026-11-06 實測（關閉推理）一篇約 43 秒。",
        "notes": "免費模型會輪替：按「測試」會列出目前的模型。預設關閉推理（thinking disabled）。",
        "quota": {"requests": 500, "period": "day"},
        "min_interval": 12.0, "max_concurrency": 1,
        "caps": {"json_mode": True, "embeddings": False, "extra_body": {"thinking": {"type": "disabled"}}},
        "verified": "2026-11-22",
    },
    {
        "id": "sealion", "label": "SEA-LION（AI Singapore）", "kind": "openai",
        "base_url": "https://api.sea-lion.ai/v1", "model": "aisingapore/Qwen-SEA-LION-v4.5-27B-IT",
        "models": ["aisingapore/Qwen-SEA-LION-v4.5-27B-IT"],
        "key_mode": "required", "key_url": "https://playground.sea-lion.ai/",
        "cost": "免費（Trial key）",
        "limits": "每分鐘 10 次（回應標頭證實），每人一把金鑰。2026-11-06 實測（關閉推理）一篇約 76 秒。",
        "notes": "用 Google 登入就能申請；強項是東南亞語言。預設關閉推理（enable_thinking false）。",
        "min_interval": 6.0, "max_concurrency": 1,
        "caps": {"json_mode": True, "embeddings": False,
                 "extra_body": {"chat_template_kwargs": {"enable_thinking": False}}},
        "verified": "2026-11-22",
    },
    {
        "id": "itera", "label": "Itera Compute（Qwen3.8 27B）", "kind": "openai",
        "base_url": "https://api.iteracompute.com/v1", "model": "qwen/qwen3.8-27b",
        "models": ["qwen/qwen3.8-27b", "Auto"],
        "key_mode": "required", "key_url": "https://platform.iteracompute.com/api-keys",
        "cost": "免費（限時活動，到 2026-11-24）",
        "limits": "每月 30M token（每月 1 日 UTC 00:00／台灣早上 8 點重置），單次 context 128K、輸出上限 8,192 token，同時限 1 個請求，超額回 429，不會自動扣款。推理型，一篇約 9,000 token（每月約 3,300 篇）；2026-11-06 實測一篇約 165 秒。",
        "notes": "2026-11-24 00:00 太平洋時間（台灣時間 16:00）起，未曾儲值的帳號停止免費額度；此前有淨儲值的帳號保留共享免費 Auto。試過用 enable_thinking false 關閉推理，反而逾時，所以不帶。",
        "ends": "2026-11-24",
        "quota": {"tokens": 30_000_000, "period": "month"},
        "min_interval": 2.0, "max_concurrency": 1,
        "caps": {"json_mode": True, "embeddings": False},
        "verified": "2026-11-23",
    },
    {
        "id": "flm", "label": "flm（不用金鑰）", "kind": "openai",
        "base_url": "https://flm.stonech.at/v1", "model": "auto",
        "models": ["auto"],
        "key_mode": "none", "key_url": "", "no_signup": True,
        "cost": "免費（不用金鑰）",
        "limits": "每個 IP 每分鐘 60 次、每天 20,000 次、1,000 萬 token（回應標頭證實）。2026-11-17 實測一篇約 5 秒。",
        "notes": "auto 由服務自己挑模型。不收圖片（2026-11-17 實測回 400），短影音畫面交給其他連線。",
        "min_interval": 1.0, "max_concurrency": 2,
        "caps": {"json_mode": True, "embeddings": False, "vision": False},
        "verified": "2026-11-22",
    },
    {
        "id": "jarvisclaw", "label": "JarvisClaw（不用金鑰）", "kind": "openai",
        "base_url": "https://api.jarvisclaw.ai/v1", "model": "auto/free",
        "models": ["auto/free"],
        "key_mode": "none", "key_url": "", "no_signup": True,
        "cost": "免費（不用金鑰）",
        "limits": "依 IP 限流，上限沒有公開。2026-11-17 實測一篇約 6 秒（實際由 nvidia/nemotron-3.5-bolt 回答），分析比較短。",
        "notes": "帶任何金鑰都會被拒，所以不用填。",
        "min_interval": 3.0, "max_concurrency": 1,
        "caps": {"json_mode": True, "embeddings": False},
        "verified": "2026-11-22",
    },
    {
        "id": "kilo", "label": "Kilo Gateway（不用金鑰）", "kind": "openai",
        "base_url": "https://api.kilo.ai/api/gateway/v1", "model": "kilo-auto/free",
        "models": ["kilo-auto/free", "reflection/beam-free"],
        "key_mode": "none", "key_url": "", "no_signup": True,
        "cost": "免費（不用金鑰）",
        "limits": "每個 IP 每小時 200 次。2026-11-17 實測：kilo-auto/free 一篇約 35 秒；reflection/beam-free 當天下架（回 404 model unavailable），免費路由隨時會換。",
        "notes": "預設推理設為 low。kilo-auto/free 由 Kilo 指派模型（實測是來源不明的 stealth 模型）。Nemotron 等推理型免費模型太慢，不建議。",
        "min_interval": 18.0, "max_concurrency": 1,
        "caps": {"json_mode": False, "embeddings": False, "vision": False,
                 "extra_body": {"reasoning": {"effort": "low"}}},
        "verified": "2026-11-22",
    },
    {
        "id": "ovh", "label": "OVHcloud AI Endpoints（不用金鑰）", "kind": "openai",
        "base_url": "https://oai.endpoints.kepler.ai.cloud.ovh.net/v1", "model": "gpt-oss-120b",
        "models": ["gpt-oss-120b", "Qwen3.8-27B", "DeepSeek-V4.1-Flash-1017", "Meta-Llama-3_3-70B-Instruct"],
        "key_mode": "none", "key_url": "", "no_signup": True,
        "cost": "免費（不用金鑰）",
        "limits": "每個 IP、每個模型每分鐘 2 次（回應標頭證實），適合當備援。2026-11-06 實測 gpt-oss-120b 一篇約 32 秒；語意搜尋的 Qwen3-Embedding-8B 一次查詢約 1.5 秒（2026-11-18）。",
        "notes": "法國 OVHcloud。帶任何金鑰都會被拒，所以不用填。",
        "min_interval": 31.0, "max_concurrency": 1,
        # gpt-oss-120b reads no images; Qwen3.6-27B on the same service does (2026-11-18 test)
        # Qwen3-Embedding-8B on the same service: recall@1 0.853 on the 300-item test, the same as the
        # best local model (2026-11-18), so a fresh install searches by meaning with no Ollama
        "caps": {"json_mode": True, "embeddings": True, "embedding_model": "Qwen3-Embedding-8B",
                 "context": 131072, "vision_model": "Qwen3.6-27B"},
        "verified": "2026-11-22",
    },
    {
        "id": "blockrun", "label": "BlockRun（不用金鑰）", "kind": "openai",
        "base_url": "https://blockrun.ai/api/v1", "model": "nvidia/nemotron-3-super-120b",
        "models": ["nvidia/nemotron-3-super-120b", "nvidia/nemotron-3.5-lightning", "nvidia/nemotron-3-ultra-550b",
                   "nvidia/minimax-m3.1-flash"],
        "key_mode": "none", "key_url": "", "no_signup": True,
        "cost": "免費（不用金鑰）",
        "limits": "每個 IP 每分鐘 30 次、每小時 300 次（官方 rate limits 頁）。指定的免費模型滿載時，會自動改用另一個免費模型，"
                  "回應照樣成功。2026-11-23 實測 nemotron-3-super-120b 一篇約 5 到 9 秒，繁中 JSON 正常。",
        "notes": "只用 /free 頁列的免費模型；清單上其他模型要付費。"
                 "這幾個都是推理模型，輸出 token 大多花在思考。",
        # 300 an hour per IP is one every 12 s
        "min_interval": 12.0, "max_concurrency": 1,
        "caps": {"json_mode": True, "embeddings": False},
        "verified": "2026-11-23",
    },
    {
        "id": "freellmapi", "label": "FreeLLMAPI 本機閘道", "kind": "openai",
        "base_url": "http://127.0.0.1:3001/v1", "model": "auto",
        "models": ["auto", "auto:fast", "auto:smart", "auto:balanced"],
        "embedding_model": "auto",
        "key_mode": "required", "key_url": "https://github.com/tashfeenahmed/freellmapi",
        "editable_url": True,
        "cost": "0（自動聚合多家免費層 API，由 FreeLLMAPI 統一維護）",
        "limits": "預設連到本機 127.0.0.1:3001/v1；支援多家免費服務商自動路由、429 降級與額度追蹤，不必逐一維護每張免費卡片。",
        "notes": "先安裝並啟動本機 FreeLLMAPI（Windows 可用 winget install 9PBN6G8K2B7F），在桌面程式內填入免費服務商金鑰，再到 Keys 頁複製 freellmapi- 開頭的 unified key 貼到此處。若拿來做語意向量，auto 會隨預設 family 變動，建議改填固定向量模型名避免維度不一致。",
        "min_interval": 0.5, "max_concurrency": 2,
        "caps": {"json_mode": True, "embeddings": True},
        "verified": "2026-11-27",
    },
    {
        "id": "omniroute", "label": "OmniRoute 閘道", "kind": "openai",
        "base_url": "http://127.0.0.1:20128/v1", "model": "",
        "models": [],
        "key_mode": "optional", "key_url": "",
        "editable_url": True,
        "cost": "0（看你接的服務商）",
        "limits": "把多家 API key 的免費層併成一個端點並自動備援。",
        "notes": "只接 API key 類服務商，不要接 OAuth 或 cookie 類來源；OmniRoute 要只綁本機（OMNIROUTE_SERVER_HOST=127.0.0.1）。",
        "min_interval": 1.0, "max_concurrency": 2,
        "caps": {"json_mode": True, "embeddings": False},
    },
    {
        "id": "ollama", "label": "本機 Ollama", "kind": "ollama",
        "base_url": "http://127.0.0.1:11434", "model": "qwen3:8b",
        "models": ["qwen3:8b"],
        "embedding_model": "embeddinggemma-2",
        "key_mode": "none", "key_url": "",
        "editable_url": True,
        "cost": "0",
        "limits": "沒有額度上限、可以離線；速度看顯示卡。",
        "notes": "要先安裝 Ollama 並下載模型，例如 ollama pull qwen3:8b。提問與向量都可以用。",
        "min_interval": 0.1, "max_concurrency": 2,
        "caps": {"json_mode": True, "embeddings": True},
    },
    {
        "id": "deepseek", "label": "DeepSeek", "kind": "openai",
        "base_url": "https://api.deepseek.com/v1", "model": "deepseek-chat",
        "models": ["deepseek-chat"],
        "key_mode": "required", "key_url": "https://platform.deepseek.com/api_keys",
        "cost": "付費（便宜）",
        "limits": "額度充足；每天 500 篇約每月 8 到 40 美元（含其他便宜 API 的估計）。",
        "notes": "最省事的付費選項之一。",
        "min_interval": 0.5, "max_concurrency": 2,
        "caps": {"json_mode": True, "embeddings": False, "context": 128000},
    },
    {
        "id": "openai", "label": "OpenAI", "kind": "openai",
        "base_url": "https://api.openai.com/v1", "model": "gpt-4o-mini",
        "models": ["gpt-4o-mini"],
        "embedding_model": "text-embedding-3-small",
        "key_mode": "required", "key_url": "https://platform.openai.com/api-keys",
        "cost": "付費",
        "limits": "依帳號等級。",
        "notes": "有向量（text-embedding-3-small）。",
        "min_interval": 0.5, "max_concurrency": 2,
        "caps": {"json_mode": True, "embeddings": True, "context": 128000},
    },
    {
        "id": "custom", "label": "自訂 OpenAI 相容端點", "kind": "openai",
        "base_url": "", "model": "",
        "models": [],
        "key_mode": "optional", "key_url": "",
        "editable_url": True,
        "cost": "看服務商",
        "limits": "—",
        "notes": "LM Studio、vLLM、llama.cpp server、自架閘道，或任何 OpenAI 相容服務。",
        "min_interval": 1.0, "max_concurrency": 2,
        "caps": {"json_mode": True, "embeddings": False},
    },
]

# How the settings page and the first-run guide sort the cards: by what kind of free the service
# is, so a person sees which ones need nothing, which refill by themselves and which run out
# (2026-11-22: 23 cards in one flat list told none of that). `how` is how to use that kind.
GROUPS: List[Dict[str, str]] = [
    {"id": "keyless", "title": "不用註冊，馬上能用",
     "how": "不用帳號也不用金鑰，剛裝好就能分析。速度和穩定度沒有保證，適合先用、之後當保底。"},
    {"id": "recurring", "title": "註冊就有，額度會自動補回",
     "how": "用 Google 或 email 註冊、拿一把免費金鑰。每分鐘、每天或每週有上限，用完過一陣子會補回。"
            "建兩到三條加到「分析」，一條撞到上限就自動換下一條。"},
    {"id": "grant", "title": "送一筆額度，用完就沒",
     "how": "註冊送的一次性額度，或有截止日的限時活動。適合一次重跑大量舊收藏；用完或活動結束，就從用途裡拿掉。"},
    {"id": "subscription", "title": "用你已經付費的方案",
     "how": "已經訂閱 Google AI Pro 的話，每月的 Google Cloud 抵免額可以拿來分析。一定要在帳單設支出上限，抵免額用完才不會直接扣卡。"},
    {"id": "local", "title": "在自己電腦上跑",
     "how": "完全免費、不限次數，資料不出這台電腦。搜尋用的向量建議用它；拿來分析要看電腦效能。"},
    {"id": "paid", "title": "付費或自訂",
     "how": "按用量付費的服務，或你自己的 OpenAI 相容端點、閘道。"},
]
GROUP_BY_CARD: Dict[str, str] = {
    "flm": "keyless", "jarvisclaw": "keyless", "kilo": "keyless", "ovh": "keyless", "blockrun": "keyless",
    "agnes": "recurring", "gemini": "recurring", "groq": "recurring", "cloudflare": "recurring",
    "openrouter": "recurring", "zai": "recurring", "tokenharbor": "recurring", "requesty": "recurring",
    "nvidia": "recurring", "aihubmix": "recurring", "sealion": "recurring",
    "bazaarlink": "recurring", "cheapllm": "recurring",
    "inception": "grant", "itera": "grant",
    "vertex": "subscription",
    "ollama": "local",
    "freellmapi": "paid", "omniroute": "paid", "deepseek": "paid", "openai": "paid", "custom": "paid",
}

# Raise it whenever a card's data changes (YYYYMMDDNN), then run `python -m app.catalog_remote --write`:
# installs fetch catalog/omnikeep-catalog.json and use it only when its revision is higher than theirs.
CATALOG_REVISION = 2026112702

# The fallback order the picker suggests first (2026-11-23, layout D): a person who does not
# want to compare 23 services gets three free connections that cover for each other, in order.
RECOMMENDED: List[Dict[str, str]] = [
    {"card": "gemini", "why": "分析最完整，能讀 YouTube 影片"},
    {"card": "groq", "why": "每日 1,000 次，速度快"},
    {"card": "flm", "why": "不用註冊，當保底"},
]

CARD_BY_ID: Dict[str, Dict[str, Any]] = {card["id"]: card for card in CARDS}
KINDS = ("openai", "gemini", "ollama")


def card(card_id: str) -> Optional[Dict[str, Any]]:
    return CARD_BY_ID.get(card_id)


def guess_card(base_url: str, kind: str = "openai") -> str:
    """The card an existing address most likely came from (used when migrating .env settings)."""
    if kind == "gemini":
        return "gemini"
    url = (base_url or "").lower()
    for card_id, marker in (("agnes", "agnes-ai.com"), ("groq", "api.groq.com"),
                            ("cloudflare", "api.cloudflare.com"), ("openrouter", "openrouter.ai"),
                            ("zai", "api.z.ai"), ("inception", "inceptionlabs.ai"), ("tokenharbor", "tokenharbor.ai"),
                            ("requesty", "requesty.ai"), ("nvidia", "integrate.api.nvidia.com"),
                            ("aihubmix", "aihubmix.com"), ("sealion", "api.sea-lion.ai"),
                            ("itera", "iteracompute.com"), ("kilo", "api.kilo.ai"), ("blockrun", "blockrun.ai"),
                            ("bazaarlink", "bazaarlink.ai"), ("cheapllm", "cheapllm.shop"), ("ovh", "endpoints.kepler.ai.cloud.ovh.net"),
                            ("freellmapi", "127.0.0.1:3001"), ("freellmapi", "localhost:3001"),
                            ("omniroute", ":20128"), ("deepseek", "api.deepseek.com"),
                            ("openai", "api.openai.com"), ("ollama", ":11434")):
        if marker in url:
            return card_id
    return "custom"


def ended(c: Dict[str, Any], today: Optional[str] = None) -> bool:
    """Whether a card's limited-time offer is over (its `ends` day has passed, local time)."""
    ends = c.get("ends") or ""
    return bool(ends) and (today or datetime.now().astimezone().date().isoformat()) > ends


def catalog() -> Dict[str, Any]:
    """What GET /api/ai/catalog returns."""
    cards = []
    for c in CARDS:
        cards.append({
            "editable_url": False, "embedding_model": "", "no_signup": False, "oauth": "",
            "verified": VERIFIED, "ends": "", "model_extra_body": {},
            **c,  # a card checked later carries its own "verified"
            "group": GROUP_BY_CARD.get(c["id"], "paid"),
            "ended": ended(c),
        })
    from app import catalog_remote  # a fetched catalog may have changed the cards' data fields
    return {"verified": VERIFIED, "revision": catalog_remote.revision(), "cards": cards, "groups": GROUPS,
            "recommended": RECOMMENDED}
