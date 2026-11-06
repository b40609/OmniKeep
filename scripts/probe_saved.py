"""Probe the custom OpenAI-compatible connections saved in OmniKeep (設定 › AI 服務商).

Usage (from the OmniKeep folder): python scripts/probe_saved.py [label-prefix] [--models m1,m2]
       [--only <label substring>] [--just m1,m2 (replaces the model list)]
Probes every "自訂 OpenAI 相容端點" connection, plus any OpenAI-kind connection whose
label starts with label-prefix (default 免費測試). The key is decrypted in memory by
OmniKeep's own code and is never printed or written; any echo of it in an error body is
redacted before the result is saved. Same checks as scripts/free_llm_probe.py.
"""
import importlib.util
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)


def _sibling(name: str):
    """Load another script in this folder (scripts/ is not a package)."""
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(f"{name}.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


probe = _sibling("free_llm_probe")
_test_keys = _sibling("add_test_connections")
from app import ai_connections  # noqa: E402

PREFIX = _test_keys.PREFIX
EXTRA_MODELS = {PREFIX + label: extras for label, _card, _url, _model, extras in _test_keys.PROVIDERS.values()}


def redact(obj, secret):
    text = json.dumps(obj, ensure_ascii=False)
    if secret:
        text = text.replace(secret, "***")
        if len(secret) > 12:
            text = text.replace(secret[:12], "***")
    return json.loads(text)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    args = sys.argv[1:]
    prefix = args[0] if args and not args[0].startswith("--") else "免費測試"
    extra = args[args.index("--models") + 1].split(",") if "--models" in args else []
    only = args[args.index("--only") + 1] if "--only" in args else ""
    just = args[args.index("--just") + 1].split(",") if "--just" in args else []
    for conn in ai_connections.list_connections():
        if conn.kind != "openai" or not (conn.label.startswith(prefix) or conn.card == "custom"):
            continue
        if only and only not in conn.label:
            continue
        if conn.key_broken:
            print(f"{conn.label}: 金鑰無法解密，跳過")
            continue
        if conn.key:
            os.environ["FREE_PROBE_KEY"] = conn.key
        try:
            with probe.client() as c:
                models = just or [conn.model, *EXTRA_MODELS.get(conn.label, []), *extra]
                for model in dict.fromkeys(models):
                    rec = redact(probe.probe_model(c, conn.label, conn.base_url.rstrip("/"), model), conn.key)
                    probe.save(rec)
                    print(json.dumps(rec, ensure_ascii=False)[:400])
        finally:
            os.environ.pop("FREE_PROBE_KEY", None)
    print(f"結果：{probe.OUT}")


if __name__ == "__main__":
    main()
