"""AI provider connections and the task slots that use them.

A connection is one provider account: a card from app/provider_catalog.py,
an address, a model and an encrypted key (app.secret_box, like the secrets in
app_settings). A slot is a task (analysis, brain, radar, embeddings, video)
with an ordered list of connections: position 0 is tried first, the rest are
its fallback chain (app/providers/chain.py).

Empty slots keep the old behaviour:
  analysis    the settings that predate connections (OPENAI_*, GEMINI_*)
  brain/radar follow the analysis chain (brain/radar also fall back to it
              once their own list is used up)
  embeddings  the old order: Ollama at OLLAMA_BASE_URL, then OPENAI_*, then
              the local hash
  video       GEMINI_* when keys are set

On first start migrate_legacy() turns those flat settings into connections
and slots so nothing changes. Afterwards the flat AI settings can still be
saved through /api/settings (older clients, agents); sync_from_settings()
carries them into the connections they were migrated into. Ask Brain's local
model is still read from BRAIN_* by app/brain.py, so the brain slot writes
those back (push_brain_settings).
"""
import json
import logging
import re
import threading
from contextlib import closing
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urlsplit

from app import provider_catalog, secret_box
from app.config import settings
from app.database import get_db_connection

logger = logging.getLogger("omnikeep.ai_connections")

SLOTS = ("analysis", "brain", "radar", "embeddings", "video")
SLOT_LABELS = {
    "analysis": "分析", "brain": "Ask Brain", "radar": "雷達評分", "embeddings": "向量（語意搜尋）",
    "video": "影片解析",
}
SLOT_HELP = {
    "analysis": "收藏的摘要、分類與深度剖析。清單是空的時候沿用舊的「主要服務商」設定。",
    "brain": "Ask Brain 回答問題。第一個是本機 Ollama 時，會先用它；清單用完後改用分析的清單。",
    "radar": "雷達的相關性評分與每日摘要。清單用完（或是空的）就用分析的清單。",
    "embeddings": "語意搜尋的向量。都失敗時改用本機雜湊向量。換模型後，既有向量要重建才查得到。",
    "video": "YouTube 影片解析（只有 Gemini 能看影片）。失敗時改用分析清單讀影片說明欄。",
}
META_MIGRATED = "legacy_settings_migrated"
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_lock = threading.RLock()
_sync_guard = threading.local()


class AIConfigError(ValueError):
    def __init__(self, errors: Dict[str, str]):
        super().__init__("; ".join(f"{k}: {v}" for k, v in errors.items()))
        self.errors = errors


@dataclass
class Connection:
    id: int
    card: str
    kind: str
    label: str
    base_url: str
    model: str
    key: str = ""
    key_broken: bool = False
    caps: Dict[str, Any] = field(default_factory=dict)
    min_interval: Optional[float] = None
    max_concurrency: Optional[int] = None
    origin: str = ""
    enabled: bool = True
    created_at: str = ""
    updated_at: str = ""

    @property
    def status_key(self) -> str:
        return f"c{self.id}"

    def interval(self) -> float:
        if self.min_interval is not None:
            return float(self.min_interval)
        card = provider_catalog.card(self.card) or {}
        return float(card.get("min_interval") or settings.LLM_MIN_REQUEST_INTERVAL)

    def concurrency(self) -> int:
        if self.max_concurrency is not None:
            return int(self.max_concurrency)
        card = provider_catalog.card(self.card) or {}
        return int(card.get("max_concurrency") or settings.LLM_MAX_CONCURRENCY)

    def embedding_model(self) -> str:
        card = provider_catalog.card(self.card) or {}
        return str(self.caps.get("embedding_model") or card.get("embedding_model") or self.model)


def extra_body_for(conn: Any, model: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Extra request fields for a chat call to `model` through `conn`.

    The connection's own model gets caps["extra_body"] (editable in 設定 › AI 服務商, filled
    from the card's preset when that model was picked). A task slot naming another model gets
    the card's preset for that model when there is one, else the connection's extra_body
    (a provider-wide switch such as Kilo's low reasoning). None when there is nothing to add.
    """
    own = (getattr(conn, "caps", None) or {}).get("extra_body") or None
    if not model or model == getattr(conn, "model", None):
        return own
    presets = (provider_catalog.card(getattr(conn, "card", "") or "") or {}).get("model_extra_body") or {}
    if model in presets:
        return dict(presets[model]) or None
    return own


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Reading ─────────────────────────────────────────────────────

def _to_connection(row) -> Connection:
    key, broken = "", False
    if row["key_enc"]:
        try:
            key = secret_box.decrypt(row["key_enc"])
        except secret_box.SecretUnavailable:
            broken = True
    try:
        caps = json.loads(row["caps_json"] or "{}")
    except ValueError:
        caps = {}
    conn = Connection(
        id=row["id"], card=row["card"], kind=row["kind"], label=row["label"], base_url=row["base_url"],
        model=row["model"], key=key, key_broken=broken, caps=caps if isinstance(caps, dict) else {},
        min_interval=row["min_interval"], max_concurrency=row["max_concurrency"], origin=row["origin"],
        enabled=bool(row["enabled"]), created_at=row["created_at"], updated_at=row["updated_at"],
    )
    from app import ai_status
    ai_status.register_secret(conn.status_key, key)
    return conn


def list_connections() -> List[Connection]:
    try:
        with closing(get_db_connection()) as db:
            rows = db.execute("SELECT * FROM ai_connections ORDER BY id").fetchall()
    except Exception:
        return []
    return [_to_connection(row) for row in rows]


def get_connection(connection_id: int) -> Optional[Connection]:
    with closing(get_db_connection()) as db:
        row = db.execute("SELECT * FROM ai_connections WHERE id = ?", (int(connection_id),)).fetchone()
    return _to_connection(row) if row else None


def slots() -> Dict[str, List[Dict[str, Any]]]:
    out: Dict[str, List[Dict[str, Any]]] = {slot: [] for slot in SLOTS}
    try:
        with closing(get_db_connection()) as db:
            rows = db.execute("SELECT slot, position, connection_id, model FROM ai_slots "
                              "ORDER BY slot, position").fetchall()
    except Exception:
        return out
    for row in rows:
        if row["slot"] in out:
            out[row["slot"]].append({"connection_id": row["connection_id"], "model": row["model"]})
    return out


def resolve(slot: str) -> List[Tuple[Connection, str]]:
    """Enabled connections of a slot in order, each with the model to use for it."""
    entries = slots().get(slot, [])
    if not entries:
        return []
    by_id = {c.id: c for c in list_connections()}
    out: List[Tuple[Connection, str]] = []
    for entry in entries:
        conn = by_id.get(entry["connection_id"])
        if conn is None or not conn.enabled:
            continue
        model = entry["model"] or (conn.embedding_model() if slot == "embeddings" else conn.model)
        out.append((conn, model))
    return out


def legacy_needs_setup() -> bool:
    if settings.PRIMARY_LLM_PROVIDER == "gemini":
        return not settings.gemini_keys
    # Local servers such as Ollama need no key; the default OpenAI address does.
    return not settings.OPENAI_API_KEY and "api.openai.com" in settings.OPENAI_BASE_URL


def needs_setup() -> bool:
    """No usable analysis provider: neither a connection in the slot nor the older settings."""
    if resolve("analysis"):
        return False
    return legacy_needs_setup()


# ── Validation ──────────────────────────────────────────────────

def _text(value: Any, limit: int, name: str, errors: Dict[str, str]) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        errors[name] = "必須是文字"
        return ""
    value = value.strip()
    if _CONTROL.search(value):
        errors[name] = "不能包含換行或控制字元"
    elif len(value) > limit:
        errors[name] = f"太長（上限 {limit} 字元）"
    return value


def _url(value: str, errors: Dict[str, str]) -> str:
    value = value.rstrip("/")
    if "<" in value or ">" in value:
        errors["base_url"] = "把位址裡角括號的部分（例如 <帳號 ID>）換成你自己的值"
        return value
    parsed = urlsplit(value)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        errors["base_url"] = "請填 http:// 或 https:// 開頭的完整網址"
    return value


def _number(value: Any, kind: type, low: float, high: float, name: str, errors: Dict[str, str]):
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        errors[name] = "必須是數字"
        return None
    try:
        number = kind(value)
    except (TypeError, ValueError):
        errors[name] = "必須是數字"
        return None
    if number < low or number > high:
        errors[name] = f"要在 {low:g} 到 {high:g} 之間"
        return None
    return number


def _caps(value: Any, errors: Dict[str, str]) -> Dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        errors["caps"] = "格式不對"
        return {}
    out: Dict[str, Any] = {}
    for flag in ("json_mode", "embeddings", "video"):
        if flag in value:
            out[flag] = bool(value[flag])
    if "context" in value:
        context = _number(value["context"], int, 0, 10_000_000, "caps", errors)
        if context is not None:
            out["context"] = context
    if "embedding_model" in value:
        out["embedding_model"] = _text(value["embedding_model"], 200, "caps", errors)
    if "extra_body" in value:
        extra = _extra_body(value["extra_body"], errors)
        if extra is not None:
            out["extra_body"] = extra
    return out


# Request fields OmniKeep sets itself; extra_body may not override them.
_RESERVED_BODY = {"model", "messages", "stream", "response_format", "tools", "tool_choice", "n"}


def _extra_body(value: Any, errors: Dict[str, str]) -> Optional[Dict[str, Any]]:
    """Extra request fields such as a reasoning switch; {} (or None) removes them."""
    if value is None:
        return {}
    if not isinstance(value, dict) or not all(isinstance(k, str) for k in value):
        errors["caps"] = "extra_body 必須是 JSON 物件"
        return None
    reserved = sorted(_RESERVED_BODY.intersection(value))
    if reserved:
        errors["caps"] = f"extra_body 不能改 {'、'.join(reserved)}"
        return None
    try:
        encoded = json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError):
        errors["caps"] = "extra_body 必須是 JSON 物件"
        return None
    if len(encoded) > 2000:
        errors["caps"] = "extra_body 太長（上限 2000 字元）"
        return None
    return json.loads(encoded)


def validate_extra_body(value: Any) -> Dict[str, Any]:
    """extra_body typed in a form, checked like a saved one; raises AIConfigError."""
    errors: Dict[str, str] = {}
    extra = _extra_body(value, errors)
    if errors:
        raise AIConfigError(errors)
    return extra or {}


def apply_model_preset(card: Dict[str, Any], caps: Dict[str, Any], old_model: Optional[str], model: str) -> None:
    """Moving to a model the card has extra fields for brings them along (in place); moving
    off it puts back the card's default, unless the fields were changed by hand meanwhile."""
    if not model or model == old_model:
        return
    presets = card.get("model_extra_body") or {}
    if model in presets:
        caps["extra_body"] = dict(presets[model])
    elif old_model in presets and caps.get("extra_body") == presets[old_model]:
        default = card.get("caps", {}).get("extra_body")
        if default:
            caps["extra_body"] = dict(default)
        else:
            caps.pop("extra_body", None)


def _clean_key(raw: Any, kind: str, errors: Dict[str, str]) -> str:
    key = _text(raw, 4000, "key", errors)
    if kind == "gemini":
        return ",".join(part.strip() for part in key.split(",") if part.strip())
    if any(ch.isspace() for ch in key):
        errors["key"] = "金鑰中不能有空白"
    return key


def _validate(data: Dict[str, Any], existing: Optional[Connection]) -> Dict[str, Any]:
    """Columns to write. A key of None (or left out) keeps the stored key; "" clears it."""
    errors: Dict[str, str] = {}
    card_id = data.get("card", existing.card if existing else None)
    card = provider_catalog.card(card_id) if isinstance(card_id, str) else None
    if card is None:
        raise AIConfigError({"card": "不是可用的服務商卡片"})
    kind = existing.kind if existing and "card" not in data else card["kind"]
    if existing and existing.origin and "card" not in data:
        kind = existing.kind  # a migrated OpenAI-compatible Ollama keeps speaking /v1
    out: Dict[str, Any] = {"card": card_id, "kind": kind}

    label = _text(data.get("label", existing.label if existing else card["label"]), 80, "label", errors)
    out["label"] = label or card["label"]

    base_url = _text(data.get("base_url", existing.base_url if existing else card["base_url"]), 2000,
                     "base_url", errors)
    if kind == "gemini":
        base_url = ""
    elif not errors.get("base_url"):
        if not base_url:
            errors["base_url"] = "請填 API 位址"
        else:
            base_url = _url(base_url, errors)
    out["base_url"] = base_url

    model = _text(data.get("model", existing.model if existing else card["model"]), 200, "model", errors)
    if not model:
        errors["model"] = "請填模型名稱"
    out["model"] = model

    key_given = "key" in data and data["key"] is not None
    key = _clean_key(data["key"], kind, errors) if key_given else (existing.key if existing else "")
    if existing and not key_given and existing.key_broken:
        key = None  # keep the unreadable token as it is until a new key is typed
    if existing and not key_given and existing.key and base_url.rstrip("/") != existing.base_url.rstrip("/"):
        # The saved key must not silently travel to a host it was never issued for.
        errors["key"] = "更換 API 位址時，請一併重新輸入 API 金鑰"
    if card["key_mode"] == "required" and not key and not (existing and existing.key_broken and not key_given):
        errors["key"] = "請輸入 API 金鑰"
    if card["key_mode"] == "none":
        key = ""
    out["key"] = key

    caps = dict(card.get("caps", {}))
    if existing and existing.card == card_id:
        caps.update(existing.caps)  # a connection moved to another card starts from that card's abilities
    caps.update(_caps(data.get("caps"), errors))
    given_caps = data.get("caps") if isinstance(data.get("caps"), dict) else {}
    if "extra_body" not in given_caps:
        apply_model_preset(card, caps, existing.model if existing else None, model)
    out["caps"] = caps
    out["min_interval"] = (_number(data["min_interval"], float, 0.05, 120, "min_interval", errors)
                           if "min_interval" in data else
                           (existing.min_interval if existing else card.get("min_interval")))
    out["max_concurrency"] = (_number(data["max_concurrency"], int, 1, 16, "max_concurrency", errors)
                              if "max_concurrency" in data else
                              (existing.max_concurrency if existing else card.get("max_concurrency")))
    out["enabled"] = bool(data.get("enabled", existing.enabled if existing else True))
    if errors:
        raise AIConfigError(errors)
    return out


# ── Writing ─────────────────────────────────────────────────────

def _changed(*status_keys: str) -> None:
    from app import ai_status
    from app.providers import reset_providers
    reset_providers()
    if status_keys:
        ai_status.forget(*status_keys)


def _audit(db, key: str, action: str) -> None:
    db.execute("INSERT INTO app_settings_audit (key, action, created_at) VALUES (?, ?, ?)", (key, action, _now()))


def _store_fingerprint(db) -> None:
    from app.app_settings import META_FINGERPRINT
    db.execute(
        "INSERT INTO app_settings (key, value, is_secret, updated_at) VALUES (?, ?, 0, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
        (META_FINGERPRINT, secret_box.fingerprint(create=True), _now()),
    )


def _insert(db, values: Dict[str, Any], origin: str = "") -> int:
    now = _now()
    key = values.get("key") or ""
    cur = db.execute(
        "INSERT INTO ai_connections (card, kind, label, base_url, model, key_enc, caps_json, min_interval, "
        "max_concurrency, origin, enabled, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (values["card"], values["kind"], values["label"], values["base_url"], values["model"],
         secret_box.encrypt(key) if key else "", json.dumps(values.get("caps", {}), ensure_ascii=False),
         values.get("min_interval"), values.get("max_concurrency"), origin, int(values.get("enabled", True)),
         now, now),
    )
    if key:
        _store_fingerprint(db)
    return int(cur.lastrowid)


def _write(db, connection_id: int, values: Dict[str, Any]) -> None:
    sets = ["card = ?", "kind = ?", "label = ?", "base_url = ?", "model = ?", "caps_json = ?",
            "min_interval = ?", "max_concurrency = ?", "enabled = ?", "updated_at = ?"]
    params: List[Any] = [values["card"], values["kind"], values["label"], values["base_url"], values["model"],
                         json.dumps(values["caps"], ensure_ascii=False), values["min_interval"],
                         values["max_concurrency"], int(values["enabled"]), _now()]
    if values.get("key") is not None:
        sets.append("key_enc = ?")
        params.append(secret_box.encrypt(values["key"]) if values["key"] else "")
        if values["key"]:
            _store_fingerprint(db)
    params.append(connection_id)
    db.execute(f"UPDATE ai_connections SET {', '.join(sets)} WHERE id = ?", params)


def create(data: Dict[str, Any], slot: Optional[str] = None) -> Connection:
    """Save a new connection; `slot` also appends it to that slot's list."""
    values = _validate(data, None)
    if slot is not None and slot not in SLOTS:
        raise AIConfigError({"slot": "沒有這個用途"})
    with _lock, closing(get_db_connection()) as db, db:
        connection_id = _insert(db, values)
        _audit(db, f"ai_connection:{connection_id}", "set")
        if slot:
            position = db.execute("SELECT COALESCE(MAX(position) + 1, 0) FROM ai_slots WHERE slot = ?",
                                  (slot,)).fetchone()[0]
            db.execute("INSERT INTO ai_slots (slot, position, connection_id, model) VALUES (?, ?, ?, '')",
                       (slot, position, connection_id))
    logger.info("AI connection %s added (%s)", connection_id, values["card"])
    _changed(f"c{connection_id}")
    push_brain_settings()
    return get_connection(connection_id)


def update(connection_id: int, data: Dict[str, Any]) -> Connection:
    existing = get_connection(connection_id)
    if existing is None:
        raise KeyError(connection_id)
    values = _validate(data, existing)
    with _lock, closing(get_db_connection()) as db, db:
        _write(db, connection_id, values)
        _audit(db, f"ai_connection:{connection_id}", "clear" if values.get("key") == "" and existing.key else "set")
    _changed(existing.status_key)
    push_brain_settings()
    return get_connection(connection_id)


def delete(connection_id: int) -> bool:
    with _lock, closing(get_db_connection()) as db, db:
        db.execute("DELETE FROM ai_slots WHERE connection_id = ?", (int(connection_id),))
        gone = db.execute("DELETE FROM ai_connections WHERE id = ?", (int(connection_id),)).rowcount
        if gone:
            _audit(db, f"ai_connection:{connection_id}", "delete")
        _renumber(db)
    from app import ai_status
    ai_status.register_secret(f"c{connection_id}", "")
    _changed(f"c{connection_id}")
    push_brain_settings()
    return bool(gone)


def _renumber(db) -> None:
    rows = db.execute("SELECT slot, position, connection_id, model FROM ai_slots ORDER BY slot, position").fetchall()
    db.execute("DELETE FROM ai_slots")
    counters: Dict[str, int] = {}
    for row in rows:
        position = counters.get(row["slot"], 0)
        counters[row["slot"]] = position + 1
        db.execute("INSERT INTO ai_slots (slot, position, connection_id, model) VALUES (?, ?, ?, ?)",
                   (row["slot"], position, row["connection_id"], row["model"]))


def set_slots(mapping: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    """Replace the lists of the slots named in `mapping` (others stay as they are)."""
    by_id = {c.id: c for c in list_connections()}
    errors: Dict[str, str] = {}
    clean: Dict[str, List[Tuple[int, str]]] = {}
    for slot, entries in (mapping or {}).items():
        if slot not in SLOTS:
            errors[slot] = "沒有這個用途"
            continue
        if not isinstance(entries, list):
            errors[slot] = "格式不對"
            continue
        seen = set()
        rows: List[Tuple[int, str]] = []
        for entry in entries:
            if isinstance(entry, int):
                entry = {"connection_id": entry}
            if not isinstance(entry, dict):
                errors[slot] = "格式不對"
                break
            try:
                connection_id = int(entry.get("connection_id"))
            except (TypeError, ValueError):
                errors[slot] = "格式不對"
                break
            conn = by_id.get(connection_id)
            if conn is None:
                errors[slot] = f"連線 {connection_id} 不存在"
                break
            if connection_id in seen:
                errors[slot] = f"「{conn.label}」重複了"
                break
            if slot == "video" and conn.kind != "gemini":
                errors[slot] = f"「{conn.label}」不能解析影片：影片解析只能用 Gemini"
                break
            if slot == "video" and conn.caps.get("video") is False:
                errors[slot] = f"「{conn.label}」不能解析 YouTube 影片：請用 AI Studio 的 Gemini 連線"
                break
            if slot == "embeddings" and conn.kind == "gemini":
                errors[slot] = f"「{conn.label}」目前不能算向量：請用 Ollama 或有向量的 OpenAI 相容服務"
                break
            model = _text(entry.get("model") or "", 200, slot, errors)
            seen.add(connection_id)
            rows.append((connection_id, model))
        clean[slot] = rows
    if errors:
        raise AIConfigError(errors)
    with _lock, closing(get_db_connection()) as db, db:
        for slot, rows in clean.items():
            db.execute("DELETE FROM ai_slots WHERE slot = ?", (slot,))
            for position, (connection_id, model) in enumerate(rows):
                db.execute("INSERT INTO ai_slots (slot, position, connection_id, model) VALUES (?, ?, ?, ?)",
                           (slot, position, connection_id, model))
            _audit(db, f"ai_slot:{slot}", "set")
    _changed()
    if "brain" in clean:
        push_brain_settings()
    return slots()


# ── Describing (keys never leave the server) ────────────────────

def key_hint(key: str) -> str:
    parts = [p for p in key.split(",") if p]
    tails = ["…" + p[-4:] for p in parts if len(p) >= 12]
    if len(parts) > 1:
        return f"{len(parts)} 把" + (f"（{'、'.join(tails)}）" if tails else "")
    return tails[0] if tails else ""


def describe_connection(conn: Connection) -> Dict[str, Any]:
    from app import ai_status, ai_usage
    used_in = [slot for slot, entries in slots().items() if any(e["connection_id"] == conn.id for e in entries)]
    return {
        "id": conn.id, "card": conn.card, "kind": conn.kind, "label": conn.label, "base_url": conn.base_url,
        "model": conn.model, "key_configured": bool(conn.key) or conn.key_broken, "key_hint": key_hint(conn.key),
        "key_undecryptable": conn.key_broken, "caps": conn.caps, "min_interval": conn.min_interval,
        "max_concurrency": conn.max_concurrency, "effective_interval": conn.interval(),
        "origin": conn.origin, "enabled": conn.enabled, "used_in": used_in,
        "status": ai_status.snapshot().get(conn.status_key), "updated_at": conn.updated_at,
        "usage": ai_usage.summary(conn.id, (provider_catalog.card(conn.card) or {}).get("quota")),
    }


def describe_slots() -> Dict[str, Any]:
    current = slots()
    return {
        "slots": [{"id": slot, "label": SLOT_LABELS[slot], "help": SLOT_HELP[slot], "entries": current[slot]}
                  for slot in SLOTS],
        "legacy_active": not current["analysis"] and not legacy_needs_setup(),
    }


# ── Migration from the flat settings ────────────────────────────

def _legacy_openai_values() -> Optional[Dict[str, Any]]:
    url = settings.OPENAI_BASE_URL.rstrip("/")
    if not settings.OPENAI_API_KEY and "api.openai.com" in url:
        return None  # nothing was ever configured
    card_id = provider_catalog.guess_card(url, "openai")
    if provider_catalog.CARD_BY_ID[card_id]["kind"] != "openai":
        card_id = "custom"  # e.g. Ollama's OpenAI-compatible /v1 address
    card = provider_catalog.CARD_BY_ID[card_id]
    return {"card": card_id, "kind": "openai", "label": f"{card['label']}（原設定）", "base_url": url,
            "model": settings.PRIMARY_MODEL, "key": settings.OPENAI_API_KEY, "caps": dict(card.get("caps", {})),
            "min_interval": float(settings.LLM_MIN_REQUEST_INTERVAL),
            "max_concurrency": int(settings.LLM_MAX_CONCURRENCY), "enabled": True}


def _legacy_can_embed(card_id: str) -> bool:
    """Whether the old OpenAI-compatible address may serve vectors. A card that says it has
    none (Agnes, Groq, Z.AI…) is left out of the embeddings slot; an unknown custom address
    keeps the old behaviour of trying /embeddings there."""
    card = provider_catalog.CARD_BY_ID.get(card_id) or {}
    return card_id == "custom" or bool(card.get("caps", {}).get("embeddings"))


def _legacy_gemini_values() -> Optional[Dict[str, Any]]:
    if not settings.gemini_keys:
        return None
    card = provider_catalog.CARD_BY_ID["gemini"]
    return {"card": "gemini", "kind": "gemini", "label": f"{card['label']}（原設定）", "base_url": "",
            "model": settings.GEMINI_MODEL, "key": ",".join(settings.gemini_keys),
            "caps": dict(card.get("caps", {})), "min_interval": None, "max_concurrency": None, "enabled": True}


def _ollama_values(base_url: str, model: str, label: str) -> Dict[str, Any]:
    card = provider_catalog.CARD_BY_ID["ollama"]
    return {"card": "ollama", "kind": "ollama", "label": label, "base_url": base_url.rstrip("/"),
            "model": model, "key": "", "caps": {**card["caps"], "embedding_model": settings.EMBEDDING_MODEL},
            "min_interval": None, "max_concurrency": None, "enabled": True}


def migrated() -> bool:
    try:
        with closing(get_db_connection()) as db:
            return db.execute("SELECT 1 FROM ai_meta WHERE key = ?", (META_MIGRATED,)).fetchone() is not None
    except Exception:
        return False


def migrate_legacy() -> bool:
    """Once per database: turn the flat AI settings into connections and slots.

    Only what is configured becomes a connection, so a fresh install starts with
    no preselected provider. Returns True when this call did the migration.
    """
    from app.vector import remote_embedding_model
    with _lock, closing(get_db_connection()) as db, db:
        if db.execute("SELECT 1 FROM ai_meta WHERE key = ?", (META_MIGRATED,)).fetchone():
            return False
        if db.execute("SELECT COUNT(*) FROM ai_connections").fetchone()[0]:
            ids = {}
        else:
            ids: Dict[str, int] = {}
            openai_values = _legacy_openai_values()
            if openai_values:
                ids["openai"] = _insert(db, openai_values, origin="legacy_openai")
            gemini_values = _legacy_gemini_values()
            if gemini_values:
                ids["gemini"] = _insert(db, gemini_values, origin="legacy_gemini")
            ollama_url = (settings.OLLAMA_BASE_URL or "").strip().rstrip("/")
            brain_local = settings.BRAIN_PROVIDER in ("ollama", "strata")
            brain_url = settings.BRAIN_BASE_URL.rstrip("/")
            if ollama_url:
                ids["ollama"] = _insert(db, _ollama_values(ollama_url, settings.BRAIN_MODEL, "本機 Ollama"),
                                        origin="legacy_ollama")
            if brain_local and brain_url and brain_url != ollama_url:
                ids["brain"] = _insert(db, _ollama_values(brain_url, settings.BRAIN_MODEL, "Ask Brain 本機模型（原設定）"),
                                       origin="legacy_brain")
            elif brain_local and brain_url:
                ids["brain"] = ids["ollama"]

            plan: Dict[str, List[Tuple[int, str]]] = {slot: [] for slot in SLOTS}
            if settings.PRIMARY_LLM_PROVIDER == "gemini" and "gemini" in ids:
                plan["analysis"].append((ids["gemini"], ""))
            elif "openai" in ids:
                plan["analysis"].append((ids["openai"], ""))
            if "gemini" in ids:
                plan["video"].append((ids["gemini"], ""))
            if "brain" in ids:
                plan["brain"].append((ids["brain"], settings.BRAIN_MODEL))
            if "ollama" in ids:
                plan["embeddings"].append((ids["ollama"], settings.EMBEDDING_MODEL))
            if "openai" in ids and settings.OPENAI_API_KEY and _legacy_can_embed(openai_values["card"]):
                plan["embeddings"].append((ids["openai"], remote_embedding_model()))
            for slot, rows in plan.items():
                for position, (connection_id, model) in enumerate(rows):
                    db.execute("INSERT INTO ai_slots (slot, position, connection_id, model) VALUES (?, ?, ?, ?)",
                               (slot, position, connection_id, model))
        db.execute("INSERT INTO ai_meta (key, value, updated_at) VALUES (?, ?, ?)", (META_MIGRATED, "1", _now()))
    if ids:
        logger.info("Moved the AI settings into %d connection(s): %s", len(set(ids.values())), ", ".join(sorted(ids)))
    _changed()
    return True


# ── Keeping the flat settings and the connections in step ──────

LEGACY_KEYS = frozenset({
    "PRIMARY_LLM_PROVIDER", "OPENAI_BASE_URL", "OPENAI_API_KEY", "PRIMARY_MODEL", "GEMINI_API_KEYS",
    "GEMINI_MODEL", "EMBEDDING_MODEL", "OLLAMA_BASE_URL", "LLM_MIN_REQUEST_INTERVAL", "LLM_MAX_CONCURRENCY",
    "BRAIN_PROVIDER", "BRAIN_BASE_URL", "BRAIN_MODEL",
})


def _by_origin(db, origin: str) -> Optional[int]:
    row = db.execute("SELECT id FROM ai_connections WHERE origin = ? ORDER BY id LIMIT 1", (origin,)).fetchone()
    return row["id"] if row else None


def _slot_ids(db, slot: str) -> List[Tuple[int, str]]:
    return [(r["connection_id"], r["model"]) for r in
            db.execute("SELECT connection_id, model FROM ai_slots WHERE slot = ? ORDER BY position", (slot,))]


def _put_slot(db, slot: str, rows: List[Tuple[int, str]]) -> None:
    db.execute("DELETE FROM ai_slots WHERE slot = ?", (slot,))
    for position, (connection_id, model) in enumerate(rows):
        db.execute("INSERT INTO ai_slots (slot, position, connection_id, model) VALUES (?, ?, ?, ?)",
                   (slot, position, connection_id, model))


def sync_from_settings(keys: Iterable[str]) -> None:
    """Flat AI settings saved through /api/settings update the connections migrated from them."""
    touched = set(keys) & LEGACY_KEYS
    if not touched or getattr(_sync_guard, "active", False) or not migrated():
        return
    from app.vector import remote_embedding_model
    with _lock, closing(get_db_connection()) as db, db:
        analysis = _slot_ids(db, "analysis")
        if touched & {"OPENAI_BASE_URL", "OPENAI_API_KEY", "PRIMARY_MODEL", "LLM_MIN_REQUEST_INTERVAL",
                      "LLM_MAX_CONCURRENCY", "PRIMARY_LLM_PROVIDER"}:
            values = _legacy_openai_values()
            connection_id = _by_origin(db, "legacy_openai")
            if values and connection_id:
                existing = db.execute("SELECT label FROM ai_connections WHERE id = ?", (connection_id,)).fetchone()
                _write(db, connection_id, {**values, "label": existing["label"]})
            elif values and analysis:
                connection_id = _insert(db, values, origin="legacy_openai")
                analysis.append((connection_id, ""))
        if touched & {"GEMINI_API_KEYS", "GEMINI_MODEL", "PRIMARY_LLM_PROVIDER"}:
            values = _legacy_gemini_values()
            connection_id = _by_origin(db, "legacy_gemini")
            if values and connection_id:
                existing = db.execute("SELECT label FROM ai_connections WHERE id = ?", (connection_id,)).fetchone()
                _write(db, connection_id, {**values, "label": existing["label"]})
            elif values and analysis:
                connection_id = _insert(db, values, origin="legacy_gemini")
                analysis.append((connection_id, ""))
                if not _slot_ids(db, "video"):
                    _put_slot(db, "video", [(connection_id, "")])
        if "PRIMARY_LLM_PROVIDER" in touched and analysis:
            wanted = _by_origin(db, "legacy_gemini" if settings.PRIMARY_LLM_PROVIDER == "gemini" else "legacy_openai")
            if wanted:
                analysis = [(wanted, "")] + [row for row in analysis if row[0] != wanted]
        if analysis != _slot_ids(db, "analysis"):
            _put_slot(db, "analysis", analysis)
        if "OLLAMA_BASE_URL" in touched:
            connection_id = _by_origin(db, "legacy_ollama")
            url = (settings.OLLAMA_BASE_URL or "").strip().rstrip("/")
            if connection_id and url:
                db.execute("UPDATE ai_connections SET base_url = ?, enabled = 1, updated_at = ? WHERE id = ?",
                           (url, _now(), connection_id))
            elif connection_id:
                db.execute("UPDATE ai_connections SET enabled = 0, updated_at = ? WHERE id = ?", (_now(), connection_id))
        if "EMBEDDING_MODEL" in touched:
            rows = []
            for connection_id, model in _slot_ids(db, "embeddings"):
                kind = db.execute("SELECT kind FROM ai_connections WHERE id = ?", (connection_id,)).fetchone()["kind"]
                rows.append((connection_id, settings.EMBEDDING_MODEL if kind == "ollama" else remote_embedding_model()))
            _put_slot(db, "embeddings", rows)
        if touched & {"BRAIN_PROVIDER", "BRAIN_BASE_URL", "BRAIN_MODEL"}:
            rows = _slot_ids(db, "brain")
            kinds = {r["id"]: r["kind"] for r in db.execute("SELECT id, kind FROM ai_connections")}
            cloud = [row for row in rows if kinds.get(row[0]) != "ollama"]
            if settings.BRAIN_PROVIDER in ("ollama", "strata"):
                url = settings.BRAIN_BASE_URL.rstrip("/")
                found = db.execute("SELECT id FROM ai_connections WHERE kind = 'ollama' AND base_url = ? "
                                   "ORDER BY id LIMIT 1", (url,)).fetchone()
                local_id = found["id"] if found else _insert(
                    db, _ollama_values(url, settings.BRAIN_MODEL, "Ask Brain 本機模型"), origin="legacy_brain")
                rows = [(local_id, settings.BRAIN_MODEL)] + cloud
            else:
                rows = cloud
            _put_slot(db, "brain", rows)
    _changed()


def push_brain_settings() -> None:
    """app/brain.py reads BRAIN_*; make them match the brain slot's local model."""
    if getattr(_sync_guard, "active", False) or not migrated():
        return
    entries = resolve("brain")
    values: Dict[str, Any] = {}
    if entries and entries[0][0].kind == "ollama":
        conn, model = entries[0]
        if settings.BRAIN_PROVIDER not in ("ollama", "strata"):
            values["BRAIN_PROVIDER"] = "ollama"
        if conn.base_url.rstrip("/") != settings.BRAIN_BASE_URL.rstrip("/"):
            values["BRAIN_BASE_URL"] = conn.base_url
        if model != settings.BRAIN_MODEL:
            values["BRAIN_MODEL"] = model
    elif settings.BRAIN_PROVIDER != "cloud":
        values["BRAIN_PROVIDER"] = "cloud"
    if not values:
        return
    from app import app_settings
    _sync_guard.active = True
    try:
        app_settings.save(values, action="sync", system=True)
    except app_settings.SettingsError as exc:
        logger.warning("Could not carry the brain slot into the Ask Brain settings: %s", exc)
    finally:
        _sync_guard.active = False


def rotate_keys(db, keyring) -> Tuple[List[str], List[str]]:
    """Re-encrypt every connection key (called inside app_settings.rotate_master_key's transaction)."""
    rotated, failed = [], []
    for row in db.execute("SELECT id, key_enc FROM ai_connections WHERE key_enc != ''").fetchall():
        name = f"ai_connection:{row['id']}"
        try:
            token = secret_box.reencrypt(row["key_enc"], keyring)
        except secret_box.SecretUnavailable:
            failed.append(name)
            continue
        db.execute("UPDATE ai_connections SET key_enc = ? WHERE id = ?", (token, row["id"]))
        rotated.append(name)
    return rotated, failed


def undecryptable() -> List[str]:
    return [f"ai_connection:{c.id}" for c in list_connections() if c.key_broken]
