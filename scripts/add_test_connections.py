"""Save free-tier test keys as OmniKeep connections (encrypted, not placed in any slot).

Usage (from the OmniKeep folder): python scripts/add_test_connections.py < keys.txt
Each input line is "<provider>: <key>" or "<provider> <key>"; provider names are matched
case-insensitively against PROVIDERS below. Keys are read from stdin only, stored through
OmniKeep's own ai_connections (encrypted), and never printed: output shows the last 4
characters at most. A provider saved before (same label) gets its key replaced.
Then run: python scripts/probe_saved.py
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import ai_connections  # noqa: E402

PREFIX = "免費測試-"
# alias -> (label, card, base_url, model, extra models worth probing)
PROVIDERS = {
    "nvidia": ("NVIDIA NIM", "nvidia", "https://integrate.api.nvidia.com/v1", "deepseek-ai/deepseek-v4.1-flash",
               ["z-ai/glm-5.3-flash", "moonshotai/kimi-k2.6", "moonshotai/kimi-k3.1-pro",
                "mistralai/mistral-large-4-1t-a52b", "minimaxai/minimax-m3.1-flash"]),
    "inception": ("Inception", "inception", "https://api.inceptionlabs.ai/v1", "mercury-3", []),
    "itera": ("Itera Compute", "itera", "https://api.iteracompute.com/v1", "qwen/qwen3.8-27b", []),
    "sealion": ("SEA-LION", "sealion", "https://api.sea-lion.ai/v1", "aisingapore/Qwen-SEA-LION-v4.5-27B-IT", []),
    "requesty": ("Requesty", "requesty", "https://router.requesty.ai/v1", "google/gemma-4-31b-it",
                 ["poolside/laguna-m.1", "novita/ling-3.1-flash"]),
    "aihubmix": ("AIHubMix", "aihubmix", "https://aihubmix.com/v1", "glm-4.7-flash-free", ["gemma-4-31b-it-free"]),
    "tokenharbor": ("Token Harbor", "tokenharbor", "https://tokenharbor.ai/v1", "deepseek-v4.1-flash:free",
                    ["mimo-v2.6-flash:free"]),
    "zai": ("Z.ai", "zai", "https://api.z.ai/api/paas/v4", "glm-4.5-flash", ["glm-4.7-flash"]),
    "mistral": ("Mistral", "custom", "https://api.mistral.ai/v1", "mistral-small-latest", []),
    "openrouter": ("OpenRouter", "openrouter", "https://openrouter.ai/api/v1", "google/gemma-4-31b-it:free", []),
    "groq": ("Groq", "groq", "https://api.groq.com/openai/v1", "qwen/qwen3.8-27b", []),
    "cohere": ("Cohere", "custom", "https://api.cohere.ai/compatibility/v1", "command-a-03-2025", []),
}
ALIASES = {"nim": "nvidia", "sea-lion": "sealion", "token harbor": "tokenharbor", "z.ai": "zai",
           "智譜": "zai", "mercury": "inception", "iteracompute": "itera"}


def resolve(name: str):
    n = re.sub(r"\s+", " ", name.strip().lower())
    n = ALIASES.get(n, n)
    if n in PROVIDERS:
        return n
    for alias in PROVIDERS:
        if alias in n.replace(" ", "").replace("-", ""):
            return alias
    return None


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    existing = {c.label: c for c in ai_connections.list_connections()}
    for raw in sys.stdin.read().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"^(.+?)\s*[:：=]\s*(\S+)$", line) or re.match(r"^(\S+)\s+(\S+)$", line)
        if not m:
            print("看不懂這一行（格式：名稱: 金鑰），跳過")
            continue
        alias = resolve(m.group(1))
        if not alias:
            print(f"不認得「{m.group(1)[:30]}」，跳過")
            continue
        label, card, base_url, model, _ = PROVIDERS[alias]
        full_label = PREFIX + label
        data = {"card": card, "label": full_label, "base_url": base_url, "model": model, "key": m.group(2)}
        try:
            if full_label in existing:
                conn = ai_connections.update(existing[full_label].id, data)
                verb = "更新"
            else:
                conn = ai_connections.create(data)
                verb = "新增"
        except ai_connections.AIConfigError as exc:
            print(f"{full_label}：存檔失敗 {exc.errors}")
            continue
        print(f"{verb} {full_label}（id {conn.id}，金鑰 {ai_connections.key_hint(conn.key) or '已存'}）")


if __name__ == "__main__":
    main()
