"""Keep the free-service cards current without upgrading OmniKeep (2026-11-23).

Free models get renamed and limits change within a week, and the cards used to change only
when someone upgraded. Now the repo carries catalog/omnikeep-catalog.json, exported from
app/provider_catalog.py; every install fetches it twice a day and lays it over its own cards.

What the file may change is limited to data fields (FIELDS): a default model, the model list,
limits and notes, dates, pacing. Where a key is sent (base_url), what kind of service a card is,
whether it takes a key, and any card the install does not already have stay with the installed
code, as Cherry Studio and OpenClaw do: "unsigned data must never control credential
destinations" (docs/reviews/2026-11-23-catalog-auto-update-research.md §4). A file that is not
newer than what is in use, or has any value of the wrong shape, is thrown away whole.

CATALOG_AUTO_UPDATE=false turns it off; the cards shipped with the code are used as they are.

    python -m app.catalog_remote --write    # after editing provider_catalog.py
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from app import provider_catalog
from app.config import BASE_DIR, settings

logger = logging.getLogger("omnikeep.catalog")

SCHEMA = 1
REPO_FILE = BASE_DIR / "catalog" / "omnikeep-catalog.json"
MAX_BYTES = 512 * 1024
INITIAL_DELAY = 30.0
EVERY = 12 * 3600.0

_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _text(limit: int, empty_ok: bool = True) -> Callable[[Any], bool]:
    return lambda v: isinstance(v, str) and len(v) <= limit and (empty_ok or bool(v.strip()))


def _date_or_empty(v: Any) -> bool:
    return v == "" or (isinstance(v, str) and bool(_DATE.match(v)))


def _models(v: Any) -> bool:
    return isinstance(v, list) and len(v) <= 60 and all(_text(160, empty_ok=False)(m) for m in v)


def _quota(v: Any) -> bool:
    if v is None:
        return True
    if not isinstance(v, dict) or v.get("period") not in ("day", "month", "once"):
        return False
    amounts = {k: v[k] for k in v if k != "period"}
    return bool(amounts) and all(k in ("requests", "tokens") and type(n) is int and n > 0 for k, n in amounts.items())


def _number(low: float, high: float) -> Callable[[Any], bool]:
    return lambda v: type(v) in (int, float) and low <= v <= high


# The only card fields the fetched file may set. None of them decides where a key goes.
FIELDS: Dict[str, Callable[[Any], bool]] = {
    "label": _text(80, empty_ok=False),
    "cost": _text(160),
    "limits": _text(800),
    "notes": _text(800),
    "model": _text(160),
    "models": _models,
    "ends": _date_or_empty,
    "verified": lambda v: isinstance(v, str) and bool(_DATE.match(v)),
    "quota": _quota,  # null removes it
    "min_interval": _number(0, 600),
    "max_concurrency": lambda v: type(v) is int and 1 <= v <= 16,
}

_applied_revision: Optional[int] = None


def revision() -> int:
    """The catalog revision in use: a fetched one, or the one shipped with the code."""
    return _applied_revision or provider_catalog.CATALOG_REVISION


def export() -> Dict[str, Any]:
    """What catalog/omnikeep-catalog.json holds: the data fields of the cards in provider_catalog.py."""
    cards = {}
    for c in provider_catalog.CARDS:
        cards[c["id"]] = {k: c[k] for k in FIELDS if k in c}
    return {
        "schema": SCHEMA,
        "revision": provider_catalog.CATALOG_REVISION,
        "cards": cards,
        "group_by_card": dict(provider_catalog.GROUP_BY_CARD),
        "recommended": [dict(r) for r in provider_catalog.RECOMMENDED],
    }


def dumps(data: Dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, indent=1, sort_keys=False) + "\n"


def problem(data: Any) -> str:
    """Why a fetched file must not be used, or '' when it may."""
    if not isinstance(data, dict) or data.get("schema") != SCHEMA:
        return "schema"
    rev = data.get("revision")
    if type(rev) is not int:
        return "revision"
    if rev <= revision():
        return "not newer"
    cards = data.get("cards")
    if not isinstance(cards, dict):
        return "cards"
    for card_id, fields in cards.items():
        if not isinstance(fields, dict):
            return f"card {card_id}"
        for key, value in fields.items():
            check = FIELDS.get(key)
            if check and not check(value):
                return f"{card_id}.{key}"
    groups = {g["id"] for g in provider_catalog.GROUPS}
    by_card = data.get("group_by_card", {})
    if not isinstance(by_card, dict) or not all(isinstance(g, str) and g in groups for g in by_card.values()):
        return "group_by_card"
    recommended = data.get("recommended", [])
    if not isinstance(recommended, list) or len(recommended) > 5 or not all(
            isinstance(r, dict) and r.get("card") in provider_catalog.CARD_BY_ID and _text(80, empty_ok=False)(r.get("why"))
            for r in recommended):
        return "recommended"
    return ""


def apply(data: Any) -> bool:
    """Lay a fetched file over the cards in use. Cards the code does not have are skipped."""
    global _applied_revision
    why = problem(data)
    if why:
        if why != "not newer":
            logger.warning("[Catalog] fetched catalog not used (%s)", why)
        return False
    for card_id, fields in data["cards"].items():
        card = provider_catalog.CARD_BY_ID.get(card_id)
        if card is None:
            continue
        for key, value in fields.items():
            if key not in FIELDS:
                continue
            if value is None:
                card.pop(key, None)
            else:
                card[key] = value
    by_card = {k: v for k, v in data.get("group_by_card", {}).items() if k in provider_catalog.CARD_BY_ID}
    provider_catalog.GROUP_BY_CARD.update(by_card)
    if data.get("recommended"):
        provider_catalog.RECOMMENDED[:] = [{"card": r["card"], "why": r["why"]} for r in data["recommended"]]
    _applied_revision = data["revision"]
    logger.info("[Catalog] using catalog revision %s", _applied_revision)
    return True


def cache_path() -> Path:
    return Path(settings.DATABASE_PATH).resolve().parent / "catalog_overlay.json"


def load_cached() -> bool:
    """At start-up: the last fetched catalog, so an offline restart keeps the newer cards."""
    if not settings.CATALOG_AUTO_UPDATE:
        return False
    try:
        saved = json.loads(cache_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return apply(saved.get("data"))


async def fetch_once() -> bool:
    """Fetch the catalog from the repo and use it when it is newer. True when it changed the cards."""
    import httpx

    if not settings.CATALOG_AUTO_UPDATE or not settings.CATALOG_UPDATE_URL.startswith("https://"):
        return False
    path = cache_path()
    try:
        cached = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cached = {}
    headers = {"If-None-Match": cached["etag"]} if cached.get("etag") else {}
    async with httpx.AsyncClient(timeout=15.0, follow_redirects=False) as client:
        async with client.stream("GET", settings.CATALOG_UPDATE_URL, headers=headers) as resp:
            if resp.status_code == 304:
                return False
            if resp.status_code != 200:
                logger.info("[Catalog] fetch answered HTTP %s", resp.status_code)
                return False
            body = b""
            async for chunk in resp.aiter_bytes():
                body += chunk
                if len(body) > MAX_BYTES:
                    logger.warning("[Catalog] fetched catalog is larger than %s bytes; not used", MAX_BYTES)
                    return False
            etag = resp.headers.get("etag", "")
    try:
        data = json.loads(body.decode("utf-8"))
    except ValueError:
        logger.warning("[Catalog] fetched catalog is not JSON; not used")
        return False
    if not apply(data):
        return False
    try:
        path.write_text(json.dumps({"etag": etag, "data": data}, ensure_ascii=False), encoding="utf-8")
    except OSError as exc:
        logger.warning("[Catalog] could not keep the fetched catalog (%s)", type(exc).__name__)
    return True


async def update_loop(initial_delay: float = INITIAL_DELAY, every: float = EVERY) -> None:
    await asyncio.sleep(initial_delay)
    while True:
        try:
            await fetch_once()
        except Exception as exc:  # offline, DNS, GitHub down: the cards in use stay
            logger.info("[Catalog] fetch failed (%s)", type(exc).__name__)
        await asyncio.sleep(every)


def _main(argv: List[str]) -> int:
    text = dumps(export())
    if "--write" in argv:
        REPO_FILE.parent.mkdir(parents=True, exist_ok=True)
        REPO_FILE.write_text(text, encoding="utf-8", newline="\n")
        sys.stdout.write(f"wrote {REPO_FILE} (revision {provider_catalog.CATALOG_REVISION})\n")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
