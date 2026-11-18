"""Switch on the local OpenAI-compatible endpoint (app/llm_gateway.py) and connect a program to it.

    python scripts/llm_gateway_setup.py               create llm_gateway.json and the claude-mem token
    python scripts/llm_gateway_setup.py --claude-mem  also point claude-mem at the endpoint
                                                      (~/.claude-mem/settings.json, backed up first)

The token is written straight into claude-mem's settings and never printed. The Google keys stay
in omnikeep.db; nothing here reads or copies them. The watchdog starts run_gateway.py within a
minute once llm_gateway.json exists (or start it yourself: python run_gateway.py).
"""
import argparse
import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def claude_mem_settings() -> Path:
    base = os.environ.get("CLAUDE_MEM_DATA_DIR") or str(Path.home() / ".claude-mem")
    return Path(base) / "settings.json"


def connect_claude_mem(token: str, port: int, model: str, path: Path = None) -> Path:
    """Point claude-mem's openai-compatible provider at the gateway; returns the backup's path."""
    path = path or claude_mem_settings()
    data = json.loads(path.read_text(encoding="utf-8-sig")) if path.exists() else {}
    target = data["env"] if isinstance(data.get("env"), dict) else data
    backup = path.with_name(f"{path.name}.bak-{datetime.now():%Y%m%d-%H%M%S}")
    if path.exists():
        shutil.copy2(path, backup)
    target.update({
        "CLAUDE_MEM_PROVIDER": "openai-compatible",
        "CLAUDE_MEM_OPENAI_COMPAT_PRESET": "custom",
        "CLAUDE_MEM_OPENAI_COMPAT_BASE_URL": f"http://127.0.0.1:{port}/v1",
        "CLAUDE_MEM_OPENAI_COMPAT_MODEL": model,
        "CLAUDE_MEM_OPENAI_COMPAT_API_KEY": token,
    })
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return backup


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--claude-mem", action="store_true", help="point claude-mem at the endpoint")
    parser.add_argument("--source", default="claude-mem", help="name the calls are counted under")
    args = parser.parse_args()

    from app.llm_gateway import ensure_token, load_config, write_default_config
    config_file = write_default_config()
    config = load_config(config_file)
    token = ensure_token(args.source)
    print(f"Order file: {config_file}")
    print(f"Connections {config['connections']}, models {config['models']}, thinking {config['thinking_level']}")
    print(f"Token for '{args.source}' is stored encrypted in app_settings (ends in ...{token[-4:]})")
    if args.claude_mem:
        backup = connect_claude_mem(token, config["port"], config["models"][0])
        print(f"claude-mem now uses http://127.0.0.1:{config['port']}/v1 (backup: {backup})")


if __name__ == "__main__":
    main()
