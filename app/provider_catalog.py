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
        "limits": "據稱只有 1 個並發（第三方說法）。",
        "notes": "適合單線程的背景工作。模型代號依官網名稱，按「測試」可確認。",
        "min_interval": 2.0, "max_concurrency": 1,
        "caps": {"json_mode": True, "embeddings": False, "context": 128000},
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
                            ("zai", "api.z.ai"), ("omniroute", ":20128"), ("deepseek", "api.deepseek.com"),
                            ("openai", "api.openai.com"), ("ollama", ":11434")):
        if marker in url:
            return card_id
    return "custom"


def catalog() -> Dict[str, Any]:
    """What GET /api/ai/catalog returns."""
    cards = []
    for c in CARDS:
        cards.append({
            "editable_url": False, "embedding_model": "", "training_note": "",
            **c, "verified": VERIFIED,
        })
    return {"verified": VERIFIED, "cards": cards}
