"""Encryption at rest for credentials entered in the app's settings.

The master key never lives in the database: backups (app/backup.py) ship
omnikeep.db to rclone remotes and git repositories. It comes from the
OMNIKEEP_SECRET_KEY environment variable, or from a key file created on first
use next to the database (OMNIKEEP_SECRET_KEY_FILE moves it). Backup archives
hold only omnikeep.db and snapshots, never this file.

The key file is a keyring: one key per line, the first one encrypts and every
line can decrypt (MultiFernet). Rotation (app_settings.rotate_master_key) puts
a new key in front, re-encrypts every stored value, then drops the old lines.
A running process notices the file changing and reloads it, so rotating needs
no restart.

Fernet = AES-128-CBC + HMAC-SHA256: a wrong key or a tampered value fails
loudly (InvalidToken) instead of decrypting to garbage.
"""
import base64
import hashlib
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

PREFIX = "fernet1:"
KEY_FILE_NAME = "omnikeep.secret.key"
ENV_KEY = "OMNIKEEP_SECRET_KEY"
ENV_KEY_FILE = "OMNIKEEP_SECRET_KEY_FILE"

_lock = threading.Lock()
# cache key -> (keyring, fingerprint of the encrypting key, file identity when it was read)
_cache: Dict[str, Tuple[MultiFernet, str, Optional[tuple]]] = {}


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


def _identity(path: Path) -> Optional[tuple]:
    """Changes whenever the file is rewritten or replaced (rotation uses os.replace)."""
    try:
        st = path.stat()
    except FileNotFoundError:
        return None
    return (st.st_ino, st.st_mtime_ns, st.st_size)


def _exclusive_write(path: Path, data: bytes) -> bool:
    """Create `path` readable by the owner only; False when it already exists."""
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    try:
        fd = os.open(path, flags, 0o600)
    except FileExistsError:
        return False
    with os.fdopen(fd, "wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    return True


def read_keyring(path: Path) -> List[bytes]:
    """The Fernet keys in a key file, encrypting key first."""
    lines = [line.strip() for line in path.read_bytes().splitlines()]
    return [_fernet_key(line) for line in lines if line]


def write_keyring(path: Path, keys: List[bytes]) -> None:
    """Atomically replace the key file, so a reader never sees half a keyring."""
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        tmp.unlink()
    except FileNotFoundError:
        pass
    _exclusive_write(tmp, b"\n".join(keys) + b"\n")
    os.replace(tmp, path)


def backup_keyring(path: Path) -> Path:
    """Copy the key file aside before it changes; never overwrites an earlier copy."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    data = path.read_bytes()
    for n in range(100):
        target = path.with_name(f"{path.name}.{stamp}{'-' + str(n) if n else ''}.bak")
        if _exclusive_write(target, data):
            return target
    raise FileExistsError("Could not choose a backup file name")


def _load(create: bool) -> Optional[Tuple[MultiFernet, str]]:
    env_value = os.environ.get(ENV_KEY, "").strip()
    with _lock:
        if env_value:
            cache_key = f"env:{hashlib.sha256(env_value.encode()).hexdigest()}"
            identity = None
        else:
            path = key_file_path()
            cache_key = str(path)
            identity = _identity(path)
        cached = _cache.get(cache_key)
        if cached and cached[2] == identity and (env_value or identity is not None):
            return cached[0], cached[1]
        if env_value:
            keys = [_fernet_key(env_value.encode())]
        else:
            if identity is None:
                if not create:
                    return None
                _exclusive_write(path, Fernet.generate_key())  # loses quietly to a concurrent creator
                identity = _identity(path)
            keys = read_keyring(path)
            if not keys:
                raise SecretUnavailable("Master key file is empty")
        loaded = (MultiFernet([Fernet(k) for k in keys]), _fingerprint(keys[0]), identity)
        _cache[cache_key] = loaded
        return loaded[0], loaded[1]


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


def reencrypt(token: str, keyring: MultiFernet) -> str:
    """Same plaintext, now under the keyring's first key."""
    if not token.startswith(PREFIX):
        raise SecretUnavailable("Unknown secret format")
    try:
        return PREFIX + keyring.rotate(token[len(PREFIX):].encode("ascii")).decode("ascii")
    except InvalidToken as exc:
        raise SecretUnavailable("Master key does not match") from exc


def keyring_of(keys: List[bytes]) -> MultiFernet:
    return MultiFernet([Fernet(k) for k in keys])


def new_key() -> bytes:
    return Fernet.generate_key()


def key_fingerprint(key: bytes) -> str:
    return _fingerprint(key)


def clear_cache() -> None:
    with _lock:
        _cache.clear()
