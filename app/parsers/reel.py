import os
import re
import base64
import asyncio
import subprocess
import tempfile
from typing import Dict, Any, List
import yt_dlp
from app.providers import get_primary_provider
from app.parsers.web import parse_facebook_page

def is_video_reel_url(url: str) -> bool:
    clean = url.lower()
    return (
        "facebook.com/reel" in clean
        or "facebook.com/share/r" in clean
        or "fb.watch" in clean
        or "instagram.com/reel" in clean
    )

async def parse_video_reel(url: str) -> Dict[str, Any]:
    """
    Multimodal Video Reel Analyzer:
    1. Downloads short reel video stream via yt-dlp.
    2. Extracts 1 frame per second using ffmpeg.
    3. Runs Vision OCR to extract on-screen project names, URLs, and architecture points.
    4. Combines video OCR with post caption for full pipeline analysis.
    Gracefully falls back to web metadata parser if video download fails.
    """
    temp_dir = tempfile.mkdtemp(prefix="omni_reel_")
    video_path = os.path.join(temp_dir, "reel.mp4")
    frames_dir = os.path.join(temp_dir, "frames")
    os.makedirs(frames_dir, exist_ok=True)

    try:
        # 1. Download short reel stream via yt-dlp
        ydl_opts = {
            'format': 'b[ext=mp4]/best',
            'outtmpl': video_path,
            'quiet': True,
            'overwrites': True,
            'socket_timeout': 15,
        }

        loop = asyncio.get_event_loop()
        def _download():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                return ydl.extract_info(url, download=True)

        info = await loop.run_in_executor(None, _download)
        raw_title = info.get("title") or ""
        uploader = info.get("uploader") or ""
        description = info.get("description") or ""
        duration = info.get("duration") or 10

        # Clean title
        cleaned_title = raw_title
        if "|" in cleaned_title:
            cleaned_title = cleaned_title.rsplit("|", 1)[0].strip()
        cleaned_title = re.sub(r'^\d+\s*reactions.*?[\|·]\s*', '', cleaned_title)
        cleaned_title = re.sub(r'^\d+\s*個心情.*?\|\s*', '', cleaned_title)
        if len(cleaned_title) > 60:
            cleaned_title = cleaned_title[:60].strip() + "..."

        author = uploader or "短影音創作者"

        # 2. Extract key frames with ffmpeg (1 fps, max 12 frames to preserve performance)
        max_frames = min(12, int(duration) if duration > 0 else 10)
        ffmpeg_cmd = [
            "ffmpeg", "-y", "-i", video_path,
            "-vf", "fps=1",
            "-vframes", str(max_frames),
            os.path.join(frames_dir, "frame_%02d.jpg")
        ]
        await loop.run_in_executor(None, lambda: subprocess.run(ffmpeg_cmd, capture_output=True))

        frames = sorted([os.path.join(frames_dir, f) for f in os.listdir(frames_dir) if f.endswith(".jpg")])

        # 3. Vision OCR on frames using parallel execution to prevent multi-image context truncation
        visual_content = ""
        if frames:
            provider = get_primary_provider()
            prompt = """請讀取這張短影音畫面中展示的開源專案卡片資訊，輸出純文字格式：
編號：(右上角數字)
專案名稱：
GitHub 網址：(如 https://github.com/...)
用途：(一句話說明功能與行銷情境)"""

            async def _analyze_frame(fp: str, idx: int):
                try:
                    with open(fp, "rb") as f:
                        b64 = base64.b64encode(f.read()).decode("utf-8")
                    res = await provider.client.chat.completions.create(
                        model=provider.model,
                        messages=[{
                            "role": "user",
                            "content": [
                                {"type": "text", "text": prompt},
                                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}
                            ]
                        }],
                        temperature=0.1
                    )
                    return res.choices[0].message.content.strip()
                except Exception:
                    return ""

            # Run parallel analysis across all extracted frames
            tasks = [_analyze_frame(fp, i) for i, fp in enumerate(frames, 1)]
            frame_texts = await asyncio.gather(*tasks)
            visual_content = "\n\n".join([t for t in frame_texts if t.strip()])

        # 4. Synthesize raw content combining description + visual OCR
        combined_raw = f"""# {cleaned_title}
作者/發布者：{author}
影音長度：約 {duration} 秒

## 影片貼文說明
{description}

## 短影音畫面視覺 OCR 與專案解構
{visual_content}
"""

        cover_image = info.get("thumbnail") or ""

        return {
            "url": url,
            "title": cleaned_title or "短影音情報",
            "content_raw": combined_raw.strip(),
            "cover_image": cover_image,
            "author": author,
            "published_date": "",
        }

    except Exception as e:
        print(f"[Reel Analyzer] Video extraction failed ({e}), falling back to page metadata...")
        # Fallback to standard web parser
        return await parse_facebook_page(url)

    finally:
        # Clean up temp files
        try:
            shutil.rmtree(temp_dir, ignore_errors=True)
        except Exception:
            pass
