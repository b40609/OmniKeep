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
`no_signup` marks a public service usable with no account at all (Kilo, OVHcloud): the
wizard lists those first and the setup Skill offers them to someone with no keys yet.
"""
from typing import Any, Dict, List, Optional

VERIFIED = "2026-11-05"

CARDS: List[Dict[str, Any]] = [
    {
        "id": "agnes", "label": "Agnes", "kind": "openai",
        "base_url": "https://apihub.agnes-ai.com/v1", "model": "agnes-3.0-flash",
        "models": ["agnes-3.0-flash"],
        "key_mode": "required", "key_url": "https://platform.agnes-ai.com/settings/apiKeys",
        "cost": "免費（體驗價 0 美元）",
        "limits": "每把金鑰每分鐘約 10 次（2026-11-05 實測，企業金鑰相同）；沒有向量。建議間隔 7 秒，兩把金鑰可以各建一條連線輪流用。",
        "notes": "很適合當保底；context 512K。",
        "min_interval": 7.0, "max_concurrency": 1,
        "caps": {"json_mode": True, "embeddings": False, "context": 512000},
    },
    {
        "id": "gemini", "label": "Google Gemini（AI Studio）", "kind": "gemini",
        "base_url": "", "model": "gemini-2.5-flash",
        "models": ["gemini-2.5-flash", "gemini-2.5-flash-lite"],
        "key_mode": "required", "key_url": "https://aistudio.google.com/apikey",
        "cost": "免費層",
        "limits": "Flash 約每分鐘 5 次、每日 20 次；Flash-Lite 約每分鐘 10 次、每日 500 次（第三方數據）。可以填多把金鑰，用逗號分隔，輪流使用。",
        "notes": "YouTube 影片解析只有 Gemini 能做。",
        "training_note": "免費層的內容會被 Google 拿去改進產品。",
        "min_interval": 12.0, "max_concurrency": 1,
        "caps": {"json_mode": True, "embeddings": False, "video": True, "context": 1000000},
    },
    {
        "id": "groq", "label": "Groq", "kind": "openai",
        "base_url": "https://api.groq.com/openai/v1", "model": "llama-3.3-70b-versatile",
        "models": ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"],
        "key_mode": "required", "key_url": "https://console.groq.com/keys",
        "cost": "免費層",
        "limits": "每個模型每分鐘 30 次、每日約 1,000 次、每日 20 萬 token；沒有向量。",
        "notes": "速度快，支援嚴格 JSON schema。",
        "min_interval": 2.5, "max_concurrency": 2,
        "caps": {"json_mode": True, "embeddings": False, "context": 131072},
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
    },
    {
        "id": "openrouter", "label": "OpenRouter（:free 模型）", "kind": "openai",
        "base_url": "https://openrouter.ai/api/v1", "model": "meta-llama/llama-3.3-70b-instruct:free",
        "models": ["meta-llama/llama-3.3-70b-instruct:free"],
        "key_mode": "required", "key_url": "https://openrouter.ai/keys",
        "cost": "免費（:free 模型）",
        "limits": "每分鐘 20 次；每日 50 次，累計儲值滿 10 美元後變每日 1,000 次。",
        "notes": "免費模型常替換：按「測試」會列出目前可用的模型。",
        "min_interval": 3.0, "max_concurrency": 1,
        "caps": {"json_mode": True, "embeddings": False, "context": 131072},
    },
    {
        "id": "zai", "label": "Z.AI（GLM Flash）", "kind": "openai",
        "base_url": "https://api.z.ai/api/paas/v4", "model": "glm-4.7-flash",
        "models": ["glm-4.7-flash", "glm-4.5-flash"],
        "key_mode": "required", "key_url": "https://z.ai/manage-apikey/apikey-list",
        "cost": "免費（Flash 模型）",
        "limits": "據稱只有 1 個並發（第三方說法）。2026-11-06 實測（關閉推理）：glm-4.7-flash 一篇約 28 秒；不關閉時超過 300 秒逾時。",
        "notes": "適合單線程的背景工作。用 email 註冊即可。預設關閉推理（thinking disabled）。",
        "min_interval": 2.0, "max_concurrency": 1,
        "caps": {"json_mode": True, "embeddings": False, "context": 128000,
                 "extra_body": {"thinking": {"type": "disabled"}}},
        "verified": "2026-11-06",
    },
    # Added 2026-11-06 from docs/free_llm_channels_2026-11.md: each passed the full analysis
    # prompt in a live test (section 2 there). Times are one sample, not a guarantee.
    {
        "id": "inception", "label": "Inception（Mercury 3）", "kind": "openai",
        "base_url": "https://api.inceptionlabs.ai/v1", "model": "mercury-3",
        "models": ["mercury-3", "mercury-2.5"],
        "key_mode": "required", "key_url": "https://platform.inceptionlabs.ai/",
        "cost": "免費額度（新帳號一次送 100M token）",
        "limits": "一次性額度，用完要綁卡；沒有向量。2026-11-06 實測一篇分析約 5 秒、每秒約 430 token。",
        "notes": "目前實測最快；context 1M。標題偶爾夾簡體。",
        "min_interval": 1.0, "max_concurrency": 2,
        "caps": {"json_mode": True, "embeddings": False, "context": 1000000},
        "verified": "2026-11-06",
    },
    {
        "id": "tokenharbor", "label": "Token Harbor（:free 模型）", "kind": "openai",
        "base_url": "https://tokenharbor.ai/v1", "model": "deepseek-v4.1-flash:free",
        "models": ["deepseek-v4.1-flash:free", "mimo-v2.6-flash:free"],
        "key_mode": "required", "key_url": "https://tokenharbor.ai/dashboard/api-keys",
        "cost": "免費（:free 模型）",
        "limits": "每 7 天滾動的免費額度（金額沒公開），約每分鐘 60 次（第三方數據）；免費模型要先在 dashboard 手動開啟。2026-11-06 實測一篇約 19 秒。",
        "notes": "新加坡公司 TH TECHNOLOGY PTE. LTD.；位址沒有 api. 子網域。",
        "training_note": "免費路由的內容可能被留存分析，上游服務商可能拿去訓練。",
        "min_interval": 1.0, "max_concurrency": 1,
        "caps": {"json_mode": True, "embeddings": False},
        "verified": "2026-11-06",
    },
    {
        "id": "requesty", "label": "Requesty（免費模型）", "kind": "openai",
        "base_url": "https://router.requesty.ai/v1", "model": "google/gemma-4-31b-it",
        "models": ["google/gemma-4-31b-it", "novita/ling-3.1-flash"],
        "key_mode": "required", "key_url": "https://www.requesty.ai/free-models",
        "cost": "免費（免費模型）",
        "limits": "每天 200 次，所有免費模型共用。2026-11-06 實測一篇約 57 秒。",
        "notes": "有公司實體與 DPA。ling-3.1-flash 不支援 JSON 格式參數，會改用一般請求再解析。",
        "min_interval": 3.0, "max_concurrency": 1,
        "caps": {"json_mode": True, "embeddings": False},
        "verified": "2026-11-06",
    },
    {
        "id": "nvidia", "label": "NVIDIA NIM（Free Endpoint）", "kind": "openai",
        "base_url": "https://integrate.api.nvidia.com/v1", "model": "minimaxai/minimax-m3.1-flash",
        "models": ["minimaxai/minimax-m3.1-flash", "mistralai/mistral-large-4-1t-a52b"],
        "key_mode": "required", "key_url": "https://build.nvidia.com/settings/api-keys",
        "cost": "免費（Free Endpoint 模型）",
        "limits": "約每分鐘 40 次，整個帳號共用（社群數據）。免費端點很擠：2026-11-06 實測一篇 80 到 190 秒。",
        "notes": "條款寫明不能用在 production。免費端點很擠，時間波動大；DeepSeek V4.1 Flash 要帶 chat_template_kwargs thinking false 才有正文，其他模型帶了沒效果或更慢，所以預設不帶。",
        "min_interval": 2.0, "max_concurrency": 1,
        "caps": {"json_mode": True, "embeddings": False},
        "verified": "2026-11-06",
    },
    {
        "id": "aihubmix", "label": "AIHubMix（-free 模型）", "kind": "openai",
        "base_url": "https://aihubmix.com/v1", "model": "glm-4.7-flash-free",
        "models": ["glm-4.7-flash-free"],
        "key_mode": "required", "key_url": "https://console.aihubmix.com/token",
        "cost": "免費（-free 模型）",
        "limits": "第三方整理：多數免費模型每分鐘 5 次、每天 100 次，glm-4.7-flash-free 每天 500 次。2026-11-06 實測（關閉推理）一篇約 43 秒。",
        "notes": "免費模型會輪替：按「測試」會列出目前的模型。預設關閉推理（thinking disabled）。",
        "min_interval": 12.0, "max_concurrency": 1,
        "caps": {"json_mode": True, "embeddings": False, "extra_body": {"thinking": {"type": "disabled"}}},
        "verified": "2026-11-06",
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
        "verified": "2026-11-06",
    },
    {
        "id": "itera", "label": "Itera Compute（Qwen3.8 27B）", "kind": "openai",
        "base_url": "https://api.iteracompute.com/v1", "model": "qwen/qwen3.8-27b",
        "models": ["qwen/qwen3.8-27b"],
        "key_mode": "required", "key_url": "https://platform.iteracompute.com/api-keys",
        "cost": "免費（限時活動，到 2026-11-24）",
        "limits": "每月 30M token，超額回 429，不會自動扣款。推理型，一篇約 9,000 token（每月約 3,300 篇）；2026-11-06 實測一篇約 165 秒。",
        "notes": "活動結束後要重新確認還能不能免費用。試過用 enable_thinking false 關閉推理，反而逾時，所以不帶。",
        "min_interval": 2.0, "max_concurrency": 1,
        "caps": {"json_mode": True, "embeddings": False},
        "verified": "2026-11-06",
    },
    {
        "id": "kilo", "label": "Kilo Gateway（不用金鑰）", "kind": "openai",
        "base_url": "https://api.kilo.ai/api/gateway/v1", "model": "reflection/beam-free",
        "models": ["reflection/beam-free", "kilo-auto/free"],
        "key_mode": "none", "key_url": "", "no_signup": True,
        "cost": "免費（不用金鑰）",
        "limits": "每個 IP 每小時 200 次。2026-11-06 實測（低推理）：beam-free 一篇約 14 秒，kilo-auto/free 約 43 秒。",
        "notes": "預設推理設為 low。kilo-auto/free 由 Kilo 指派模型（實測是來源不明的 stealth 模型）。Nemotron 等推理型免費模型太慢，不建議。",
        "training_note": "免費路由的提示與回應會被記錄並用於訓練。",
        "min_interval": 18.0, "max_concurrency": 1,
        "caps": {"json_mode": False, "embeddings": False, "extra_body": {"reasoning": {"effort": "low"}}},
        "verified": "2026-11-06",
    },
    {
        "id": "ovh", "label": "OVHcloud AI Endpoints（不用金鑰）", "kind": "openai",
        "base_url": "https://oai.endpoints.kepler.ai.cloud.ovh.net/v1", "model": "gpt-oss-120b",
        "models": ["gpt-oss-120b", "Meta-Llama-3_3-70B-Instruct"],
        "key_mode": "none", "key_url": "", "no_signup": True,
        "cost": "免費（不用金鑰）",
        "limits": "每個 IP、每個模型每分鐘 2 次（回應標頭證實），適合當備援。2026-11-06 實測 gpt-oss-120b 一篇約 32 秒。",
        "notes": "法國 OVHcloud，官方說不拿來訓練、不留存資料。帶任何金鑰都會被拒，所以不用填。",
        "min_interval": 31.0, "max_concurrency": 1,
        "caps": {"json_mode": True, "embeddings": False, "context": 131072},
        "verified": "2026-11-06",
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
        "notes": "要先安裝 Ollama 並下載模型，例如 ollama pull qwen3:8b。Ask Brain 與向量都可以用。",
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
                            ("itera", "iteracompute.com"), ("kilo", "api.kilo.ai"), ("ovh", "endpoints.kepler.ai.cloud.ovh.net"),
                            ("omniroute", ":20128"), ("deepseek", "api.deepseek.com"),
                            ("openai", "api.openai.com"), ("ollama", ":11434")):
        if marker in url:
            return card_id
    return "custom"


def catalog() -> Dict[str, Any]:
    """What GET /api/ai/catalog returns."""
    cards = []
    for c in CARDS:
        cards.append({
            "editable_url": False, "embedding_model": "", "training_note": "", "no_signup": False,
            "verified": VERIFIED,
            **c,  # a card checked later carries its own "verified"
        })
    return {"verified": VERIFIED, "cards": cards}
