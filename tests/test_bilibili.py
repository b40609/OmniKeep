import json
from unittest.mock import AsyncMock, patch
import pytest

from app.parsers.bilibili import is_bilibili_url, extract_bvid, parse_bilibili_video
from app.pipeline import run_pipeline


def test_is_bilibili_url():
    assert is_bilibili_url("https://www.bilibili.com/video/BV1kMxM6FECM")
    assert is_bilibili_url("http://bilibili.com/video/BV1kMxM6FECM?spm_id_from=333.999")
    assert is_bilibili_url("https://b23.tv/BV1kMxM6FECM")
    assert is_bilibili_url("https://b23.tv/m7gK41z")
    assert is_bilibili_url("https://m.bilibili.com/video/BV1kMxM6FECM")
    assert not is_bilibili_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    assert not is_bilibili_url("https://github.com/fastapi/fastapi")
    assert not is_bilibili_url("invalid-url")


def test_extract_bvid():
    assert extract_bvid("https://www.bilibili.com/video/BV1kMxM6FECM") == "BV1kMxM6FECM"
    assert extract_bvid("https://b23.tv/BV1kMxM6FECM?spm=1") == "BV1kMxM6FECM"
    assert extract_bvid("https://www.bilibili.com/video/av170001") == "av170001"
    assert extract_bvid("https://www.bilibili.com") is None


@pytest.mark.asyncio
async def test_parse_bilibili_video_with_subtitles():
    fake_initial_state = {
        "videoData": {
            "bvid": "BV1TestBvid123",
            "title": "測試 Bilibili 科技長影片",
            "desc": "這是一部關於大模型與 GPU 架構的深度測試影片",
            "duration": 1800,
            "pic": "https://i0.hdslb.com/bfs/archive/fake_cover.jpg",
            "owner": {"name": "科技工研客"},
            "subtitle": {
                "list": [
                    {
                        "id": 12345,
                        "lan": "zh-CN",
                        "lan_doc": "中文（簡體）",
                        "subtitle_url": "https://i0.hdslb.com/bfs/subtitle/test.json"
                    }
                ]
            }
        }
    }
    fake_sub_body = {
        "body": [
            {"from": 0.0, "to": 4.5, "content": "大家好，歡迎來到這期架構分析"},
            {"from": 5.0, "to": 9.2, "content": "今天我們要來實測 RTX 2000 Ada 與 14700 算力表現"}
        ]
    }

    mock_html = f"<html><body><script>window.__INITIAL_STATE__={json.dumps(fake_initial_state)};</script></body></html>"

    class MockResp:
        def __init__(self, status_code, text, json_data=None, url="https://www.bilibili.com/video/BV1TestBvid123"):
            self.status_code = status_code
            self.text = text
            self._json = json_data or {}
            self.url = url
            self.headers = {}

        def json(self):
            return self._json

    async def fake_get(url, **kwargs):
        if "subtitle" in url:
            return MockResp(200, "", fake_sub_body)
        return MockResp(200, mock_html)

    with patch("app.parsers.bilibili.public_http_client") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=fake_get)
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client_cls.return_value = mock_client

        data = await parse_bilibili_video("https://www.bilibili.com/video/BV1TestBvid123")

        assert data["title"] == "測試 Bilibili 科技長影片"
        assert data["author"] == "科技工研客"
        assert data["duration"] == 1800
        assert data["cover_image"] == "https://i0.hdslb.com/bfs/archive/fake_cover.jpg"
        assert data["source_type"] == "bilibili"
        assert "[00:00] 大家好，歡迎來到這期架構分析" in data["content_raw"]
        assert "[00:05] 今天我們要來實測 RTX 2000 Ada" in data["content_raw"]


@pytest.mark.asyncio
async def test_pipeline_bilibili_e2e():
    # Users decide which categories exist; AI can use an explicitly created one.
    from app.database import add_category
    add_category("AI")
    mock_bili_data = {
        "url": "https://www.bilibili.com/video/BV1TestPipeline",
        "title": "Bilibili 長影片測試",
        "author": "極客測試者",
        "duration": 1200,
        "cover_image": "https://i0.hdslb.com/bfs/cover.jpg",
        "content_raw": "# Bilibili 長影片測試\n\nUP主: 極客測試者\n\n## 內容\n語音轉錄內容測試",
        "source_type": "bilibili"
    }

    mock_ai_json = {
        "category": "AI",
        "title_l1": "測試 Bilibili 影片分析",
        "summary_l1": "這是一份經過結構化提煉的 Bilibili 深度技術摘要。",
        "tech_tags": ["Bilibili", "AI", "Whisper"],
        "deep_analysis": "### 核心技術架構\n1. 支援字幕與 Whisper 雙軌語音轉錄\n2. 結構化提煉",
        "is_composite": False,
        "sub_entities": []
    }

    with patch("app.pipeline.parse_bilibili_video", new_callable=AsyncMock) as mock_parse, \
         patch("app.pipeline.get_primary_provider") as mock_provider_fn:

        mock_parse.return_value = mock_bili_data
        mock_provider = AsyncMock()
        mock_provider.generate_json = AsyncMock(return_value=mock_ai_json)
        mock_provider_fn.return_value = mock_provider

        item = await run_pipeline("https://www.bilibili.com/video/BV1TestPipeline")

        assert item["source_type"] == "bilibili"
        assert item["title_l1"] == "測試 Bilibili 影片分析"
        assert item["category_name"] == "AI"
        assert "Whisper" in item["tech_tags"]
        assert item["cover_image"] == "https://i0.hdslb.com/bfs/cover.jpg"
