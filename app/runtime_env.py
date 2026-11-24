"""Keep long-running OmniKeep processes off ephemeral harness temp directories.

When an AI coding agent restarts OmniKeep from inside a short-lived runner shell
(e.g. T3 / Antigravity sets TEMP/TMP to ``.../.t3/userdata/antigravity-tmp/.../run-XXXX``),
the background server inherits that path. Once the runner cleans up its per-run
folder, every ``tempfile.mkdtemp`` call (Reels, Bilibili, screenshots, transcripts,
cookie exports) fails with ``[WinError 3]`` until the server is restarted.
"""
from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path

logger = logging.getLogger("omnikeep.runtime_env")

# Path segments belonging to ephemeral per-run agent sandboxes that disappear
# after the launching turn exits.
_EPHEMERAL_TEMP_MARKERS = ("antigravity-tmp",)


def _is_ephemeral_temp_path(path: str) -> bool:
    normalized = path.replace("\\", "/").lower()
    return any(marker in normalized for marker in _EPHEMERAL_TEMP_MARKERS)


def _is_usable_dir(path: str | None) -> bool:
    if not path:
        return False
    if _is_ephemeral_temp_path(path):
        return False
    return os.path.isdir(path) and os.access(path, os.W_OK)


def _windows_persistent_temp_candidates() -> list[str]:
    candidates: list[str] = []
    if os.name == "nt":
        try:
            import winreg  # type: ignore[import-not-found]

            for hive, subkey in (
                (winreg.HKEY_CURRENT_USER, r"Environment"),
                (
                    winreg.HKEY_LOCAL_MACHINE,
                    r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment",
                ),
            ):
                try:
                    with winreg.OpenKey(hive, subkey) as key:
                        for name in ("TEMP", "TMP"):
                            try:
                                raw, _ = winreg.QueryValueEx(key, name)
                            except OSError:
                                continue
                            if isinstance(raw, str) and raw.strip():
                                expanded = os.path.expandvars(raw.strip())
                                candidates.append(expanded)
                except OSError:
                    continue
        except ImportError:
            pass

    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        candidates.append(str(Path(local_app_data) / "Temp"))
    candidates.append(str(Path.home() / "AppData" / "Local" / "Temp"))
    system_root = os.environ.get("SystemRoot")
    if system_root:
        candidates.append(str(Path(system_root) / "Temp"))
    return candidates


def _resolve_persistent_temp_dir() -> str:
    candidates = (
        _windows_persistent_temp_candidates()
        if os.name == "nt"
        else ["/tmp", str(Path.home() / ".cache" / "omnikeep-tmp")]
    )
    for raw in candidates:
        if not raw or _is_ephemeral_temp_path(raw):
            continue
        try:
            os.makedirs(raw, exist_ok=True)
        except OSError:
            continue
        if os.path.isdir(raw) and os.access(raw, os.W_OK):
            return raw

    # Last-resort fallback inside the project/user home.
    fallback = str(Path.home() / ".omnikeep-tmp")
    os.makedirs(fallback, exist_ok=True)
    return fallback


def ensure_stable_tempdir() -> str:
    """Ensure TEMP/TMP/TMPDIR and ``tempfile`` point to a persistent writable folder.

    Leaves valid, non-ephemeral temp directories untouched (including pytest's
    temporary directories). Replaces missing paths or ephemeral harness temp
    folders (such as ``antigravity-tmp``) with the persistent OS/user temp dir
    and clears ``tempfile.tempdir`` so future ``mkdtemp`` calls pick it up.
    """
    current_values = {
        key: os.environ.get(key)
        for key in ("TEMP", "TMP", "TMPDIR")
        if os.environ.get(key)
    }
    cached = tempfile.tempdir

    needs_repair = False
    if cached and not _is_usable_dir(cached):
        needs_repair = True
    elif not current_values:
        # Let Python's standard resolution run if nothing is set, unless it fails.
        try:
            resolved = tempfile.gettempdir()
            if not _is_usable_dir(resolved):
                needs_repair = True
        except OSError:
            needs_repair = True
    else:
        for val in current_values.values():
            if not _is_usable_dir(val):
                needs_repair = True
                break

    if not needs_repair:
        return tempfile.gettempdir()

    target = _resolve_persistent_temp_dir()
    previous = current_values.get("TEMP") or current_values.get("TMP") or current_values.get("TMPDIR") or cached
    os.environ["TEMP"] = target
    os.environ["TMP"] = target
    if "TMPDIR" in os.environ:
        os.environ["TMPDIR"] = target
    tempfile.tempdir = None
    active = tempfile.gettempdir()
    logger.warning(
        "Replaced ephemeral or missing temp directory (%s) with persistent path: %s",
        previous,
        active,
    )
    return active
