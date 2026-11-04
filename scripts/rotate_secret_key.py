"""Re-encrypt every credential saved in the app under a new master key.

The old key file is copied to omnikeep.secret.key.<UTC time>.bak first; keep
that copy as long as you keep database backups made before today, because
they can only be read with the old key. The running server picks up the new
key by itself, so there is no need to stop it. Key material is never printed.

    python scripts/rotate_secret_key.py
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.app_settings import RotationError, rotate_master_key  # noqa: E402


def main() -> int:
    argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter).parse_args()
    try:
        result = rotate_master_key()
    except RotationError as exc:
        print(f"Nothing rotated: {exc}.")
        return 1
    except Exception as exc:
        # Never echo exception payloads: they may quote file contents.
        print(f"Rotation failed ({type(exc).__name__}). The key file still reads every saved value; "
              "run the command again.")
        return 1
    print(f"Re-encrypted {len(result['rotated'])} saved credentials with a new master key.")
    print(f"Key file:   {result['key_file']}")
    print(f"Old key:    {result['backup']}  (needed to restore database backups made before now)")
    if result["failed"]:
        print("Could not read (already unreadable before rotating; enter them again in the app): "
              + ", ".join(result["failed"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
