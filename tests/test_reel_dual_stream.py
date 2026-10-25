import os
import subprocess
import tempfile
import pytest
from app.parsers.reel import extract_scene_tile, extract_audio_stream, is_video_reel_url

def test_is_video_reel_url():
    assert is_video_reel_url("https://www.facebook.com/reel/123456789") is True
    assert is_video_reel_url("https://www.facebook.com/share/r/abcxyz/") is True
    assert is_video_reel_url("https://fb.watch/shortlink/") is True
    assert is_video_reel_url("https://www.instagram.com/reel/C8XYZ123/") is True
    assert is_video_reel_url("https://github.com/fastapi/fastapi") is False
    assert is_video_reel_url("https://www.youtube.com/watch?v=123") is False

def test_extract_scene_tile_and_audio():
    with tempfile.TemporaryDirectory() as td:
        vid_path = os.path.join(td, "synthetic_reel.mp4")
        tile_path = os.path.join(td, "storyboard_tile.jpg")
        audio_path = os.path.join(td, "audio.mp3")

        # Create a 2-second test video with video and audio streams
        cmd = [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", "testsrc=duration=2:size=320x240:rate=10",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
            "-c:v", "libx264", "-c:a", "aac",
            vid_path
        ]
        res = subprocess.run(cmd, capture_output=True)
        assert res.returncode == 0
        assert os.path.exists(vid_path)

        # 1. Test Tile Storyboard generation (will trigger uniform fallback or scene cut)
        tile_ok = extract_scene_tile(vid_path, tile_path, duration=2.0)
        assert tile_ok is True
        assert os.path.exists(tile_path)
        assert os.path.getsize(tile_path) > 1024

        # 2. Test Audio extraction
        audio_ok = extract_audio_stream(vid_path, audio_path)
        assert audio_ok is True
        assert os.path.exists(audio_path)
        assert os.path.getsize(audio_path) > 500
