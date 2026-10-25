"""Secret redaction layer — the ONE hard rule that applies to every preset.

Anything OmniKeep sends to a cloud LLM (Agnes) passes through redact_text()
first. Filename risk detection powers the L0 desktop risk scan (filenames
only, contents never opened).
"""
import re
from typing import List

# ── Content patterns: credential formats (gitleaks-style, hand-tuned) ──
_CONTENT_PATTERNS = [
    ("openai-key", re.compile(r"sk-[A-Za-z0-9_-]{20,}")),
    ("github-token", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{30,}\b")),
    ("github-pat", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b")),
    ("aws-key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("google-key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("slack-token", re.compile(r"\bxox[baprs]-[0-9A-Za-z-]{10,}\b")),
    ("telegram-bot", re.compile(r"\b\d{8,10}:AA[A-Za-z0-9_-]{30,}\b")),
    ("private-key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("bearer", re.compile(r"\bBearer\s+[A-Za-z0-9._-]{20,}")),
    # keyword assignments: api_key=..., okx_secret: ..., passphrase: "..."
    # (?<![a-z0-9]) lets the keyword appear after an underscore (OKX_SECRET)
    # without matching mid-word (tokenizer).
    ("key-assignment", re.compile(
        r"(?i)(?<![a-z0-9])(?:password|passwd|secret|token|credential|"
        r"api[_-]?key|apikey|access[_-]?key|secret[_-]?key|client[_-]?secret|"
        r"passphrase)['\"]?\s*[:=]\s*['\"]?[A-Za-z0-9+/_-]{12,}")),
]

# ── Filename risk detection (L0: names only, contents never opened) ──
# A file is risky when (a) a always-secret suffix matches, OR
# (b) it has a "note-like" extension AND its stem carries a secret keyword.
# .env.example / .env.sample are TEMPLATES with no real secrets — excluded.
_ALWAYS_RISKY_SUFFIX = re.compile(
    r"(?i)\.(?:pem|key|p12|pfx|keystore|jks)$|^\.env$|^id_(?:rsa|ed25519|ecdsa)[^/\\]*$")
_NOTE_LIKE_EXTS = {
    "txt", "csv", "json", "md", "log", "dat", "xml", "yml", "yaml",
    "ini", "conf", "bak", "old", "doc", "docx", "xls", "xlsx",
}
# Substring compounds — safe against README/requirements because of the
# extension guard above (code files like token_bucket.py never reach here).
_STEM_COMPOUNDS = (
    "apikey", "api_key", "api-key", "api_keys", "api-keys",
    "secret_key", "secretkey", "secret-key", "accesskey", "access_key",
    "privatekey", "private_key", "private-key", "passphrase", "credential",
    "mnemonic", "seedphrase", "seed_phrase", "wallet", "keystore",
    "password", "passwd",
)
# Exchange names only count when paired with api/key/secret/token
# (okx_api.txt flags; okx-readonly-contract.md is just documentation).
_EXCHANGE_PAIR = re.compile(
    r"(?i)(?:okx|binance|bybit|kucoin|kraken|coinbase)[_\- ]*(?:api|key|secret|token)")
# Whole-stem tokens — "secret.txt" flags, "secret_architecture.md" does not.
_STEM_EXACT = {"api", "token", "key", "keys", "secret", "seed",
               "password", "passwd", "pwd", "credentials"}


def redact_text(text: str) -> str:
    """Replace credential-shaped substrings with [REDACTED:<kind>] markers."""
    if not text:
        return text
    for kind, pattern in _CONTENT_PATTERNS:
        text = pattern.sub(f"[REDACTED:{kind}]", text)
    return text


def is_risky_filename(name: str) -> bool:
    """True when the FILENAME ALONE (never contents) suggests a plaintext secret."""
    base = name.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    if _ALWAYS_RISKY_SUFFIX.search(base):
        return True
    if "." not in base:
        return False
    stem, _, ext = base.rpartition(".")
    if ext.lower() not in _NOTE_LIKE_EXTS:
        return False
    lowered = stem.lower()
    if any(c in lowered for c in _STEM_COMPOUNDS):
        return True
    if _EXCHANGE_PAIR.search(lowered):
        return True
    return lowered in _STEM_EXACT


def find_risky_files(files: List[str]) -> List[str]:
    return sorted(f for f in files if is_risky_filename(f))
