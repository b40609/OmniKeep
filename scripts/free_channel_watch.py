"""Weekly check of the two maintained free-LLM sources against last week's snapshot.

Usage: python scripts/free_channel_watch.py
Sources (agreed 2026-11-06, see docs/free_llm_channels_2026-11.md section 1):
  - FreeLLMAPI (tashfeenahmed/freellmapi): the supported-platforms table and the
    platforms registered in server/src/providers/index.ts
  - mvalentsev/awesome-free-ai-coding: the README entries (probe-verified twice a week)
Prints a Markdown report of what was added, removed or changed since the last run,
plus every change touching a provider OmniKeep has a card for, and writes the report
and the new snapshot under %LOCALAPPDATA%/OmniKeep/free_channel_watch/. Read-only
towards OmniKeep: it never edits the catalog. The first run only records a baseline.
"""
import json
import os
import re
import sys
import time
from datetime import date
from pathlib import Path
from typing import Dict, List

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import provider_catalog  # noqa: E402

RAW = "https://raw.githubusercontent.com"
SOURCES = {
    "freellmapi_table": f"{RAW}/tashfeenahmed/freellmapi/main/docs/en/providers/01-supported-platforms.md",
    "freellmapi_index": f"{RAW}/tashfeenahmed/freellmapi/main/server/src/providers/index.ts",
    "mvalentsev": f"{RAW}/mvalentsev/awesome-free-ai-coding/main/README.md",
}
OUT_DIR = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "OmniKeep" / "free_channel_watch"


def fetch(url: str) -> str:
    with httpx.Client(timeout=30, trust_env=False, follow_redirects=True,
                      headers={"User-Agent": "OmniKeep free-channel watch"}) as client:
        response = client.get(url)
        response.raise_for_status()
        return response.text


def _clean(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    return re.sub(r"\s+", " ", text).strip()


def parse_table(md: str) -> Dict[str, str]:
    """FreeLLMAPI catalog table: `id` -> 'auth | notes'."""
    out = {}
    for line in md.splitlines():
        m = re.match(r"^\|\s*`([a-z0-9_-]+)`\s*\|([^|]*)\|([^|]*)\|([^|]*)\|(.*)\|\s*$", line)
        if m:
            out[m.group(1)] = _clean(f"{m.group(2)} | {m.group(3)} | {m.group(5)}")
    return out


def parse_index(ts: str) -> Dict[str, str]:
    """Registered platforms: id -> base URL (empty when the adapter builds its own)."""
    out = {}
    for block in re.split(r"register\(", ts)[1:]:
        pid = re.search(r"platform:\s*'([a-z0-9_-]+)'", block)
        if pid:
            base = re.search(r"baseUrl:\s*'([^']+)'", block)
            out[pid.group(1)] = base.group(1) if base else ""
    return out


def parse_mvalentsev(md: str) -> Dict[str, str]:
    """README entries '- **[Name](url)** — description' -> description."""
    out = {}
    for m in re.finditer(r"^- \*\*\[([^\]]+)\]\(([^)]*)\)\*\*(.*)$", md, re.M):
        out[m.group(1).strip()] = _clean(m.group(3))[:400]
    return out


def diff(old: Dict[str, str], new: Dict[str, str]):
    added = sorted(set(new) - set(old))
    removed = sorted(set(old) - set(new))
    changed = sorted(k for k in set(old) & set(new) if old[k] != new[k])
    return added, removed, changed


def card_hosts() -> Dict[str, str]:
    """OmniKeep card id -> host of its base URL, to spot changes to providers we ship."""
    out = {}
    for card in provider_catalog.CARDS:
        m = re.match(r"https?://([^/]+)", card.get("base_url") or "")
        if m:
            out[card["id"]] = m.group(1).lower()
    return out


def offer_lines(today: str, within_days: int = 14) -> List[str]:
    """Cards whose limited-time free offer (`ends`) is over or ends within `within_days`."""
    out = []
    for card in provider_catalog.CARDS:
        ends = card.get("ends")
        if not ends:
            continue
        left = (date.fromisoformat(ends) - date.fromisoformat(today)).days
        if left < 0:
            out.append(f"- **{card['label']}**：免費活動已在 {ends} 結束。查官網後更新或移除卡片 `{card['id']}`。")
        elif left <= within_days:
            out.append(f"- **{card['label']}**：免費活動 {ends} 結束（還有 {left} 天），到期前查官網。")
    return out


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    snap_path = OUT_DIR / "snapshot.json"
    try:
        new = {
            "freellmapi_table": parse_table(fetch(SOURCES["freellmapi_table"])),
            "freellmapi_index": parse_index(fetch(SOURCES["freellmapi_index"])),
            "mvalentsev": parse_mvalentsev(fetch(SOURCES["mvalentsev"])),
        }
    except httpx.HTTPError as exc:
        print(f"抓取失敗：{type(exc).__name__}: {exc}")
        return 1
    empty = [name for name, rows in new.items() if not rows]
    if empty:
        print(f"解析結果是空的，來源格式可能改了：{', '.join(empty)}")
        return 1
    old = json.loads(snap_path.read_text(encoding="utf-8")) if snap_path.exists() else None
    today = time.strftime("%Y-%m-%d")
    lines = [f"# 免費 LLM 管道週報（{today}）", ""]
    if old is None:
        lines.append("第一次執行：只建立基準，下週起才會列出變動。")
        lines.append(f"- FreeLLMAPI 目錄 {len(new['freellmapi_table'])} 家、已註冊 adapter {len(new['freellmapi_index'])} 家；"
                     f"mvalentsev 清單 {len(new['mvalentsev'])} 項。")
    else:
        lines.append(f"比較基準：{old.get('date', '?')}")
        hosts = card_hosts()
        ours = []
        titles = {"freellmapi_table": "FreeLLMAPI 目錄", "freellmapi_index": "FreeLLMAPI 已註冊 adapter",
                  "mvalentsev": "mvalentsev 清單"}
        for key, title in titles.items():
            added, removed, changed = diff(old["data"].get(key, {}), new[key])
            lines += ["", f"## {title}", f"新增 {len(added)}、移除 {len(removed)}、內容有變 {len(changed)}"]
            for label, names, src in (("新增", added, new[key]), ("移除", removed, old["data"].get(key, {})),
                                      ("有變", changed, new[key])):
                for name in names[:40]:
                    lines.append(f"- {label}：**{name}** — {src.get(name, '')[:240]}")
                    text = f"{name} {src.get(name, '')}".lower()
                    for card_id, host in hosts.items():
                        if card_id == name.lower() or host in text:
                            ours.append(f"- {title} {label}：**{name}**（OmniKeep 卡片 `{card_id}`）")
        lines += ["", "## 跟 OmniKeep 現有卡片有關的變動"]
        lines += sorted(set(ours)) or ["- 沒有"]
        lines += ["", "有變動時：照 docs/free_llm_channels_2026-11.md 的方法查官方頁、需要的話用 scripts/probe_saved.py 實測，"
                  "再更新 app/provider_catalog.py。"]
    offers = offer_lines(today)
    if offers:
        lines += ["", "## 限時活動", *offers]
    report = "\n".join(lines)
    print(report)
    (OUT_DIR / f"report-{today}.md").write_text(report + "\n", encoding="utf-8")
    snap_path.write_text(json.dumps({"date": today, "data": new}, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
