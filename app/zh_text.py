"""Simplified Chinese that slipped into text the AI wrote, turned into Taiwan Traditional.

The analysis prompt asks for Traditional Chinese, but the no-signup services (Qwen and similar
models) still write some Simplified: the 2026-11-18 new-user trial saved titles such as
「从零手寫 GPT」 and 「本地知识库问答」. OpenCC s2twp fixes those, with Taiwan wording.

It is applied only when the text has a character that is Simplified for sure. Run on text that is
already Traditional, s2twp still rewrites words (「台灣」 to 「臺灣」, 「發佈」 to 「釋出」), and the
characters below are written in Traditional text too (游泳, 干擾, 公里, 准許...): in 2,508 saved
analyses they were the only ones OpenCC would change. Without opencc the text stays as it is.
"""
import logging
from typing import Any, Dict, Iterable

logger = logging.getLogger("omnikeep.zh")

# Characters OpenCC maps to another form that Traditional text still uses as they are.
AMBIGUOUS = frozenset("台准游干里污占划斗朴佣夸雇丰烟余")

_converters: Any = None


def _load():
    global _converters
    if _converters is None:
        try:
            import opencc
            _converters = (opencc.OpenCC("s2tw"), opencc.OpenCC("s2twp"))
        except Exception as exc:  # an install without opencc keeps working
            logger.warning("[zh] opencc is not available (%s: %s); Simplified Chinese the AI writes stays "
                           "Simplified (pip install -r requirements.txt)", type(exc).__name__, exc)
            _converters = False
    return _converters


def has_simplified(text: str) -> bool:
    """A character in the text is Simplified for sure (not one Traditional text also uses)."""
    conv = _load()
    if not conv or not text:
        return False
    chars = {c for c in text if "一" <= c <= "鿿" and c not in AMBIGUOUS}
    return any(conv[0].convert(c) != c for c in chars)


def fix_simplified(text: str) -> str:
    """Taiwan Traditional when the text has Simplified in it; otherwise exactly as it was."""
    if not isinstance(text, str) or not has_simplified(text):
        return text
    out = _converters[1].convert(text)
    # 「台」 is how Taiwan writes it; s2twp turns it into 「臺」.
    if "臺" not in text:
        out = out.replace("臺", "台")
    return out


def fix_fields(record: Dict[str, Any], keys: Iterable[str]) -> Dict[str, Any]:
    """The same record with the named text fields (or lists of text) fixed in place."""
    for key in keys:
        value = record.get(key)
        if isinstance(value, str):
            record[key] = fix_simplified(value)
        elif isinstance(value, list):
            record[key] = [fix_simplified(v) if isinstance(v, str) else v for v in value]
    return record
