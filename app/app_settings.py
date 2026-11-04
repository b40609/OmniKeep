"""Settings the owner edits in the app instead of .env.

Precedence for every key listed in SPECS:
    value saved in the app  >  .env / environment  >  built-in default

Values live in the `app_settings` table; credentials are encrypted with
app.secret_box and are never returned to the browser (only "configured" and
the last four characters). Saving applies the value to the running process at
once. Bootstrap settings stay in .env: HOST, PORT and the paths are needed
before the database opens, and API_KEY / LOCAL_AUTO_LOGIN guard the login that
protects this very settings page.
"""
import logging
import re
import threading
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Iterable, List, Optional, Set, Tuple
from urllib.parse import urlsplit

from app import secret_box
from app.config import Settings, settings
from app.database import get_db_connection

logger = logging.getLogger("omnikeep.app_settings")

META_FINGERPRINT = "_meta.secret_key_fingerprint"
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


class SettingsError(ValueError):
    def __init__(self, errors: Dict[str, str]):
        super().__init__("; ".join(f"{k}: {v}" for k, v in errors.items()))
        self.errors = errors


def _vapid_subject(value: str) -> Optional[str]:
    if value and not (value.startswith("mailto:") or value.startswith("https://")):
        return "請填 mailto: 開頭的信箱，或 https:// 開頭的網址"
    return None


@dataclass(frozen=True)
class Spec:
    key: str
    group: str
    label: str
    kind: str  # text | url | secret | int | float | bool | choice | ids
    attr: str = ""  # Settings attribute, when it differs from the key
    help: str = ""
    choices: Tuple[Tuple[str, str], ...] = ()
    minimum: Optional[float] = None
    maximum: Optional[float] = None
    multi: bool = False  # a secret holding several comma-separated keys
    numeric_ids: bool = False
    optional: bool = False  # a url that may be left empty (switches that service off)
    hook: str = ""  # llm | limiter | telegram: what must be rebuilt after a change
    check: Optional[Callable[[Any], Optional[str]]] = None

    @property
    def field(self) -> str:
        return self.attr or self.key

    @property
    def secret(self) -> bool:
        return self.kind == "secret"


GROUPS: Tuple[Tuple[str, str], ...] = (
    ("ai", "AI 服務商"),
    ("brain", "Ask Brain"),
    ("profile", "個人化"),
    ("telegram", "Telegram"),
    ("line", "LINE"),
    ("github", "GitHub"),
    ("backup", "備份"),
    ("push", "推播"),
)

SPECS: Tuple[Spec, ...] = (
    Spec("PRIMARY_LLM_PROVIDER", "ai", "主要服務商", "choice", hook="llm",
         choices=(("openai_compatible", "OpenAI 相容（OpenAI、DeepSeek、Groq、OpenRouter、Ollama…）"),
                  ("gemini", "Google Gemini"))),
    Spec("OPENAI_BASE_URL", "ai", "API 位址", "url", hook="llm",
         help="OpenAI 相容服務的 /v1 位址。更換位址時要一併重新輸入 API 金鑰。"),
    Spec("OPENAI_API_KEY", "ai", "API 金鑰", "secret", hook="llm",
         help="分析與語意搜尋都用這把金鑰。"),
    Spec("PRIMARY_MODEL", "ai", "分析模型", "text", hook="llm"),
    Spec("EMBEDDING_MODEL", "ai", "向量模型", "text",
         help="語意搜尋用，先交給本機 Ollama 計算；Ollama 連不上時改用上面的 OpenAI 相容服務"
              "（embeddinggemma-2 會改送 text-embedding-3-small）。更換後，既有向量要重建才查得到。"),
    Spec("OLLAMA_BASE_URL", "ai", "本機 Ollama 位址（向量）", "url", optional=True,
         help="例如 http://127.0.0.1:11434。留空表示不用 Ollama 算向量。"),
    Spec("GEMINI_API_KEYS", "ai", "Gemini API 金鑰", "secret", attr="GEMINI_API_KEYS_RAW",
         multi=True, hook="llm", help="多把金鑰用逗號分隔，會輪流使用。影片解析也會用到。"),
    Spec("GEMINI_MODEL", "ai", "Gemini 模型", "text", hook="llm"),
    Spec("LLM_MIN_REQUEST_INTERVAL", "ai", "請求最小間隔（秒）", "float", minimum=0.05, maximum=60,
         hook="limiter", help="兩次 AI 請求之間至少等待的秒數；遇到 429 會自動放慢。"),
    Spec("LLM_MAX_CONCURRENCY", "ai", "同時請求數", "int", minimum=1, maximum=16, hook="limiter"),

    Spec("BRAIN_PROVIDER", "brain", "回答來源", "choice",
         choices=(("ollama", "本機 Ollama，失敗時改用主要服務商"),
                  ("strata", "Strata（Ollama 相容），失敗時改用主要服務商"),
                  ("cloud", "直接用主要服務商"))),
    Spec("BRAIN_BASE_URL", "brain", "Ollama 位址", "url", help="例如 http://127.0.0.1:11434"),
    Spec("BRAIN_MODEL", "brain", "本機模型", "text", help="要先在 Ollama 下載，例如 ollama pull qwen3:8b"),
    Spec("BRAIN_MAX_CITATIONS", "brain", "引用筆數上限", "int", minimum=1, maximum=20),

    Spec("USER_BACKGROUND", "profile", "使用者背景", "text",
         help="給 AI 分析參考的身分、專長與手上的專案，例如「資料工程師，在做個人記帳 App」。"
              "工程與工具類內容會多一段結合背景的落地建議；留空就不加。"),
    Spec("LOCAL_HARDWARE", "profile", "本機硬體", "text",
         help="例如「Ryzen 7 / RTX 4070 12GB / 32GB RAM」。分析 AI 模型時會評估能否在這台機器上跑；"
              "留空則只列出不同顯存大小的需求。"),

    Spec("TELEGRAM_BOT_TOKEN", "telegram", "Bot Token", "secret", hook="telegram",
         help="向 @BotFather 建立 Bot 後取得。儲存後 Bot 立即重新連線。"),
    Spec("TELEGRAM_ALLOWED_USER_IDS", "telegram", "已綁定的帳號", "ids",
         attr="TELEGRAM_ALLOWED_USER_IDS_RAW", numeric_ids=True,
         help="用配對連結新增；移除後立即失去存取權。"),

    Spec("LINE_CHANNEL_SECRET", "line", "Channel Secret", "secret"),
    Spec("LINE_CHANNEL_ACCESS_TOKEN", "line", "Channel Access Token", "secret"),
    Spec("LINE_ALLOWED_USER_IDS", "line", "允許的 LINE User ID", "ids", attr="LINE_ALLOWED_USER_IDS_RAW",
         help="多個用逗號分隔。"),

    Spec("GITHUB_TOKEN", "github", "GitHub Token", "secret",
         help="雷達抓 GitHub 來源時使用，可提高 API 額度。不需要任何寫入權限。"),

    Spec("BACKUP_SINK", "backup", "備份方式", "choice",
         choices=(("local", "只存本機"), ("rclone", "本機＋rclone 雲端"), ("git", "本機＋git repo"), ("off", "關閉"))),
    Spec("BACKUP_HOUR", "backup", "每日備份時間（點）", "int", minimum=0, maximum=23),
    Spec("BACKUP_KEEP", "backup", "本機保留份數", "int", minimum=1, maximum=365),
    Spec("BACKUP_RCLONE_REMOTE", "backup", "rclone 遠端", "text", help="例如 gdrive:OmniKeep"),
    Spec("BACKUP_GIT_REPO_DIR", "backup", "git repo 資料夾", "text", help="私人 repo 的本機 clone 路徑"),

    Spec("VAPID_SUBJECT", "push", "推播聯絡資訊", "text", check=_vapid_subject,
         help="mailto: 信箱或 https 網址，推播服務商用來聯絡你。留空則用專案網址。"),
)

SPEC_BY_KEY: Dict[str, Spec] = {spec.key: spec for spec in SPECS}

_lock = threading.RLock()
_baseline: Dict[str, Any] = {}  # Settings field -> its .env/default value while overridden
_undecryptable: Set[str] = set()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Value conversion ────────────────────────────────────────────

def _text(spec: Spec, raw: Any, limit: int) -> str:
    if not isinstance(raw, str):
        raise ValueError("必須是文字")
    value = raw.strip()
    if _CONTROL.search(value):
        raise ValueError("不能包含換行或控制字元")
    if len(value) > limit:
        raise ValueError(f"太長（上限 {limit} 字元）")
    return value


def normalize(spec: Spec, raw: Any) -> Any:
    """Validate input from the browser; returns the typed value for Settings."""
    kind = spec.kind
    if kind == "secret":
        value = _text(spec, raw, 4000)
        if spec.multi:
            value = ",".join(part.strip() for part in value.split(",") if part.strip())
        elif any(ch.isspace() for ch in value):
            raise ValueError("金鑰中不能有空白")
    elif kind == "text":
        value = _text(spec, raw, 500)
    elif kind == "url":
        value = _text(spec, raw, 2000).rstrip("/")
        parsed = urlsplit(value)
        if not (spec.optional and value == "") and (parsed.scheme not in ("http", "https") or not parsed.hostname):
            raise ValueError("請填 http:// 或 https:// 開頭的完整網址")
    elif kind == "choice":
        value = raw if isinstance(raw, str) else ""
        if value not in {choice for choice, _ in spec.choices}:
            raise ValueError("不是可用的選項")
    elif kind == "bool":
        if isinstance(raw, bool):
            value = raw
        elif isinstance(raw, str) and raw.lower() in ("true", "false"):
            value = raw.lower() == "true"
        else:
            raise ValueError("必須是開或關")
    elif kind in ("int", "float"):
        if isinstance(raw, bool):
            raise ValueError("必須是數字")
        try:
            value = int(raw) if kind == "int" else float(raw)
        except (TypeError, ValueError):
            raise ValueError("必須是數字") from None
        if kind == "int" and isinstance(raw, float) and raw != int(raw):
            raise ValueError("必須是整數")
        if spec.minimum is not None and value < spec.minimum:
            raise ValueError(f"不能小於 {spec.minimum:g}")
        if spec.maximum is not None and value > spec.maximum:
            raise ValueError(f"不能大於 {spec.maximum:g}")
    elif kind == "ids":
        parts = raw if isinstance(raw, list) else str(raw or "").split(",")
        ids: List[str] = []
        for part in parts:
            token = str(part).strip()
            if not token:
                continue
            if spec.numeric_ids and not re.fullmatch(r"-?\d{1,20}", token):
                raise ValueError(f"「{token[:20]}」不是數字 ID")
            if not spec.numeric_ids and not re.fullmatch(r"[A-Za-z0-9_\-]{1,100}", token):
                raise ValueError(f"「{token[:20]}」不是有效的 ID")
            if token not in ids:
                ids.append(token)
        value = ",".join(ids)
    else:  # pragma: no cover - SPECS is static
        raise ValueError("未知的設定類型")
    if spec.check:
        problem = spec.check(value)
        if problem:
            raise ValueError(problem)
    return value


def _serialize(spec: Spec, value: Any) -> str:
    if spec.kind == "bool":
        return "true" if value else "false"
    return str(value)


def _deserialize(spec: Spec, stored: str) -> Any:
    if spec.kind == "bool":
        return stored == "true"
    if spec.kind == "int":
        return int(stored)
    if spec.kind == "float":
        return float(stored)
    return stored


# ── Storage ─────────────────────────────────────────────────────

def _read_rows(conn) -> Dict[str, Tuple[str, bool]]:
    try:
        rows = conn.execute("SELECT key, value, is_secret FROM app_settings").fetchall()
    except Exception:
        return {}
    return {row["key"]: (row["value"], bool(row["is_secret"])) for row in rows}


def _stored_values() -> Tuple[Dict[str, Any], Set[str], Optional[str]]:
    """App-saved values by key (decrypted), keys that cannot be decrypted, saved fingerprint."""
    with closing(get_db_connection()) as conn:
        rows = _read_rows(conn)
    values: Dict[str, Any] = {}
    broken: Set[str] = set()
    for key, (stored, is_secret) in rows.items():
        spec = SPEC_BY_KEY.get(key)
        if spec is None:
            continue
        try:
            plain = secret_box.decrypt(stored) if is_secret else stored
            values[key] = _deserialize(spec, plain)
        except (secret_box.SecretUnavailable, ValueError):
            broken.add(key)
    fingerprint = rows.get(META_FINGERPRINT, (None, False))[0]
    return values, broken, fingerprint


def baseline_value(spec: Spec) -> Any:
    """What .env (or the built-in default) says, regardless of the app's value."""
    with _lock:
        if spec.field in _baseline:
            return _baseline[spec.field]
    return getattr(settings, spec.field)


def default_value(spec: Spec) -> Any:
    return Settings.model_fields[spec.field].default


def _env_provides(spec: Spec) -> bool:
    value = baseline_value(spec)
    return value not in ("", None) and value != default_value(spec)


# ── Applying to the running process ─────────────────────────────

def _run_sync_hooks(keys: Iterable[str]) -> None:
    hooks = {SPEC_BY_KEY[key].hook for key in keys if key in SPEC_BY_KEY}
    if "llm" in hooks:
        from app.providers import reset_providers
        reset_providers()
    if "limiter" in hooks:
        from app.providers.rate_limiter import limiter
        limiter.reconfigure(settings.LLM_MIN_REQUEST_INTERVAL, settings.LLM_MAX_CONCURRENCY)


def apply_overrides() -> List[str]:
    """Make the running settings match the database; returns the keys whose value changed."""
    values, broken, _ = _stored_values()
    changed: List[str] = []
    with _lock:
        _undecryptable.clear()
        _undecryptable.update(broken)
        for spec in SPECS:
            current = getattr(settings, spec.field)
            if spec.key in values:
                _baseline.setdefault(spec.field, current)
                target = values[spec.key]
            elif spec.field in _baseline:
                target = _baseline.pop(spec.field)
            else:
                continue
            if current != target:
                setattr(settings, spec.field, target)
                changed.append(spec.key)
    if broken:
        logger.warning("Saved settings cannot be decrypted with the current master key: %s",
                       ", ".join(sorted(broken)))
    _run_sync_hooks(changed)
    return changed


def restore_baseline() -> None:
    """Put every overridden setting back to its .env/default value (used between tests)."""
    with _lock:
        restored = [spec.key for spec in SPECS if spec.field in _baseline]
        for field, value in _baseline.items():
            setattr(settings, field, value)
        _baseline.clear()
        _undecryptable.clear()
    _run_sync_hooks(restored)


def save(values: Optional[Dict[str, Any]] = None, reset: Iterable[str] = (), action: str = "set") -> List[str]:
    """Validate, store and apply. `reset` drops the app's value so .env/default applies again."""
    values = dict(values or {})
    reset = list(dict.fromkeys(reset))
    errors: Dict[str, str] = {}
    typed: Dict[str, Any] = {}
    for key, raw in values.items():
        spec = SPEC_BY_KEY.get(key)
        if spec is None:
            errors[key] = "這個設定不能在 App 內修改"
            continue
        try:
            typed[key] = normalize(spec, raw)
        except ValueError as exc:
            errors[key] = str(exc)
    for key in reset:
        if key not in SPEC_BY_KEY:
            errors[key] = "這個設定不能在 App 內修改"
        elif key in typed:
            errors[key] = "不能同時修改又改回 .env"
    if "OPENAI_BASE_URL" in typed or "OPENAI_BASE_URL" in reset:
        url_spec = SPEC_BY_KEY["OPENAI_BASE_URL"]
        new_url = str(typed.get("OPENAI_BASE_URL", baseline_value(url_spec))).rstrip("/")
        key_decided = "OPENAI_API_KEY" in typed  # a new key, or explicitly none
        if new_url != settings.OPENAI_BASE_URL.rstrip("/") and settings.OPENAI_API_KEY and not key_decided:
            # The saved key must not silently travel to a host it was never issued for.
            errors["OPENAI_API_KEY"] = "更換 API 位址時，請一併重新輸入 API 金鑰"
    if errors:
        raise SettingsError(errors)

    now = _now()
    with _lock, closing(get_db_connection()) as conn, conn:
        for key, value in typed.items():
            spec = SPEC_BY_KEY[key]
            stored = _serialize(spec, value)
            if spec.secret:
                stored = secret_box.encrypt(stored)
            conn.execute(
                "INSERT INTO app_settings (key, value, is_secret, updated_at) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value, is_secret = excluded.is_secret, "
                "updated_at = excluded.updated_at",
                (key, stored, int(spec.secret), now),
            )
            event = "clear" if spec.secret and value == "" else action
            conn.execute("INSERT INTO app_settings_audit (key, action, created_at) VALUES (?, ?, ?)",
                         (key, event, now))
        for key in reset:
            conn.execute("DELETE FROM app_settings WHERE key = ?", (key,))
            conn.execute("INSERT INTO app_settings_audit (key, action, created_at) VALUES (?, 'reset', ?)",
                         (key, now))
        if any(SPEC_BY_KEY[key].secret for key in typed):
            conn.execute(
                "INSERT INTO app_settings (key, value, is_secret, updated_at) VALUES (?, ?, 0, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
                (META_FINGERPRINT, secret_box.fingerprint(create=True), now),
            )
    if typed or reset:
        logger.info("Settings changed in the app (%s): %s", action, ", ".join([*typed, *reset]))
    changed = apply_overrides()
    touched = set(typed) | set(reset)
    from app import ai_status
    if any(SPEC_BY_KEY[k].hook == "llm" for k in touched):
        ai_status.forget("llm", "embeddings", "gemini")
    return sorted(set(changed) | touched)


def import_env() -> List[str]:
    """Copy every value .env currently provides into the app, so .env can be emptied."""
    with closing(get_db_connection()) as conn:
        saved = set(_read_rows(conn))
    values = {spec.key: baseline_value(spec) for spec in SPECS
              if spec.key not in saved and _env_provides(spec)}
    if values:
        save(values, action="import")
    return sorted(values)


# ── Description for the settings page ──────────────────────────

def _hint(spec: Spec, value: str) -> str:
    parts = [p for p in value.split(",") if p] if spec.multi else ([value] if value else [])
    tails = ["…" + p[-4:] for p in parts if len(p) >= 12]
    if spec.multi and parts:
        return f"{len(parts)} 把" + (f"（{'、'.join(tails)}）" if tails else "")
    return tails[0] if tails else ""


def describe() -> Dict[str, Any]:
    values, broken, saved_fingerprint = _stored_values()
    groups = []
    for group_id, group_label in GROUPS:
        fields = []
        for spec in (s for s in SPECS if s.group == group_id):
            source = "app" if spec.key in values else ("env" if _env_provides(spec) else "default")
            field: Dict[str, Any] = {
                "key": spec.key, "label": spec.label, "kind": spec.kind, "help": spec.help,
                "source": source, "env_available": _env_provides(spec),
            }
            if spec.choices:
                field["choices"] = [{"value": v, "label": label} for v, label in spec.choices]
            if spec.minimum is not None:
                field["min"] = spec.minimum
            if spec.maximum is not None:
                field["max"] = spec.maximum
            effective = getattr(settings, spec.field)
            if spec.secret:
                field["configured"] = bool(effective)
                field["hint"] = _hint(spec, effective or "")
                field["undecryptable"] = spec.key in broken
            else:
                field["value"] = [p for p in effective.split(",") if p] if spec.kind == "ids" else effective
                if field["env_available"]:
                    base = baseline_value(spec)
                    field["env_value"] = [p for p in base.split(",") if p] if spec.kind == "ids" else base
            fields.append(field)
        groups.append({"id": group_id, "label": group_label, "fields": fields})

    from app.security import configured_key
    current_fingerprint = secret_box.fingerprint(create=False)
    key_path = secret_box.key_file_path()
    return {
        "groups": groups,
        "secret_key": {
            "source": secret_box.key_source(),
            "path": str(key_path) if secret_box.key_source() == "file" else None,
            "exists": current_fingerprint is not None,
            "changed": bool(saved_fingerprint and current_fingerprint and saved_fingerprint != current_fingerprint),
            "undecryptable": sorted(broken),
        },
        "env_importable": [spec.key for spec in SPECS if spec.key not in values and _env_provides(spec)],
        "bootstrap": [
            {"key": "HOST", "value": settings.HOST},
            {"key": "PORT", "value": settings.PORT},
            {"key": "DATABASE_PATH", "value": settings.DATABASE_PATH},
            {"key": "API_KEY", "value": "已設定" if configured_key() else "未設定"},
            {"key": "LOCAL_AUTO_LOGIN", "value": settings.LOCAL_AUTO_LOGIN},
        ],
    }
