"""Rotate only API_KEY in .env without displaying credentials or importing the app."""
import argparse
import os
from pathlib import Path
import secrets

from dotenv import set_key


def rotate_api_key(path: Path) -> None:
    if "API_KEY" in os.environ:
        raise RuntimeError("API_KEY environment override must be removed before rotation")
    if not path.is_file() or path.is_symlink():
        raise ValueError("An existing regular .env file is required")
    # set_key parses assignments (including multiline values), replaces duplicate
    # API_KEY definitions and atomically replaces the file. Never log its result:
    # the return tuple contains the newly generated credential.
    set_key(path, "API_KEY", secrets.token_urlsafe(48), quote_mode="always")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path,
                        default=Path(__file__).resolve().parents[1] / ".env")
    args = parser.parse_args()
    try:
        rotate_api_key(args.env_file)
    except Exception:
        # Do not expose parser, filesystem or configuration exception payloads.
        print("API_KEY rotation failed. Check file access and API_KEY environment overrides.")
        return 1
    print("API_KEY rotated in .env. Restart the service and update client headers privately.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
