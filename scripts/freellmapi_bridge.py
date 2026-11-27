"""Zero-friction local bridge between OmniKeep and the FreeLLMAPI desktop app.

Automates what would otherwise require manual dashboard copy-paste:
1. Detects a running local FreeLLMAPI gateway on loopback (desktop default 31415,
   Docker/CLI default 3001, or an explicit --base-url). Optionally launches the
   installed Microsoft Store desktop app when --launch is given.
2. Uses FreeLLMAPI's official loopback desktop sign-in (`POST /api/auth/desktop-session`,
   available only on local desktop installs with `FREEAPI_DESKTOP=1`) to obtain a
   short-lived admin session without passwords or user copy-paste.
3. Optionally enables FreeLLMAPI's built-in keyless free providers
   (`POST /api/keys/keyless-available/enable`) so a brand-new user works with zero keys.
4. Optionally mirrors existing *free-tier* API keys already stored encrypted inside
   OmniKeep (`gemini`, `groq`, `openrouter`, `cloudflare`, `zai`, `agnes`, `nvidia`,
   `requesty`, `bazaarlink`, `cheapllm`, `sealion`, `itera`) straight into local
   FreeLLMAPI over loopback — never touching paid/subscription cards (`vertex`,
   `openai`, `deepseek`) and never printing any key or token to stdout/stderr.
5. Fetches FreeLLMAPI's unified API key (`GET /api/settings/api-key`) in memory and
   creates/updates OmniKeep's `freellmapi` connection (and optionally places it first
   in the requested task slot, e.g. `analysis`).

Security invariant: NO API key, unified key, or session token is ever printed or
returned in JSON output (only masked last-4 hints).
"""
from __future__ import annotations

import argparse
import json
import os
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


def _ensure_utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


def _mask_hint(secret: str) -> str:
    s = (secret or "").strip()
    if len(s) >= 4:
        return f"…{s[-4:]}"
    return "已設定" if s else ""


def _is_loopback_url(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.username or parsed.password:
        return False
    return parsed.scheme in ("http", "https") and (parsed.hostname or "").lower() in ("127.0.0.1", "localhost", "::1")


def _normalize_origin(base_url: str) -> str:
    raw = (base_url or "").strip().rstrip("/")
    if raw.endswith("/v1"):
        raw = raw[:-3].rstrip("/")
    return raw


def probe_gateway(
    base_url: str = "",
    ports: Sequence[int] = DEFAULT_PORTS,
    timeout: float = 2.0,
) -> Optional[Dict[str, Any]]:
    """Find a reachable local FreeLLMAPI origin and inspect its /api/auth/status."""
    candidates: List[str] = []
    if base_url:
        origin = _normalize_origin(base_url)
        if not _is_loopback_url(origin):
            raise ValueError("安全限制：自動接線只允許連接本機 loopback（127.0.0.1 / localhost）的 FreeLLMAPI。")
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
    token = (resp.json() or {}).get("token") or ""
    if not token:
        raise RuntimeError("FreeLLMAPI 未回傳桌面工作階段權杖。")
    return str(token)


def _mirror_existing_free_keys(
    client: httpx.Client,
    origin: str,
    headers: Dict[str, str],
    *,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Mirror OmniKeep's already-saved free-tier API keys into local FreeLLMAPI (in memory only)."""
    from app import ai_connections

    existing_resp = client.get(f"{origin}/api/keys/providers", headers=headers)
    already_configured = set()
    if existing_resp.status_code == 200:
        for prov in (existing_resp.json() or {}).get("providers") or []:
            if prov.get("configured") and prov.get("platform"):
                already_configured.add(str(prov["platform"]).lower())

    synced: List[str] = []
    skipped: List[str] = []
    failed: List[Dict[str, str]] = []

    for conn in ai_connections.list_connections():
        card_id = (conn.card or "").strip().lower()
        platform = FREE_CARD_TO_PLATFORM.get(card_id)
        if not platform:
            continue
        raw_key = (conn.key or "").strip()
        if not raw_key:
            continue
        # Gemini connections may store comma-separated keys; push each individually
        keys = [k.strip() for k in raw_key.split(",") if k.strip()] if card_id == "gemini" else [raw_key]
        if platform in already_configured:
            skipped.append(f"{card_id}->{platform}(已設定)")
            continue
        if dry_run:
            synced.append(f"{card_id}->{platform}(將匯入 {len(keys)} 把)")
            continue
        ok_count = 0
        for idx, secret_key in enumerate(keys, 1):
            label = f"OmniKeep-{conn.label}" + (f"-{idx}" if len(keys) > 1 else "")
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
            already_configured.add(platform)

    return {"synced": synced, "skipped": skipped, "failed": failed}


def _upsert_omnikeep_connection(
    v1_url: str,
    unified_key: str,
    *,
    model: str = "auto",
    slot: str = "analysis",
    prepend_slot: bool = True,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Create or update OmniKeep's `freellmapi` connection and optionally put it first in `slot`."""
    from app import ai_connections

    existing = next(
        (c for c in ai_connections.list_connections() if (c.card or "").lower() == "freellmapi"),
        None,
    )
    if dry_run:
        action = "update" if existing else "create"
        return {
            "action": action,
            "connection_id": existing.id if existing else None,
            "base_url": v1_url,
            "model": model,
            "key_hint": _mask_hint(unified_key),
            "slot": slot,
        }

    if existing:
        conn = ai_connections.update(
            existing.id,
            {"base_url": v1_url, "key": unified_key, "model": model},
        )
        action = "updated"
    else:
        conn = ai_connections.create(
            {
                "card": "freellmapi",
                "label": "FreeLLMAPI 本機閘道",
                "base_url": v1_url,
                "key": unified_key,
                "model": model,
            }
        )
        action = "created"

    slot_order: List[int] = []
    if slot:
        current_entries = ai_connections.slots().get(slot) or []
        preserved: List[Dict[str, Any]] = []
        for e in current_entries:
            cid = int(e["connection_id"])
            if cid == conn.id:
                continue
            item: Dict[str, Any] = {"connection_id": cid}
            if e.get("model"):
                item["model"] = e["model"]
            preserved.append(item)
        self_entry: Dict[str, Any] = {"connection_id": conn.id}
        new_entries = ([self_entry] + preserved) if prepend_slot else (preserved + [self_entry])
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
    model: str = "auto",
    slot: str = "analysis",
    prepend_slot: bool = True,
    dry_run: bool = False,
    wait_seconds: float = 20.0,
) -> Dict[str, Any]:
    """Run the complete zero-copy-paste FreeLLMAPI <-> OmniKeep wiring flow."""
    found = probe_gateway(base_url=base_url, ports=ports)
    launched = False
    if not found and launch and not base_url:
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

    with httpx.Client(timeout=15.0, follow_redirects=False, trust_env=False) as client:
        token = _acquire_desktop_session(client, origin)
        headers = {"Authorization": f"Bearer {token}"}

        keyless_enabled: Any = []
        if enable_keyless and not dry_run:
            resp_kl = client.post(f"{origin}/api/keys/keyless-available/enable", headers=headers)
            if resp_kl.status_code == 200:
                keyless_enabled = (resp_kl.json() or {}).get("enabled", [])

        mirror_summary = (
            _mirror_existing_free_keys(client, origin, headers, dry_run=dry_run)
            if sync_existing_keys
            else {"synced": [], "skipped": [], "failed": []}
        )

        resp_key = client.get(f"{origin}/api/settings/api-key", headers=headers)
        if resp_key.status_code != 200:
            return {"ok": False, "origin": origin, "error": f"無法讀取 FreeLLMAPI unified key（HTTP {resp_key.status_code}）。"}
        unified_key = str((resp_key.json() or {}).get("apiKey") or "").strip()
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
                models_probe_ok = True
                ready_models_count = len((resp_models.json() or {}).get("data") or [])
        except (httpx.HTTPError, ValueError):
            pass

    conn_result = _upsert_omnikeep_connection(
        v1_url,
        unified_key,
        model=model,
        slot=slot,
        prepend_slot=prepend_slot,
        dry_run=dry_run,
    )

    return {
        "ok": True,
        "dry_run": dry_run,
        "launched_app": launched,
        "origin": origin,
        "v1_url": v1_url,
        "keyless_enabled": keyless_enabled,
        "mirrored_free_keys": mirror_summary,
        "models_probe_ok": models_probe_ok,
        "ready_models_count": ready_models_count,
        "connection": conn_result,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="一鍵免手動貼上接線 FreeLLMAPI 與 OmniKeep（零金鑰印出）")
    parser.add_argument("--base-url", default="", help="指定本機 FreeLLMAPI 位址（預設自動探測 31415 與 3001）")
    parser.add_argument("--launch", action="store_true", help="偵測不到時嘗試喚起已安裝的 Windows FreeLLMAPI 桌面版")
    parser.add_argument("--no-keyless", action="store_true", help="不自動啟用 FreeLLMAPI 內建的免金鑰免費服務商")
    parser.add_argument(
        "--sync-existing-keys",
        action="store_true",
        help="將 OmniKeep 既有的免費層 API 金鑰本機加密同步進 FreeLLMAPI（不動付費／Vertex 卡、不印金鑰）",
    )
    parser.add_argument("--model", default="auto", help="預設路由模型（預設 auto）")
    parser.add_argument("--slot", default="analysis", help="自動掛入的 OmniKeep 用途槽位（留空則不改槽位）")
    parser.add_argument("--append", action="store_true", help="掛在槽位備援尾端而非第一順位")
    parser.add_argument("--dry-run", action="store_true", help="只預覽會做的事，不寫入 FreeLLMAPI 或 OmniKeep")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    _ensure_utf8_stdio()
    args = build_parser().parse_args(argv)
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
            prepend_slot=not args.append,
            dry_run=args.dry_run,
        )
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
