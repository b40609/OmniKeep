"""Encryption at rest for credentials entered in the app's settings.

The master key never lives in the database: backups (app/backup.py) ship
omnikeep.db to rclone remotes and git repositories. It comes from the
OMNIKEEP_SECRET_KEY environment variable, or from a key file created on first
use next to the database (OMNIKEEP_SECRET_KEY_FILE moves it). Backup archives
hold only omnikeep.db and snapshots, never this file.

Fernet = AES-128-CBC + HMAC-SHA256: a wrong key or a tampered value fails
loudly (InvalidToken) instead of decrypting to garbage.
"""
import base64
import hashlib
import os
import threading
from pathlib import Path
from typing import Dict, Optional, Tuple

from cryptography.fernet import Fernet, InvalidToken

PREFIX = "fernet1:"
KEY_FILE_NAME = "omnikeep.secret.key"
ENV_KEY = "OMNIKEEP_SECRET_KEY"
ENV_KEY_FILE = "OMNIKEEP_SECRET_KEY_FILE"

_lock = threading.Lock()
_cache: Dict[str, Tuple[Fernet, str]] = {}


class SecretUnavailable(Exception):
    """The value cannot be decrypted with the current master key."""


def key_file_path() -> Path:
    override = os.environ.get(ENV_KEY_FILE, "").strip()
    if override:
        return Path(override).expanduser().resolve()
    from app.config import settings
    return Path(settings.DATABASE_PATH).resolve().parent / KEY_FILE_NAME


def key_source() -> str:
    return "env" if os.environ.get(ENV_KEY, "").strip() else "file"


def _fernet_key(material: bytes) -> bytes:
    """Accept a ready Fernet key; derive one from any other passphrase."""
    try:
        Fernet(material)
        return material
    except (ValueError, TypeError):
        return base64.urlsafe_b64encode(hashlib.sha256(material).digest())


def _fingerprint(key: bytes) -> str:
    return hashlib.sha256(key).hexdigest()[:16]


def _write_new_key(path: Path) -> bytes:
    key = Fernet.generate_key()
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    try:
        fd = os.open(path, flags, 0o600)
    except FileExistsError:
        return path.read_bytes().strip()  # another process won the race
    with os.fdopen(fd, "wb") as handle:
        handle.write(key)
    return key


def _load(create: bool) -> Optional[Tuple[Fernet, str]]:
    env_value = os.environ.get(ENV_KEY, "").strip()
    cache_key = f"env:{hashlib.sha256(env_value.encode()).hexdigest()}" if env_value else str(key_file_path())
    with _lock:
        if cache_key in _cache:
            return _cache[cache_key]
        if env_value:
            key = _fernet_key(env_value.encode())
        else:
            path = key_file_path()
            if path.is_file():
                key = _fernet_key(path.read_bytes().strip())
            elif create:
                key = _write_new_key(path)
            else:
                return None
        loaded = (Fernet(key), _fingerprint(key))
        _cache[cache_key] = loaded
        return loaded


def fingerprint(create: bool = False) -> Optional[str]:
    loaded = _load(create)
    return loaded[1] if loaded else None


def encrypt(plaintext: str) -> str:
    fernet, _ = _load(create=True)
    return PREFIX + fernet.encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt(token: str) -> str:
    if not token.startswith(PREFIX):
        raise SecretUnavailable("Unknown secret format")
    loaded = _load(create=False)
    if loaded is None:
        raise SecretUnavailable("Master key is missing")
    try:
        return loaded[0].decrypt(token[len(PREFIX):].encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise SecretUnavailable("Master key does not match") from exc


def clear_cache() -> None:
    with _lock:
        _cache.clear()
