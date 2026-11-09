"""What a long video shows on screen and its speech does not say: slides, charts, screenshots.

Measured 2026-11-09 on a 10-minute Taiwanese news commentary (HifbaXJNxHU): 78 of 82 distinct frames
had text, mostly burned-in subtitles repeating the speech; 19 showed what the speech never says
(market-share chart 32% against 25%, a share price at -12.31%, a paper's date). Those are what this
adds, as "## 畫面重點（OCR，可能有錯字）" with a [MM:SS] per frame. A local vision model was too slow
and returned nothing for half the frames, so the text is read with OCR only.

Steps: ffmpeg decodes the video once into a small, low frame rate proxy -> PySceneDetect's
AdaptiveDetector finds the cuts; the middle of each scene plus a frame every FLOOR_EVERY seconds ->
pHash against every frame kept so far (a slide shown twice is read once) -> RapidOCR -> only the
lines the transcript does not already say and no earlier frame showed (logos, watermarks).

Optional (requirements-ocr.txt): without the packages the section is skipped with one log line, and
the transcript and analysis go on as before. Short videos (YouTube Shorts, Reels) keep their
12-frame storyboard (app/parsers/reel.py).
"""
import asyncio
import importlib.util
import logging
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional, Tuple

from app.parsers.transcript import _cjk_join, _short, plain_text, stamp, to_traditional

logger = logging.getLogger("omnikeep.screen")

SECTION_TITLE = "## 畫面重點（OCR，可能有錯字）"
PACKAGES = {"scenedetect": "scenedetect", "cv2": "opencv-python-headless", "imagehash": "imagehash",
            "rapidocr": "rapidocr", "onnxruntime": "onnxruntime"}
MIN_SECONDS = 60  # shorter ones are Shorts-like; reel.py reads those from a storyboard
MAX_SECONDS = 2 * 3600  # longer videos are not downloaded for this
READ_SECONDS = 3600  # of a long video, frames from the first hour only
TIME_BUDGET = 480  # seconds for decoding, cut detection and OCR; what is read by then is kept
DOWNLOAD_HEIGHT = 720  # 480p misread small numbers (53 as 63, 68% as 21.68%)
MAX_DOWNLOAD_BYTES = 600 * 1024 * 1024
PROXY_FPS = 2
FLOOR_EVERY = 20  # seconds: slides that change without a cut still get a frame
PHASH_DISTANCE = 6
MIN_SCORE = 0.6  # OCR confidence
MIN_LINE_NEW = 2  # a line is kept with this many units the speech and earlier frames lack ...
MIN_LINE_SHARE = 0.3  # ... making up this share of it (a subtitle line misread in one place is not)
MIN_NOVEL = 6  # new units a frame needs to be listed
MAX_LINES = 60
MAX_LINE_CHARS = 300
MAX_SECTION_CHARS = 6000

_lock = threading.Lock()  # one video at a time: decoding and OCR take every CPU core
_missing_logged = False
_engines: Optional[List[Any]] = None


def missing_packages() -> List[str]:
    return [package for module, package in PACKAGES.items() if importlib.util.find_spec(module) is None]


def available() -> bool:
    global _missing_logged
    missing = missing_packages()
    if missing and not _missing_logged:
        logger.warning("[Screen] %s not installed; video frames are not read "
                       "(pip install -r requirements-ocr.txt)", ", ".join(missing))
        _missing_logged = True
    return not missing


# ── frames ─────────────────────────────────────────────────────────────────────

def _proxy(video: str, folder: str, seconds: float, timeout: float) -> str:
    """The video at PROXY_FPS as MJPEG: every frame a keyframe, so picking frames costs no seeking."""
    path = os.path.join(folder, "proxy.avi")
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-protocol_whitelist", "file,pipe",
           "-t", str(int(seconds)), "-i", video, "-an",
           "-vf", f"fps={PROXY_FPS},scale=-2:'min({DOWNLOAD_HEIGHT},ih)'",
           "-c:v", "mjpeg", "-q:v", "3", path]
    proc = subprocess.run(cmd, capture_output=True, timeout=max(10, timeout))
    if proc.returncode != 0 or not os.path.exists(path):
        raise RuntimeError("ffmpeg 解不開影片：" + proc.stderr.decode("utf-8", "replace").strip()[-160:])
    return path


def _cut_frames(proxy: str) -> Tuple[List[int], int]:
    """Proxy frame numbers to read (scene middles and the floor), and the proxy's frame count."""
    from scenedetect import AdaptiveDetector, SceneManager, open_video
    video = open_video(proxy)
    manager = SceneManager()
    # Frames, not seconds: scenedetect 0.6 takes only frames. 2 frames = 1 s at PROXY_FPS.
    manager.add_detector(AdaptiveDetector(min_scene_len=2))
    manager.detect_scenes(video)

    def frame(timecode) -> int:  # 0.7 deprecates get_frames() for frame_num; 0.6 has both
        number = getattr(timecode, "frame_num", None)
        return int(number) if number is not None else int(timecode.get_frames())

    total = frame(video.duration)
    picks = {(frame(a) + frame(b)) // 2 for a, b in manager.get_scene_list()}
    step = FLOOR_EVERY * PROXY_FPS
    picks |= set(range(step // 2, total, step))
    return sorted(p for p in picks if 0 <= p < total), total


def _distinct(proxy: str, picks: List[int]) -> List[Tuple[float, Any]]:
    """(seconds, BGR image) of the picked frames that look unlike every frame kept before."""
    import cv2
    import imagehash
    from PIL import Image
    kept, hashes = [], []
    capture = cv2.VideoCapture(proxy)
    try:
        for frame in picks:
            capture.set(cv2.CAP_PROP_POS_FRAMES, frame)
            ok, image = capture.read()
            if not ok:
                continue
            digest = imagehash.phash(Image.fromarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB)))
            if any(digest - other <= PHASH_DISTANCE for other in hashes):
                continue
            hashes.append(digest)
            kept.append((frame / PROXY_FPS, image))
    finally:
        capture.release()
    return kept


def _ocr_engines() -> List[Any]:
    """Several small engines in threads: onnxruntime's default (every core on one image) read 82
    frames in 61.7 s on a 20-core desktop CPU, 4 engines of 5 threads in 18.0 s (measured 2026-11-09)."""
    global _engines
    if _engines is None:
        from rapidocr import RapidOCR
        cores = os.cpu_count() or 4
        workers = max(1, min(4, cores // 6))
        threads = max(1, min(5, cores // (workers + 1)))
        # Video text is upright (no angle classifier); log level "error": RapidOCR warns on every frame
        # without text. The long side capped at 960 px, so a frame is not blown up to 736 px on its
        # short side, which only made detection slower. About 110 MiB for the 4 engines.
        params = {"Global.use_cls": False, "Global.log_level": "error",
                  "Det.limit_type": "max", "Det.limit_side_len": 960,
                  "EngineConfig.onnxruntime.intra_op_num_threads": threads}
        _engines = [RapidOCR(params=params) for _ in range(workers)]
    return _engines


def _read(engine: Any, image: Any) -> List[str]:
    result = engine(image)
    texts, scores = getattr(result, "txts", None) or (), getattr(result, "scores", None) or ()
    return [text.strip() for text, score in zip(texts, scores) if score >= MIN_SCORE and text.strip()]


def _read_all(frames: List[Tuple[float, Any]], deadline: float) -> List[Tuple[float, List[str]]]:
    """OCR lines of each frame, in time order, up to the first frame not read by the deadline."""
    engines = _ocr_engines()
    results: List[Optional[List[str]]] = [None] * len(frames)

    def work(worker: int) -> None:
        for index in range(worker, len(frames), len(engines)):
            if time.monotonic() > deadline:
                return
            results[index] = _read(engines[worker], frames[index][1])

    with ThreadPoolExecutor(len(engines)) as pool:
        list(pool.map(work, range(len(engines))))
    read = []
    for (at, _), lines in zip(frames, results):
        if lines is None:
            break
        read.append((at, lines))
    return read


# ── what is new ────────────────────────────────────────────────────────────────

_CJK_RUN = re.compile(r"[㐀-鿿豈-﫿]+")
_WORD = re.compile(r"[a-z0-9]+(?:[.,][0-9]+)*")


def _units(text: str) -> set:
    """Chinese as character pairs, other text as whole words and numbers: English letter pairs are
    so common that after one screenshot of English nothing would look new."""
    text = to_traditional(text).lower()
    units = set(_WORD.findall(text))
    for run in _CJK_RUN.findall(text):
        units |= {run[i:i + 2] for i in range(len(run) - 1)} if len(run) > 1 else {run}
    return units


def novel_lines(frames: List[Tuple[float, List[str]]], transcript: str) -> List[Tuple[float, str]]:
    """(seconds, text) of the frames whose text the speech and the earlier frames do not have.

    A line is kept when enough of it is new; a frame is listed when its kept lines bring at least
    MIN_NOVEL new units. Burned-in subtitles repeat the speech and drop out; a logo or watermark
    is new once, then seen."""
    said = _units(plain_text(transcript))
    seen: set = set()
    found = []
    for at, lines in frames:
        kept, new = [], 0
        for line in lines:
            units = _units(line)
            fresh = units - said - seen
            if len(fresh) >= MIN_LINE_NEW and len(fresh) >= MIN_LINE_SHARE * len(units):
                kept.append(line)
                new += len(fresh)
        for line in lines:
            seen |= _units(line)
        if kept and new >= MIN_NOVEL:
            found.append((at, " / ".join(kept)[:MAX_LINE_CHARS]))
    return found


def section(found: List[Tuple[float, str]], note: str = "") -> str:
    lines, size = [], 0
    for at, text in found[:MAX_LINES]:
        line = f"- {stamp(at)} {text}"
        if size + len(line) > MAX_SECTION_CHARS:
            break
        lines.append(line)
        size += len(line) + 1
    if not lines:
        return ""
    head = f"{SECTION_TITLE}\n影片畫面上的字（投影片、圖表、截圖），只列旁白沒講到的部分{note}。"
    return head + "\n" + "\n".join(lines)


def read_screen(video: str, transcript: str, duration: float, stats: Optional[Dict[str, Any]] = None) -> str:
    """The section for a video file on disk, "" when nothing on screen adds to the transcript."""
    stats = stats if stats is not None else {}
    start = time.monotonic()
    deadline = start + TIME_BUDGET
    seconds = min(duration or READ_SECONDS, READ_SECONDS)
    folder = tempfile.mkdtemp(prefix="omni_screen_")
    try:
        proxy = _proxy(video, folder, seconds, TIME_BUDGET)
        stats["decode_s"] = round(time.monotonic() - start, 1)
        picks, total = _cut_frames(proxy)
        frames = _distinct(proxy, picks)
        stats.update(candidates=len(picks), kept=len(frames), detect_s=round(time.monotonic() - start, 1))
        read = _read_all(frames, deadline)
        stats.update(ocr_frames=len(read), total_s=round(time.monotonic() - start, 1))
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    found = novel_lines(read, transcript)
    stats["listed"] = len(found)
    note = ""
    if len(read) < len(frames):
        note = f"（時間到，只讀到 {stamp(read[-1][0] if read else 0)}）"
    elif duration and duration > READ_SECONDS:
        note = f"（只讀前 {READ_SECONDS // 60} 分鐘）"
    return section(found, note)


# ── YouTube ────────────────────────────────────────────────────────────────────

def _download_video(url: str, folder: str) -> str:
    """A low resolution, video-only copy: H.264 first, it decodes several times faster than AV1."""
    from app.parsers.transcript import BASE_OPTS, _with_session
    height = DOWNLOAD_HEIGHT
    opts = {**BASE_OPTS, "outtmpl": os.path.join(folder, "video.%(ext)s"), "overwrites": True,
            "max_filesize": MAX_DOWNLOAD_BYTES,
            "format": (f"bestvideo[height<={height}][vcodec^=avc1]/bestvideo[height<={height}]"
                       f"/best[height<={height}]")}
    _with_session(url, opts, lambda ydl: ydl.extract_info(url, download=True))
    found = [os.path.join(folder, f) for f in os.listdir(folder) if f.startswith("video.") and not f.endswith(".part")]
    if not found:
        raise RuntimeError("影片沒有下載下來")
    return found[0]


def _screen_sync(url: str, duration: float, transcript: str) -> str:
    with _lock:
        folder = tempfile.mkdtemp(prefix="omni_video_")
        try:
            started = time.monotonic()
            video = _download_video(url, folder)
            stats: Dict[str, Any] = {"download_s": round(time.monotonic() - started, 1)}
            text = read_screen(video, transcript, duration, stats)
            logger.info("[Screen] %s: %s", url, stats)
            return text
        finally:
            shutil.rmtree(folder, ignore_errors=True)


async def screen_notes(url: str, info: Optional[Dict[str, Any]], transcript: str) -> str:
    """The "畫面重點" section of a YouTube video, "" when skipped or nothing on screen is new.

    Never raises: the transcript and the analysis go on without it."""
    duration = float((info or {}).get("duration") or 0)
    if not (MIN_SECONDS <= duration <= MAX_SECONDS) or not transcript.strip() or not available():
        return ""
    try:
        return await asyncio.to_thread(_screen_sync, url, duration, transcript)
    except Exception as exc:
        logger.warning("[Screen] %s: frames not read (%s)", url, _short(exc))
        return ""
