"""What this install can do right now, feature by feature, and how each one gets better (設定 › AI).

A new install works without an account (the no-signup services, app/ai_connections.py STARTER_CARDS),
and the owner upgrades when the difference matters to them (decided 2026-11-18). So every feature
says plainly how good it is now, measured where there is a measurement, and the one step that makes
it better. Nothing here calls a model or the network: it reads the connections and what is installed.
"""
import importlib.util
import os
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional

from app import ai_connections, provider_catalog
from app.config import settings

GOOD, BASIC, OFF = "good", "basic", "off"

# 2026-11-18, 18 saved items (GitHub, articles, YouTube, Threads, reels) analysed again by the
# no-signup chain and judged blind against the Gemini 4 analysis: Gemini better on 17.
FREE_ANALYSIS_NOTE = "用免註冊的服務：分析比較精簡，GitHub 專案比較少畫架構圖"
GEMINI_STEP = "申請免費的 Google AI Studio 金鑰（約 3 分鐘），加成一條連線"
AGENT_HINT = "也可以跟你的 agent 說要做什麼，它會照 OmniKeep 的安裝說明處理"


def _card(conn) -> Dict[str, Any]:
    return provider_catalog.card(conn.card) or {}


def _entries(slot: str):
    return [(conn, model) for conn, model in ai_connections.resolve(slot) if conn.enabled]


def _sees(conn) -> bool:
    if conn.kind == "gemini":
        return True
    caps = {**_card(conn).get("caps", {}), **conn.caps}
    return caps.get("vision", True) is not False


def _installed(*modules: str) -> bool:
    return all(importlib.util.find_spec(m) is not None for m in modules)


def _ollama_installed() -> bool:
    """Whether Ollama is on this machine (its program, not whether it runs: no network here)."""
    if shutil.which("ollama"):
        return True
    local = os.environ.get("LOCALAPPDATA")
    places = [Path("/Applications/Ollama.app"), Path("/usr/local/bin/ollama")]
    if local:
        places.append(Path(local) / "Programs" / "Ollama" / "ollama.exe")
    return any(p.exists() for p in places)


def _ffmpeg_installed() -> bool:
    """ffmpeg cuts the frames and the sound out of videos (app/parsers/reel.py, transcript.py, screen.py)."""
    return shutil.which("ffmpeg") is not None


def _ffmpeg_step() -> str:
    # 2026-11-26 review (KEEP-B-04): the installer and this page never mentioned ffmpeg, so a
    # machine without it showed short videos as good while every reel came back as text only.
    if os.name == "nt":
        command = "winget install --id Gyan.FFmpeg -e"
    elif Path("/Applications").exists():
        command = "brew install ffmpeg"
    else:
        command = "sudo apt install ffmpeg（或你的套件管理器）"
    return f"在伺服器安裝 ffmpeg：{command}（免帳號），再重新啟動 OmniKeep。" + AGENT_HINT


NO_FFMPEG = "沒裝 ffmpeg"


def _embedder_step(prefix: str = "") -> str:
    # 2026-11-18 rehearsal: a machine with Ollama but no embedding model was told to install Ollama
    if _ollama_installed():
        return f"{prefix}在 Ollama 下載向量模型（免帳號）。跟你的 agent 說「幫我設定 OmniKeep」，它會依這台電腦挑大小並下載"
    return f"{prefix}裝 Ollama 和向量模型（免帳號，安裝程式會依電腦挑大小）。" + AGENT_HINT


def _feature(fid: str, name: str, level: str, now: str, step: str = "", card: str = "") -> Dict[str, Any]:
    out: Dict[str, Any] = {"id": fid, "name": name, "level": level, "now": now}
    if step:
        out["step"] = step
    if card:
        out["card"] = card  # the settings page opens a new connection on this card
    return out


def _analysis() -> Dict[str, Any]:
    entries = _entries("analysis")
    if not entries:
        if not ai_connections.legacy_needs_setup():
            return _feature("analysis", "分析", GOOD, "用舊版的主要 AI 設定")
        return _feature("analysis", "分析", OFF, "還沒接 AI：新收藏只存原文，接上後可以補分析",
                        GEMINI_STEP, "gemini")
    if all(_card(conn).get("no_signup") for conn, _ in entries):
        return _feature("analysis", "分析", BASIC, FREE_ANALYSIS_NOTE, GEMINI_STEP + "，排在「分析」第 1 條", "gemini")
    first = next(conn for conn, _ in entries if not _card(conn).get("no_signup"))
    return _feature("analysis", "分析", GOOD, f"用 {first.label}")


def _search() -> Dict[str, Any]:
    from app.vector import LOCAL_EMBEDDING_MODEL, target_embedding_model
    model = target_embedding_model()
    if model == LOCAL_EMBEDDING_MODEL:
        return _feature("search", "用意思找收藏", OFF, "只比對關鍵字：要打出收藏裡有的字才找得到",
                        _embedder_step())
    first = next((conn for conn, _ in _entries("embeddings")), None)
    if first is not None and _card(first).get("no_signup"):
        # 2026-11-18: OVHcloud's Qwen3-Embedding-8B found the right item first 85% of the time on the
        # 300-item test, as the best local model did; the limit is 2 queries a minute
        return _feature("search", "用意思找收藏", BASIC,
                        f"用 {first.label} 的 {model}：找得跟最好的本機模型一樣準，但每分鐘只能查 2 次；"
                        "同一分鐘第 3 次起只比對關鍵字，所以常搜尋的時候多半是在用關鍵字找",
                        _embedder_step("沒有次數限制的做法："))
    return _feature("search", "用意思找收藏", GOOD, f"用 {model}")


def _video() -> Dict[str, Any]:
    if _entries("video") or settings.gemini_keys:
        return _feature("video", "直接看 YouTube 影片", GOOD, "Gemini 直接看畫面、聽聲音")
    return _feature("video", "直接看 YouTube 影片", OFF, "改讀字幕和畫面上的字，一樣會分析",
                    "只有 Google AI Studio 的 Gemini 能直接看影片：" + GEMINI_STEP + "，加到「影片」", "gemini")


def _reel_frames() -> Dict[str, Any]:
    if not _ffmpeg_installed():
        return _feature("reel_frames", "短影音畫面上的字", OFF,
                        f"{NO_FFMPEG}：短影音抽不出畫面和聲音，只用貼文文字", _ffmpeg_step())
    entries = _entries("analysis") + [e for e in _entries("video") if e not in _entries("analysis")]
    seeing = [conn for conn, _ in entries if _sees(conn)]
    if not seeing:
        return _feature("reel_frames", "短影音畫面上的字", OFF, "目前的連線都不能看圖：只用語音和貼文文字",
                        GEMINI_STEP, "gemini")
    return _feature("reel_frames", "短影音畫面上的字", GOOD, f"用 {seeing[0].label} 看畫面")


def _screen_text() -> Dict[str, Any]:
    from app.parsers import screen
    if not _ffmpeg_installed():
        return _feature("screen_text", "長影片畫面上的字", OFF, f"{NO_FFMPEG}：讀不到影片畫面，只用逐字稿",
                        _ffmpeg_step())
    if not screen.missing_packages():
        return _feature("screen_text", "長影片畫面上的字", GOOD, "在這台電腦讀投影片和圖表上的字")
    return _feature("screen_text", "長影片畫面上的字", OFF, "沒裝畫面文字辨識：只用逐字稿",
                    "在伺服器執行 pip install -r requirements-ocr.txt（約 165 MB，免帳號），再重新啟動。" + AGENT_HINT)


def _speech() -> Dict[str, Any]:
    if not _ffmpeg_installed():
        return _feature("speech", "沒有字幕的影片轉文字", OFF, f"{NO_FFMPEG}：解不開影片的聲音，沒有字幕的影片無法分析內容",
                        _ffmpeg_step())
    if _installed("faster_whisper", "ctranslate2"):
        return _feature("speech", "沒有字幕的影片轉文字", GOOD, "在這台電腦把語音轉成文字")
    return _feature("speech", "沒有字幕的影片轉文字", OFF, "沒裝語音轉文字：沒有字幕的影片無法分析內容",
                    "在伺服器執行 pip install -r requirements-stt.txt（約 210 MB，免帳號；有 NVIDIA 顯示卡最好），再重新啟動。"
                    + AGENT_HINT)


def features() -> List[Dict[str, Any]]:
    return [_analysis(), _search(), _video(), _reel_frames(), _screen_text(), _speech()]


def summary() -> Optional[str]:
    """One line for the top of the card, or None when everything is as good as it gets."""
    rows = features()
    weak = [r["name"] for r in rows if r["level"] != GOOD]
    if not weak:
        return None
    return "、".join(weak) + " 還可以更好，各項下面寫了怎麼做。"
