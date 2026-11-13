"""Probe free OpenAI-compatible LLM endpoints with OmniKeep's real analysis prompt.

Usage: python scripts/free_llm_probe.py <name> <base_url> <model> [<model> ...]
       python scripts/free_llm_probe.py <name> <base_url> --list
Key (optional) comes from env FREE_PROBE_KEY and is never printed. Without it no
Authorization header is sent (keyless endpoints such as Kilo and OVHcloud).
FREE_PROBE_GAP sets the seconds between the two requests per model (default 2).
FREE_PROBE_MAXTOK / FREE_PROBE_SMALL_MAXTOK set max_tokens (default 3000 / 200; 0 = no cap,
which is what OmniKeep's analysis calls do); FREE_PROBE_TIMEOUT is seconds per request. Reasoning
models spend these on hidden reasoning first. FREE_PROBE_EXTRA is JSON merged into the
request body, e.g. '{"reasoning": {"effort": "low"}}'.
Results go to FREE_PROBE_OUT (default %TEMP%/omnikeep_free_llm_probe/results.jsonl).
Survey and results: docs/free_llm_channels_2026-11.md.
"""
import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
PIPELINE = ROOT / "app" / "pipeline.py"
OUT = Path(os.environ.get("FREE_PROBE_OUT") or Path(tempfile.gettempdir()) / "omnikeep_free_llm_probe" / "results.jsonl")

SAMPLE = """Qwen3-Embedding-0.6B 是阿里通義千問團隊釋出的多語向量模型，參數量 0.6B，Apache-2.0 授權。
官方公布的 MMTEB 多語平均分數為 64.33，高於 Google embeddinggemma-2 的 61.36。模型支援 Matryoshka 表示，
向量可以從 1024 維截短到 256 維，檢索分數下降不到 1%。最大輸入長度 32K token，支援 100 多種語言與程式碼檢索。
社群實測在一般桌機 CPU 上每秒可以處理約 40 個 512 token 的段落；用 llama.cpp 的 GGUF Q8 版本只需約 700 MB 記憶體。
同系列另有 4B 與 8B 版本，8B 在 MTEB 多語榜排名第一。適合個人知識庫、RAG 與本機搜尋。"""

JSON_SYSTEM = "你是連線測試助手。只輸出一個 JSON 物件，不要有其他文字。"
JSON_PROMPT = '請用繁體中文回覆這個 JSON 物件，值照抄：{"回覆": "連線成功", "數字": 42}'
REQUIRED = ["category", "title_l1", "summary_l1", "tech_tags", "deep_analysis", "is_composite", "sub_entities"]
RL_HEADERS = re.compile(r"ratelimit|retry-after|x-quota|x-remaining", re.I)


def analysis_prompt() -> str:
    """The analysis system prompt with neutral placeholders (no owner background or hardware)."""
    src = PIPELINE.read_text(encoding="utf-8")
    tpl = re.search(r'_ANALYSIS_PROMPT_TEMPLATE = r?"""(.*?)"""', src, re.S).group(1)
    parts = {
        "BACKGROUND_ANCHOR": "",
        "BACKGROUND_ADVICE": "給出 1-2 點具體技術借鏡或落地改進建議。",
        "HARDWARE_LABEL": "硬體需求",
        "HARDWARE_VERDICT": "分別標註 8 GB、16 GB、24 GB 顯存的運行結論。",
    }
    return re.sub(r"<<([A-Z_]+)>>", lambda m: parts[m.group(1)], tpl)


def parse_json(text: str):
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.M).strip()
    try:
        return json.loads(text)
    except ValueError:
        s, e = text.find("{"), text.rfind("}")
        if s >= 0 and e > s:
            try:
                return json.loads(text[s:e + 1])
            except ValueError:
                return None
    return None


def client() -> httpx.Client:
    headers = {"User-Agent": "Mozilla/5.0 (OmniKeep free-tier probe)", "Content-Type": "application/json"}
    key = os.environ.get("FREE_PROBE_KEY")
    if key:
        headers["Authorization"] = f"Bearer {key}"
    return httpx.Client(headers=headers, timeout=float(os.environ.get("FREE_PROBE_TIMEOUT", "180")), trust_env=False, follow_redirects=True)


def chat(c, base, model, system, user, max_tokens, json_mode):
    body = {"model": model, "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": 0.2}
    if max_tokens > 0:  # 0 = no cap, like OmniKeep's own analysis calls
        body["max_tokens"] = max_tokens
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    body.update(json.loads(os.environ.get("FREE_PROBE_EXTRA") or "{}"))
    t = time.monotonic()
    r = c.post(f"{base}/chat/completions", json=body)
    dt = time.monotonic() - t
    rl = {k: v for k, v in r.headers.items() if RL_HEADERS.search(k)}
    return r, dt, rl


def run_case(c, base, model, system, user, max_tokens):
    """Try json_object first; on 400/422 retry once without it."""
    json_mode = True
    try:
        r, dt, rl = chat(c, base, model, system, user, max_tokens, True)
        if r.status_code in (400, 422):
            r, dt, rl = chat(c, base, model, system, user, max_tokens, False)
            json_mode = False
    except httpx.HTTPError as exc:
        return {"status": type(exc).__name__, "seconds": None, "json_mode": json_mode, "error": str(exc)[:200]}, None
    out = {"status": r.status_code, "seconds": round(dt, 1), "json_mode": json_mode, "ratelimit": rl}
    if r.status_code != 200:
        out["error"] = r.text[:300]
        return out, None
    try:
        data = r.json()
        msg = data["choices"][0]["message"]
        text = msg.get("content") or ""
        out["usage"] = data.get("usage")
        out["served_model"] = data.get("model")
        out["finish_reason"] = data["choices"][0].get("finish_reason")
    except Exception as exc:  # noqa: BLE001
        out["error"] = f"bad body: {exc}: {r.text[:200]}"
        return out, None
    return out, text


def probe_model(c, name, base, model):
    rec = {"provider": name, "base": base, "model": model, "date": time.strftime("%Y-%m-%d %H:%M")}
    small, text = run_case(c, base, model, JSON_SYSTEM, JSON_PROMPT, int(os.environ.get("FREE_PROBE_SMALL_MAXTOK", "200")))
    small["parsed"] = parse_json(text) is not None if text is not None else False
    rec["small_json"] = small
    if small["status"] != 200:
        return rec
    time.sleep(float(os.environ.get("FREE_PROBE_GAP", "2")))
    full, text = run_case(c, base, model, analysis_prompt(), f"請分析以下內容：\n\n{SAMPLE}",
                          int(os.environ.get("FREE_PROBE_MAXTOK", "3000")))
    if text is not None:
        obj = parse_json(text)
        full["parsed"] = isinstance(obj, dict)
        if isinstance(obj, dict):
            full["missing_keys"] = [k for k in REQUIRED if k not in obj]
            full["title_l1"] = str(obj.get("title_l1", ""))[:60]
            full["summary_len"] = len(str(obj.get("summary_l1", "")))
            full["deep_len"] = len(str(obj.get("deep_analysis", "")))
            full["has_latex"] = "$" in json.dumps(obj, ensure_ascii=False)
        else:
            full["raw_head"] = text[:200]
        toks = (full.get("usage") or {}).get("completion_tokens")
        if toks and full["seconds"]:
            full["tok_per_s"] = round(toks / full["seconds"], 1)
    rec["analysis"] = full
    return rec


def save(rec) -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def main():
    name, base = sys.argv[1], sys.argv[2].rstrip("/")
    models = sys.argv[3:]
    with client() as c:
        if models == ["--list"]:
            r = c.get(f"{base}/models")
            print(r.status_code)
            try:
                for m in r.json().get("data", []):
                    print(m.get("id"))
            except Exception:  # noqa: BLE001
                print(r.text[:500])
            return
        for model in models:
            rec = probe_model(c, name, base, model)
            save(rec)
            print(json.dumps(rec, ensure_ascii=False))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
