"""What each known embedding model needs: its query format and how many dimensions to keep.

Retrieval models are asymmetric: a search query is wrapped in the model's own instruction,
while stored documents are embedded as they are. Using another model's format costs
recall (the qwen3 and harrier cards say so, and it showed in the 2026-11 tests).

`dim` is how many dimensions are stored, unless EMBEDDING_DIM fixes one for every model.
Measured on 300 saved items with everyday queries (backups/local-runtime-poc-20261114/round3,
r4_*.json): cutting to 256 lost 2 to 15 points of recall@1 for every model, while the
qwen3 models kept at 1024 scored the same as their full 2560 / 4096 (Matryoshka-trained),
so they store 1024. The others store their full width.
"""
from typing import Any, Dict, Optional

from app.config import settings

# Used for a model this table does not know, the hashed fallback and remote endpoints
# that are asked for a size (OpenAI's `dimensions`).
DEFAULT_DIM = 256

_RETRIEVE = "Instruct: Given a web search query, retrieve relevant passages that answer the query\nQuery:"

# Matched against the lower-case model name (an "hf.co/owner/" repo is reduced to the repo
# name), first prefix that fits.
PROFILES = (
    {"prefix": "qwen3-embedding:0.6b", "query": _RETRIEVE + "{q}", "dim": 1024},
    {"prefix": "qwen3-embedding:4b", "query": _RETRIEVE + "{q}", "dim": 1024},
    # Ollama's untagged / :latest qwen3-embedding is the 8B one.
    {"prefix": "qwen3-embedding", "query": _RETRIEVE + "{q}", "dim": 1024},
    {"prefix": "harrier-oss-v1-0.6b", "query": _RETRIEVE + " {q}", "dim": 1024},
    {"prefix": "harrier-oss-v1-270m", "query": _RETRIEVE + " {q}", "dim": 640},
    {"prefix": "embeddinggemma", "query": "task: search result | query: {q}", "dim": 768},
    {"prefix": "bge-m3", "query": "{q}", "dim": 1024},
)


def _key(model: str) -> str:
    name = (model or "").strip().lower()
    if name.startswith("hf.co/"):
        # hf.co/<owner>/<repo>-GGUF:<quant> -> <repo>
        name = name.split("/", 2)[-1]
        name = name.split(":", 1)[0].removesuffix("-gguf").removesuffix("-i1")
    return name


def profile(model: str) -> Optional[Dict[str, object]]:
    key = _key(model)
    bare = key.split(":", 1)[0]
    for p in PROFILES:
        prefix = str(p["prefix"])
        if key.startswith(prefix) or (":" not in prefix and bare.startswith(prefix)):
            return p
    return None


def model_dim(model: str) -> int:
    """How many dimensions vectors of `model` are stored with."""
    fixed = int(getattr(settings, "EMBEDDING_DIM", 0) or 0)
    if fixed > 0:
        return fixed
    p = profile(model)
    return int(p["dim"]) if p else DEFAULT_DIM


def query_text(model: str, text: str) -> str:
    """A search query in `model`'s own format (documents are embedded as they are)."""
    p = profile(model)
    return str(p["query"]).format(q=text) if p else text


# Which local model a machine gets: the first tier the hardware meets, best first.
# recall_at_1 is on 300 saved items with everyday Chinese queries ("nl" in round3/r4_*.json);
# embeddinggemma-2 at the old 256 dimensions scored 0.70 there. Measured on one machine
# (a 16 GB NVIDIA card, a desktop CPU, 64 GB RAM); the thresholds for other machines are estimates.
# Left out: KaLM-Embedding-Gemma3-12B (Ollama loads it as embeddinggemma and its vectors come
# out wrong, recall@1 0.24) and harrier-oss-v1-27b (15.4 GB at Q4, more than a 16 GB card has free).
TIERS = (
    {"model": "qwen3-embedding:8b", "min_vram_gb": 8, "recall_at_1": 0.853, "size_gb": 4.7,
     "why": "顯示卡夠大：品質最好的本機向量模型，查詢約 0.1 秒"},
    {"model": "qwen3-embedding:4b", "min_vram_gb": 4, "recall_at_1": 0.80, "size_gb": 2.5,
     "why": "中階顯示卡：品質次之，查詢約 0.06 秒"},
    {"model": "hf.co/mradermacher/harrier-oss-v1-0.6b-GGUF:Q8_0", "min_ram_gb": 8, "recall_at_1": 0.79,
     "size_gb": 0.64, "why": "沒有可用的顯示卡：只用 CPU 時品質與速度最平衡，查詢約 0.12 秒"},
    {"model": "hf.co/mykor/harrier-oss-v1-270m-GGUF:Q8_0", "recall_at_1": 0.737, "size_gb": 0.29,
     "why": "記憶體較少：最小的模型，品質仍高於舊的設定"},
)


def recommend(hardware: Dict[str, Any]) -> Dict[str, Any]:
    """The local embedding model for a machine, from the setup scan's hardware block
    (gpus: [{name, vram_gb}], ram_gb, os, cpu). Only NVIDIA cards are seen (nvidia-smi).
    Apple Silicon shares its memory with the GPU, so half of it counts as VRAM there (an estimate)."""
    gpus = hardware.get("gpus") or []
    vram = max((float(g.get("vram_gb") or 0) for g in gpus), default=0.0)
    ram = float(hardware.get("ram_gb") or 0)
    if str(hardware.get("os", "")).startswith("Darwin") and "arm" in str(hardware.get("cpu", "")).lower():
        vram = max(vram, ram / 2)
    pick = TIERS[-1]
    for tier in TIERS:
        if "min_vram_gb" in tier:
            if vram >= tier["min_vram_gb"]:
                pick = tier
                break
        elif ram >= tier.get("min_ram_gb", 0):
            pick = tier
            break
    return {**pick, "dim": model_dim(pick["model"]), "vram_gb": vram, "ram_gb": ram}
