"""Zero-friction local bridge between OmniKeep and the FreeLLMAPI desktop app.

Automates what would otherwise require manual dashboard copy-paste:
1. Detects a running local FreeLLMAPI gateway on loopback (desktop default 31415,
   Docker/CLI default 3001, or an explicit --base-url). Optionally launches the
   installed Microsoft Store desktop app when --launch is given (skipped in --dry-run).
2. In non-dry-run mode, uses FreeLLMAPI's official loopback desktop sign-in
   (`POST /api/auth/desktop-session`, available only on local desktop installs with
   `FREEAPI_DESKTOP=1`) to obtain a short-lived admin session without passwords or
   user copy-paste, and logs out (`POST /api/auth/logout`) when done.
3. Optionally enables FreeLLMAPI's built-in keyless free providers
   (`POST /api/keys/keyless-available/enable`) so a brand-new user works with zero keys.
4. Optionally mirrors existing enabled *free-tier* API keys already stored encrypted inside
   OmniKeep (`gemini`, `groq`, `openrouter`, `cloudflare`, `zai`, `agnes`, `nvidia`,
   `requesty`, `bazaarlink`, `cheapllm`, `sealion`, `itera`) straight into local
   FreeLLMAPI over loopback — never touching paid/subscription cards (`vertex`,
   `openai`, `deepseek`), disabled connections, or custom-relay connections, and never
   printing any key or token to stdout/stderr.
5. Fetches FreeLLMAPI's unified API key (`GET /api/settings/api-key`) in memory and
   creates/updates the matching-origin OmniKeep `freellmapi` connection (preserving
   existing custom model, slot override, and slot order on re-runs unless overridden).

Security invariants:
- NO API key, unified key, or session token is ever printed or returned in JSON output
  (only masked hints via `ai_connections.key_hint` for keys >= 12 chars).
- `--dry-run` performs ZERO writes on both FreeLLMAPI (no desktop-session creation)
  and OmniKeep.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple
from urllib.parse import urlparse

import httpx

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

DEFAULT_PORTS: Tuple[int, ...] = (31415, 3001)
MSSTORE_APP_ID = "TashAhmed.FreeLLMAPI_6nczed04ys4da!FreeLLMAPI"
MSSTORE_WINGET_ID = "9PBN6G8K2B7F"

# Only free-tier API-key cards are eligible for optional local mirroring into FreeLLMAPI.
# Paid/subscription cards (vertex, openai, deepseek) and local gateways are deliberately excluded.
FREE_CARD_TO_PLATFORM: Dict[str, str] = {
    "gemini": "google",
    "groq": "groq",
    "openrouter": "openrouter",
    "cloudflare": "cloudflare",
    "zai": "zhipu",
    "agnes": "agnes",
    "nvidia": "nvidia",
    "requesty": "requesty",
    "bazaarlink": "bazaarlink",
    "cheapllm": "cheapllm",
    "sealion": "sealion",
    "itera": "iteracompute",
}

_CLOUDFLARE_ACCOUNT_RE = re.compile(r"^/client/v4/accounts/([^/]+)/ai(?:/v1)?/?$", re.IGNORECASE)


def _ensure_utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


def _mask_hint(secret: str) -> str:
    """Reuse OmniKeep's masking policy (only show last-4 for >= 12 chars; never reveal short keys)."""
    s = (secret or "").strip()
    if not s:
        return ""
    from app import ai_connections

    hint = ai_connections.key_hint(s)
    return hint if hint else "已設定"


def _parse_loopback_origin(base_url: str) -> Optional[str]:
    """Validate that `base_url` is a clean loopback HTTP(S) origin (optionally ending in /v1).

    Rejects userinfo, query strings, fragments, non-loopback hosts, and unexpected paths,
    returning canonical `scheme://host[:port]` (with brackets around IPv6) or None.
    """
    raw = (base_url or "").strip()
    if not raw or any(ch.isspace() for ch in raw) or "\\" in raw:
        return None
    try:
        parsed = urlparse(raw)
        port = parsed.port
    except ValueError:
        return None
    if parsed.scheme not in ("http", "https"):
        return None
    if parsed.username is not None or parsed.password is not None:
        return None
    if parsed.params or parsed.query or parsed.fragment:
        return None
    host = (parsed.hostname or "").lower()
    if host not in ("127.0.0.1", "localhost", "::1"):
        return None
    path = (parsed.path or "").rstrip("/")
    if path not in ("", "/v1"):
        return None
    host_fmt = f"[{host}]" if ":" in host else host
    port_part = f":{port}" if port is not None else ""
    return f"{parsed.scheme}://{host_fmt}{port_part}"


def _is_loopback_url(url: str) -> bool:
    return _parse_loopback_origin(url) is not None


def _normalize_origin(base_url: str) -> str:
    canonical = _parse_loopback_origin(base_url)
    if canonical is not None:
        return canonical
    raw = (base_url or "").strip().rstrip("/")
    if raw.endswith("/v1"):
        raw = raw[:-3].rstrip("/")
    return raw


def _canonical_origin_any(base_url: str) -> str:
    """Normalize any HTTP(S) base_url to `scheme://host[:port]` for matching existing connections."""
    raw = (base_url or "").strip()
    if not raw:
        return ""
    try:
        parsed = urlparse(raw)
        port = parsed.port
    except ValueError:
        return raw.rstrip("/").lower()
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return raw.rstrip("/").lower()
    host = parsed.hostname.lower()
    host_fmt = f"[{host}]" if ":" in host else host
    default_port = 80 if parsed.scheme == "http" else 443
    port_part = f":{port}" if (port is not None and port != default_port) else ""
    return f"{parsed.scheme}://{host_fmt}{port_part}"


def _parse_json_response(resp: httpx.Response, endpoint: str) -> Dict[str, Any]:
    try:
        data = resp.json()
    except ValueError as exc:
        raise RuntimeError(f"FreeLLMAPI {endpoint} 回傳非 JSON 內容（HTTP {resp.status_code}）。") from exc
    if not isinstance(data, dict):
        raise RuntimeError(f"FreeLLMAPI {endpoint} 回傳格式非 JSON 物件（HTTP {resp.status_code}）。")
    return data


def _validate_slot(slot: str) -> Optional[str]:
    """Return a Chinese error message if `slot` is invalid for a FreeLLMAPI connection, else None."""
    if not slot:
        return None
    from app import ai_connections

    if slot not in ai_connections.SLOTS:
        valid = "、".join(ai_connections.SLOTS)
        return f"無效的槽位「{slot}」；可用槽位為：{valid}（或留空不改槽位）。"
    if slot == "video":
        return "FreeLLMAPI 為 OpenAI 相容閘道，不能放入 video（影片解析只能用 Gemini 連線）。"
    return None


def _extract_cloudflare_account_id(base_url: str) -> Tuple[Optional[str], bool]:
    """Extract Cloudflare account_id from an official Workers AI base_url.

    Returns (account_id_or_none, is_official_cloudflare_host).
    """
    raw = (base_url or "").strip()
    if not raw:
        return None, False
    try:
        parsed = urlparse(raw)
    except ValueError:
        return None, False
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in ("http", "https") or host != "api.cloudflare.com":
        return None, False
    m = _CLOUDFLARE_ACCOUNT_RE.match(parsed.path or "")
    if not m:
        return None, True
    account_id = m.group(1).strip()
    if not account_id or "<" in account_id or ">" in account_id or ":" in account_id:
        return None, True
    return account_id, True


def _is_official_default_url(card_id: str, conn_base_url: str) -> bool:
    """Check whether a connection still points to its catalog card's official base_url."""
    from app import provider_catalog

    card = provider_catalog.card(card_id) or {}
    expected = (card.get("base_url") or "").strip().rstrip("/").lower()
    actual = (conn_base_url or "").strip().rstrip("/").lower()
    if not expected:
        # e.g. gemini has empty base_url
        return actual == ""
    return actual == expected


def probe_gateway(
    base_url: str = "",
    ports: Sequence[int] = DEFAULT_PORTS,
    timeout: float = 2.0,
) -> Optional[Dict[str, Any]]:
    """Find a reachable local FreeLLMAPI origin and inspect its /api/auth/status."""
    candidates: List[str] = []
    if base_url:
        origin = _parse_loopback_origin(base_url)
        if origin is None:
            raise ValueError(
                "安全限制：自動接線只允許連接乾淨的本機 loopback 位址（127.0.0.1 / localhost / [::1]，不含帳密、query 或 fragment）。"
            )
        candidates.append(origin)
    else:
        for port in ports:
            candidates.append(f"http://127.0.0.1:{port}")

    with httpx.Client(timeout=timeout, follow_redirects=False, trust_env=False) as client:
        for origin in candidates:
            try:
                resp = client.get(f"{origin}/api/auth/status")
                if resp.status_code == 200:
                    data = resp.json()
                    if isinstance(data, dict) and "desktop" in data:
                        return {"origin": origin, "v1_url": f"{origin}/v1", "auth_status": data}
            except (httpx.HTTPError, ValueError):
                continue
    return None


def launch_desktop_app(wait_seconds: float = 20.0, ports: Sequence[int] = DEFAULT_PORTS) -> Optional[Dict[str, Any]]:
    """Launch the installed Microsoft Store FreeLLMAPI app on Windows and wait until loopback answers."""
    if sys.platform != "win32":
        return None
    try:
        subprocess.Popen(
            ["explorer.exe", f"shell:AppsFolder\\{MSSTORE_APP_ID}"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except OSError:
        return None

    deadline = time.monotonic() + max(1.0, wait_seconds)
    while time.monotonic() < deadline:
        found = probe_gateway(ports=ports, timeout=1.5)
        if found:
            return found
        time.sleep(1.0)
    return None


def _acquire_desktop_session(client: httpx.Client, origin: str) -> str:
    resp = client.post(f"{origin}/api/auth/desktop-session")
    if resp.status_code != 200:
        raise RuntimeError(
            f"無法自動取得 FreeLLMAPI 桌面免密碼工作階段（HTTP {resp.status_code}）；"
            "若為 Docker／遠端安裝，請於 FreeLLMAPI 網頁登入後改用一般卡片設定。"
        )
    token = _parse_json_response(resp, "/api/auth/desktop-session").get("token") or ""
    if not token:
        raise RuntimeError("FreeLLMAPI 未回傳桌面工作階段權杖。")
    return str(token)


def _logout_desktop_session(client: httpx.Client, origin: str, headers: Dict[str, str]) -> None:
    try:
        client.post(f"{origin}/api/auth/logout", headers=headers)
    except httpx.HTTPError:
        pass


def _collect_mirror_candidates() -> Tuple[List[Dict[str, Any]], List[str], List[Dict[str, str]]]:
    """Collect eligible local free-tier connections to mirror without making any network calls."""
    from app import ai_connections

    candidates: List[Dict[str, Any]] = []
    skipped: List[str] = []
    failed: List[Dict[str, str]] = []

    for conn in ai_connections.list_connections():
        card_id = (conn.card or "").strip().lower()
        platform = FREE_CARD_TO_PLATFORM.get(card_id)
        if not platform:
            continue
        if not conn.enabled:
            skipped.append(f"{card_id}->{platform}(已停用)")
            continue
        raw_key = (conn.key or "").strip()
        if not raw_key:
            continue

        if card_id == "cloudflare":
            account_id, is_cf_host = _extract_cloudflare_account_id(conn.base_url)
            if not is_cf_host:
                skipped.append(f"{card_id}->{platform}(自訂 base_url)")
                continue
            if ":" in raw_key:
                left, _, right = raw_key.partition(":")
                if left.strip() and right.strip():
                    keys = [raw_key]
                else:
                    failed.append({"card": card_id, "platform": platform, "status": "invalid_cloudflare_key"})
                    continue
            elif account_id:
                keys = [f"{account_id}:{raw_key}"]
            else:
                failed.append({"card": card_id, "platform": platform, "status": "missing_cloudflare_account_id"})
                continue
        else:
            if not _is_official_default_url(card_id, conn.base_url):
                skipped.append(f"{card_id}->{platform}(自訂 base_url)")
                continue
            # Gemini connections may store comma-separated keys; push each individually
            keys = [k.strip() for k in raw_key.split(",") if k.strip()] if card_id == "gemini" else [raw_key]
            if not keys:
                continue

        candidates.append({
            "card": card_id,
            "platform": platform,
            "label": conn.label,
            "keys": keys,
        })

    return candidates, skipped, failed


def _preview_mirror_free_keys() -> Dict[str, Any]:
    """Zero-network dry-run preview of which local free-tier cards would be mirrored."""
    candidates, skipped, failed = _collect_mirror_candidates()
    planned = [f"{c['card']}->{c['platform']}(將匯入 {len(c['keys'])} 把)" for c in candidates]
    return {
        "synced": planned,
        "skipped": skipped,
        "failed": failed,
        "note": "dry-run 不建立 FreeLLMAPI 工作階段，未比對遠端已設定平台清單。",
    }


def _mirror_existing_free_keys(
    client: httpx.Client,
    origin: str,
    headers: Dict[str, str],
) -> Dict[str, Any]:
    """Mirror OmniKeep's already-saved enabled free-tier API keys into local FreeLLMAPI (in memory only)."""
    existing_resp = client.get(f"{origin}/api/keys/providers", headers=headers)
    if existing_resp.status_code != 200:
        return {
            "synced": [],
            "skipped": [],
            "failed": [{"card": "*", "platform": "*", "status": f"providers_http_{existing_resp.status_code}"}],
        }
    providers_doc = _parse_json_response(existing_resp, "/api/keys/providers")
    # Snapshot platforms already configured BEFORE this run so multiple local connections
    # on the same free card stay consistent with dry-run preview.
    initial_configured = {
        str(prov["platform"]).lower()
        for prov in (providers_doc.get("providers") or [])
        if isinstance(prov, dict) and prov.get("configured") and prov.get("platform")
    }

    candidates, skipped, failed = _collect_mirror_candidates()
    synced: List[str] = []

    for item in candidates:
        card_id = item["card"]
        platform = item["platform"]
        keys = item["keys"]
        if platform in initial_configured:
            skipped.append(f"{card_id}->{platform}(已設定)")
            continue
        ok_count = 0
        for idx, secret_key in enumerate(keys, 1):
            label = f"OmniKeep-{item['label']}" + (f"-{idx}" if len(keys) > 1 else "")
            try:
                resp = client.post(
                    f"{origin}/api/keys",
                    headers=headers,
                    json={"platform": platform, "key": secret_key, "label": label[:60]},
                )
                if resp.status_code in (200, 201):
                    ok_count += 1
                else:
                    failed.append({"card": card_id, "platform": platform, "status": str(resp.status_code)})
            except httpx.HTTPError as exc:
                failed.append({"card": card_id, "platform": platform, "status": type(exc).__name__})
        if ok_count:
            synced.append(f"{card_id}->{platform}({ok_count} 把)")

    return {"synced": synced, "skipped": skipped, "failed": failed}


def _find_matching_freellmapi_connection(v1_url: str):
    """Match an existing `freellmapi` connection only when it shares the same origin."""
    from app import ai_connections

    target_origin = _canonical_origin_any(v1_url)
    return next(
        (
            c
            for c in ai_connections.list_connections()
            if (c.card or "").lower() == "freellmapi"
            and _canonical_origin_any(c.base_url) == target_origin
        ),
        None,
    )


def _compute_slot_entries(
    current_entries: List[Dict[str, Any]],
    conn_id: Optional[int],
    slot_position: Optional[str],
) -> List[Dict[str, Any]]:
    """Compute updated slot entries preserving peer overrides, self override, and existing position."""
    entries: List[Dict[str, Any]] = []
    self_idx: Optional[int] = None
    self_entry: Optional[Dict[str, Any]] = None

    for idx, e in enumerate(current_entries):
        cid = int(e["connection_id"])
        item: Dict[str, Any] = {"connection_id": cid}
        if e.get("model"):
            item["model"] = e["model"]
        if conn_id is not None and cid == conn_id:
            self_idx = idx
            self_entry = item
        entries.append(item)

    if conn_id is None:
        # New connection preview placeholder (not yet persisted)
        return entries

    if self_idx is not None and self_entry is not None:
        if slot_position is None:
            return entries
        others = [item for i, item in enumerate(entries) if i != self_idx]
        if slot_position == "append":
            return others + [self_entry]
        return [self_entry] + others

    new_self: Dict[str, Any] = {"connection_id": conn_id}
    if slot_position == "append":
        return entries + [new_self]
    return [new_self] + entries


def _upsert_omnikeep_connection(
    v1_url: str,
    unified_key: str,
    *,
    model: Optional[str] = None,
    slot: str = "analysis",
    slot_position: Optional[str] = None,
    prepend_slot: Optional[bool] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Create or update the matching-origin OmniKeep `freellmapi` connection and slot entry."""
    from app import ai_connections

    if slot_position is None and prepend_slot is not None:
        slot_position = "prepend" if prepend_slot else "append"

    existing = _find_matching_freellmapi_connection(v1_url)
    effective_model = model if (model is not None and str(model).strip()) else (existing.model if existing else "auto")

    if dry_run:
        action = "update" if existing else "create"
        planned_slot_position = (
            "keep"
            if (
                existing
                and slot
                and slot_position is None
                and any(int(e["connection_id"]) == existing.id for e in (ai_connections.slots().get(slot) or []))
            )
            else (slot_position or "prepend")
        )
        return {
            "action": action,
            "connection_id": existing.id if existing else None,
            "base_url": v1_url,
            "model": effective_model,
            "key_hint": "(dry-run 未登入讀取)" if not unified_key else _mask_hint(unified_key),
            "slot": slot,
            "slot_position": planned_slot_position if slot else "",
        }

    if existing:
        patch: Dict[str, Any] = {"base_url": v1_url, "key": unified_key}
        if model is not None and str(model).strip():
            patch["model"] = str(model).strip()
        conn = ai_connections.update(existing.id, patch)
        action = "updated"
    else:
        conn = ai_connections.create(
            {
                "card": "freellmapi",
                "label": "FreeLLMAPI 本機閘道",
                "base_url": v1_url,
                "key": unified_key,
                "model": effective_model,
            }
        )
        action = "created"

    slot_order: List[int] = []
    if slot:
        current_entries = ai_connections.slots().get(slot) or []
        new_entries = _compute_slot_entries(current_entries, conn.id, slot_position)
        slot_order = [int(e["connection_id"]) for e in new_entries]
        ai_connections.set_slots({slot: new_entries})

    return {
        "action": action,
        "connection_id": conn.id,
        "base_url": conn.base_url,
        "model": conn.model,
        "key_hint": _mask_hint(unified_key),
        "slot": slot,
        "slot_order": slot_order,
    }


def auto_connect(
    *,
    base_url: str = "",
    ports: Sequence[int] = DEFAULT_PORTS,
    launch: bool = False,
    enable_keyless: bool = True,
    sync_existing_keys: bool = False,
    model: Optional[str] = None,
    slot: str = "analysis",
    slot_position: Optional[str] = None,
    prepend_slot: Optional[bool] = None,
    dry_run: bool = False,
    wait_seconds: float = 20.0,
) -> Dict[str, Any]:
    """Run the complete zero-copy-paste FreeLLMAPI <-> OmniKeep wiring flow."""
    # Validate inputs BEFORE any network or DB side effects so errors never leave half-applied state.
    if slot_position is None and prepend_slot is not None:
        slot_position = "prepend" if prepend_slot else "append"
    if slot_position not in (None, "prepend", "append"):
        return {"ok": False, "error": f"無效的槽位排序模式：{slot_position}"}

    slot_err = _validate_slot(slot)
    if slot_err:
        return {"ok": False, "error": slot_err}

    found = probe_gateway(base_url=base_url, ports=ports)
    launched = False
    if not found and launch and not base_url and not dry_run:
        found = launch_desktop_app(wait_seconds=wait_seconds, ports=ports)
        launched = bool(found)

    if not found:
        return {
            "ok": False,
            "error": (
                "偵測不到執行中的本機 FreeLLMAPI（已檢查埠號 "
                + ", ".join(str(p) for p in ports)
                + "）。請先啟動 FreeLLMAPI 桌面程式（或加上 --launch 自動喚起；尚未安裝可用 "
                f"winget install --id {MSSTORE_WINGET_ID} --source msstore）。"
            ),
        }

    origin = found["origin"]
    v1_url = found["v1_url"]
    auth_status = found["auth_status"]
    if not auth_status.get("desktop"):
        return {
            "ok": False,
            "origin": origin,
            "error": (
                "偵測到 FreeLLMAPI（非桌面免密碼模式，例如 Docker 或遠端安裝）。"
                "請先在瀏覽器登入 FreeLLMAPI 並從 Keys 頁取得 unified key 後，到 OmniKeep「設定 › AI」貼上。"
            ),
        }

    # Strict zero-write dry-run: do NOT call /api/auth/desktop-session (which creates user/session rows).
    if dry_run:
        mirror_preview = (
            _preview_mirror_free_keys()
            if sync_existing_keys
            else {"synced": [], "skipped": [], "failed": []}
        )
        conn_preview = _upsert_omnikeep_connection(
            v1_url,
            "",
            model=model,
            slot=slot,
            slot_position=slot_position,
            dry_run=True,
        )
        return {
            "ok": True,
            "dry_run": True,
            "launched_app": False,
            "origin": origin,
            "v1_url": v1_url,
            "would_enable_keyless": bool(enable_keyless),
            "keyless_enabled": [],
            "keyless_error": None,
            "mirrored_free_keys": mirror_preview,
            "models_probe_ok": None,
            "ready_models_count": None,
            "connection": conn_preview,
        }

    with httpx.Client(timeout=15.0, follow_redirects=False, trust_env=False) as client:
        token = _acquire_desktop_session(client, origin)
        headers = {"Authorization": f"Bearer {token}"}
        try:
            keyless_enabled: Any = []
            keyless_error: Optional[str] = None
            if enable_keyless:
                resp_kl = client.post(f"{origin}/api/keys/keyless-available/enable", headers=headers)
                if resp_kl.status_code == 200:
                    keyless_enabled = _parse_json_response(resp_kl, "/api/keys/keyless-available/enable").get("enabled", [])
                else:
                    keyless_error = f"HTTP {resp_kl.status_code}"

            mirror_summary = (
                _mirror_existing_free_keys(client, origin, headers)
                if sync_existing_keys
                else {"synced": [], "skipped": [], "failed": []}
            )

            resp_key = client.get(f"{origin}/api/settings/api-key", headers=headers)
            if resp_key.status_code != 200:
                return {"ok": False, "origin": origin, "error": f"無法讀取 FreeLLMAPI unified key（HTTP {resp_key.status_code}）。"}
            unified_key = str(_parse_json_response(resp_key, "/api/settings/api-key").get("apiKey") or "").strip()
            if not unified_key:
                return {"ok": False, "origin": origin, "error": "FreeLLMAPI 回傳空的 unified key。"}

            # Verify /v1/models responds with the unified key (without logging the key)
            models_probe_ok = False
            ready_models_count = 0
            try:
                resp_models = client.get(
                    f"{v1_url}/models?available=true",
                    headers={"Authorization": f"Bearer {unified_key}"},
                )
                if resp_models.status_code == 200:
                    models_doc = _parse_json_response(resp_models, "/v1/models")
                    models_probe_ok = True
                    ready_models_count = len(models_doc.get("data") or [])
            except (httpx.HTTPError, RuntimeError, ValueError):
                pass
        finally:
            _logout_desktop_session(client, origin, headers)

    conn_result = _upsert_omnikeep_connection(
        v1_url,
        unified_key,
        model=model,
        slot=slot,
        slot_position=slot_position,
        dry_run=False,
    )

    return {
        "ok": True,
        "dry_run": False,
        "launched_app": launched,
        "origin": origin,
        "v1_url": v1_url,
        "keyless_enabled": keyless_enabled,
        "keyless_error": keyless_error,
        "mirrored_free_keys": mirror_summary,
        "models_probe_ok": models_probe_ok,
        "ready_models_count": ready_models_count,
        "connection": conn_result,
    }


def add_bridge_arguments(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
    """Register CLI flags shared between freellmapi_bridge.py and setup_cli.py."""
    parser.add_argument("--base-url", default="", help="指定本機 FreeLLMAPI 位址（預設自動探測 31415 與 3001）")
    parser.add_argument("--launch", action="store_true", help="偵測不到時嘗試喚起已安裝的 Windows FreeLLMAPI 桌面版（--dry-run 時不喚起）")
    parser.add_argument("--no-keyless", action="store_true", help="不自動啟用 FreeLLMAPI 內建的免金鑰免費服務商")
    parser.add_argument(
        "--sync-existing-keys",
        action="store_true",
        help="將 OmniKeep 既有的啟用免費層 API 金鑰本機加密同步進 FreeLLMAPI（不動付費／Vertex 卡、不印金鑰）",
    )
    parser.add_argument("--model", default=None, help="指定路由模型（未指定時新建預設 auto，重跑保留原設定）")
    parser.add_argument("--slot", default="analysis", help="自動掛入的 OmniKeep 用途槽位（留空則不改槽位）")
    pos_group = parser.add_mutually_exclusive_group()
    pos_group.add_argument("--prepend", action="store_true", help="明確排到槽位第一順位（重跑未指定時保留原位置）")
    pos_group.add_argument("--append", action="store_true", help="掛在槽位備援尾端")
    parser.add_argument("--dry-run", action="store_true", help="嚴格零寫入預覽，不建立 FreeLLMAPI 工作階段也不寫入 OmniKeep")
    return parser


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="一鍵免手動貼上接線 FreeLLMAPI 與 OmniKeep（零金鑰印出）")
    return add_bridge_arguments(parser)


def main(argv: Optional[List[str]] = None) -> int:
    _ensure_utf8_stdio()
    args = build_parser().parse_args(argv)
    slot_position = "prepend" if args.prepend else ("append" if args.append else None)
    try:
        from app.app_settings import apply_overrides
        apply_overrides()
        result = auto_connect(
            base_url=args.base_url,
            launch=args.launch,
            enable_keyless=not args.no_keyless,
            sync_existing_keys=args.sync_existing_keys,
            model=args.model,
            slot=args.slot,
            slot_position=slot_position,
            dry_run=args.dry_run,
        )
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
