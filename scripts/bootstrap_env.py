"""Create a new local .env with a strong API key; never overwrite existing settings."""

import argparse
import os
from pathlib import Path
import re
import secrets


def bootstrap_env(root: Path) -> Path:
    template = root / ".env.example"
    destination = root / ".env"
    source = template.read_text(encoding="utf-8")
    matches = list(re.finditer(r"^API_KEY=.*$", source, flags=re.MULTILINE))
    if len(matches) != 1:
        raise ValueError(".env.example must contain exactly one API_KEY assignment")
    source = source[:matches[0].start()] + f"API_KEY={secrets.token_urlsafe(48)}" + source[matches[0].end():]

    # O_EXCL refuses to replace an existing .env, including a symbolic link.
    descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as output:
        output.write(source)
    return destination


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-dir", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    try:
        bootstrap_env(args.project_dir)
    except (FileExistsError, OSError, ValueError):
        print("Setup stopped: .env already exists, or .env.example is unavailable/invalid.")
        return 1
    print("Created .env with a random API_KEY. Keep it private; open the app to sign in.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
