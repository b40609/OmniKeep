"""Add a Web Push (VAPID) key pair to .env without displaying or replacing keys."""
import argparse
import base64
import os
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from dotenv import dotenv_values, set_key

KEYS = ("VAPID_PUBLIC_KEY", "VAPID_PRIVATE_KEY")


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def generate_vapid_pair() -> tuple[str, str]:
    """Return (public, private) as base64url: uncompressed P-256 point and raw 32-byte scalar."""
    private = ec.generate_private_key(ec.SECP256R1())
    public = private.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    return _b64url(public), _b64url(private.private_numbers().private_value.to_bytes(32, "big"))


def add_vapid_keys(path: Path) -> None:
    if any(key in os.environ for key in KEYS):
        raise RuntimeError("VAPID environment overrides must be removed first")
    if not path.is_file() or path.is_symlink():
        raise ValueError("An existing regular .env file is required")
    existing = dotenv_values(path)
    present = [key for key in KEYS if existing.get(key)]
    if present:
        # Replacing a key pair silently breaks every existing browser subscription.
        raise FileExistsError("VAPID keys already exist; remove both lines to regenerate")
    public, private = generate_vapid_pair()
    # set_key atomically rewrites the file; never log its return value (it holds the key).
    set_key(path, "VAPID_PUBLIC_KEY", public, quote_mode="never")
    set_key(path, "VAPID_PRIVATE_KEY", private, quote_mode="always")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path,
                        default=Path(__file__).resolve().parents[1] / ".env")
    args = parser.parse_args()
    try:
        add_vapid_keys(args.env_file)
    except FileExistsError:
        print("VAPID keys already exist in .env; nothing changed.")
        return 1
    except Exception:
        # Do not expose parser, filesystem or configuration exception payloads.
        print("Adding VAPID keys failed. Check that .env exists and no VAPID environment overrides are set.")
        return 1
    print("Added VAPID_PUBLIC_KEY and VAPID_PRIVATE_KEY to .env. Restart the service to enable Web Push.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
