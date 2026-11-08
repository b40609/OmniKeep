"""X posts are read through public JSON mirrors, since x.com only answers "JavaScript is disabled"."""
import asyncio
import json

import pytest

from app.parsers import x_posts
from app.parsers.x_posts import (LONG_POST_NOTE, REPLIES_MISSING, from_fxtwitter, from_oembed, from_syndication,
                                 from_vxtwitter, parse_x_post, render, syndication_token, x_status)

FX = {"code": 200, "tweet": {
    "text": "这套越狱提示词居然是免费的\n\n地址在这里：https://github.com/togg53192-cmd/jailbreaks",
    "created_at": "Sat Nov 07 09:36:00 +0000 2026",
    "author": {"name": "陈发财", "screen_name": "Chenfacai0"},
    "media": {"photos": [{"url": "https://pbs.twimg.com/media/a.jpg"}],
              "videos": [{"url": "https://video.twimg.com/v.mp4", "thumbnail_url": "https://pbs.twimg.com/t.jpg"}]},
    "quote": {"text": "原推", "author": {"name": "某人", "screen_name": "someone"}, "created_at": ""},
}}
SYND = {"text": "以下5个网站：\n\n1. https://t.co/aaa - 设计提示词 https://t.co/media",
        "created_at": "2026-11-07T18:04:20.000Z", "user": {"name": "牧枫", "screen_name": "mr_mofun"},
        "entities": {"urls": [{"url": "https://t.co/aaa", "expanded_url": "https://Scrolltide.co"}]},
        "mediaDetails": [{"type": "photo", "url": "https://t.co/media", "media_url_https": "https://pbs.twimg.com/p.jpg"}],
        "note_tweet": {"id": "x"}}


@pytest.mark.parametrize("url, expected", [
    ("https://x.com/chenfacai0/status/2119000907740594279?a=UUxvOl3CfDhkaDC9-VE&s=52",
     ("chenfacai0", "2119000907740594279")),
    ("https://twitter.com/jack/status/20", None),  # too short to be a real post id
    ("https://twitter.com/jack/status/12345678", ("jack", "12345678")),
    ("https://mobile.twitter.com/a_b/status/2119128837267378509/photo/1", ("a_b", "2119128837267378509")),
    ("https://x.com/i/web/status/2119128837267378509", ("", "2119128837267378509")),
    ("https://x.com/i/status/2119128837267378509", ("", "2119128837267378509")),
    ("https://fxtwitter.com/mr_mofun/status/2119128837267378509", ("mr_mofun", "2119128837267378509")),
    ("https://x.com/mr_mofun", None),
    ("https://example.com/u/status/2119128837267378509", None),
])
def test_post_urls_on_x_and_its_mirrors(url, expected):
    assert x_status(url) == expected


@pytest.mark.parametrize("post_id, token", [
    # Node: ((Number(id) / 1e15) * Math.PI).toString(36).replace(/(0+|\.)/g, '')
    ("2119128837267378509", "54xftpdn5nb"),
    ("2119000907740594279", "54x1cu7u6m"),
    ("1688632658282868736", "43czur826sh"),
    ("20", "6dq1a2xwd93"),
])
def test_syndication_token_is_the_one_x_embed_script_sends(post_id, token):
    assert syndication_token(post_id) == token


def test_fxtwitter_answer_keeps_text_author_media_and_the_quoted_post():
    post = from_fxtwitter(FX)
    text = render(post)
    assert text.startswith("陈发财 (@Chenfacai0) 在 X 發文 · 2026-11-07 09:36 UTC")
    assert "https://github.com/togg53192-cmd/jailbreaks" in text
    assert "- https://pbs.twimg.com/media/a.jpg" in text and "- https://video.twimg.com/v.mp4" in text
    assert "> 某人 (@someone) 在 X 發文" in text and "> 原推" in text
    assert from_fxtwitter({"code": 404, "message": "NOT_FOUND"}) is None


def test_syndication_expands_links_drops_the_media_link_and_says_a_long_post_is_cut():
    text = render(from_syndication(SYND))
    assert "1. https://Scrolltide.co - 设计提示词" in text and "t.co" not in text
    assert LONG_POST_NOTE in text and "- https://pbs.twimg.com/p.jpg" in text


def test_vxtwitter_and_oembed_answers():
    vx = from_vxtwitter({"text": "hello", "user_name": "A", "user_screen_name": "a", "date": "",
                         "mediaURLs": ["https://pbs.twimg.com/x.jpg"], "qrt": None})
    assert vx["text"] == "hello" and vx["photos"] == ["https://pbs.twimg.com/x.jpg"]
    oembed = from_oembed({"author_name": "陈发财", "author_url": "https://twitter.com/Chenfacai0",
                          "html": '<blockquote class="twitter-tweet"><p lang="zh">第一行<br><br>第二行 '
                                  '<a href="https://t.co/x">pic.twitter.com/x</a></p>&mdash; 陈发财</blockquote>'})
    assert oembed["text"] == "第一行\n\n第二行" and oembed["screen"] == "Chenfacai0"
    assert from_oembed({"html": "<blockquote></blockquote>"}) is None


class _Resp:
    def __init__(self, status, body):
        self.status_code, self._body = status, body

    def json(self):
        if isinstance(self._body, str):
            return json.loads(self._body)
        return self._body


def _client(answers, asked):
    class Client:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, url, params=None):
            asked.append(url + (f"?cursor={params['cursor']}" if params else ""))
            for host, answer in answers.items():
                if host in url:
                    if isinstance(answer, Exception):
                        raise answer
                    return _Resp(*answer)
            return _Resp(404, {})
    return Client


def test_the_next_source_answers_when_one_is_down(monkeypatch):
    asked = []
    monkeypatch.setattr(x_posts, "public_http_client", _client({
        "fxtwitter": (503, "<html>down</html>"),
        "syndication": (200, SYND),
    }, asked))
    page = asyncio.run(parse_x_post("https://x.com/mr_mofun/status/2119128837267378509?s=52"))
    assert page["source"] == "X syndication" and page["http_status"] == 200
    assert page["url"] == "https://x.com/mr_mofun/status/2119128837267378509?s=52"  # kept, so the item is updated in place
    assert page["title"] == "牧枫 (@mr_mofun) on X" and page["author"] == "牧枫 (@mr_mofun)"
    assert page["cover_image"] == "https://pbs.twimg.com/p.jpg"
    assert "https://Scrolltide.co" in page["content_raw"]
    assert REPLIES_MISSING in page["content_raw"]  # syndication has no replies: tried again later
    assert [u.split("/")[2] for u in asked] == ["api.fxtwitter.com", "api.fxtwitter.com", "cdn.syndication.twimg.com"]


def test_no_post_when_every_source_fails_so_the_usual_fetch_takes_over(monkeypatch):
    asked = []
    monkeypatch.setattr(x_posts, "public_http_client", _client({
        "fxtwitter": (200, ""),  # empty body: not JSON
        "syndication": (200, {}),
        "vxtwitter": TimeoutError(),
        "publish.twitter.com": (404, {}),
    }, asked))
    assert asyncio.run(parse_x_post("https://x.com/u/status/2119128837267378509")) is None
    assert len(asked) == 5


def test_a_profile_or_another_site_never_calls_the_mirrors(monkeypatch):
    asked = []
    monkeypatch.setattr(x_posts, "public_http_client", _client({}, asked))
    assert asyncio.run(parse_x_post("https://x.com/mr_mofun")) is None
    assert asyncio.run(parse_x_post("https://example.com/a/status/2119128837267378509")) is None
    assert asked == []


def test_web_parser_hands_x_posts_to_the_mirrors(monkeypatch):
    from app.parsers import web

    async def fake(url):
        return {"url": url, "title": "A (@a) on X", "content_raw": "A (@a) 在 X 發文\n\nhello", "cover_image": "",
                "author": "A (@a)", "published_date": "", "raw_html": "", "http_status": 200, "source": "FxTwitter"}
    monkeypatch.setattr(x_posts, "parse_x_post", fake)
    page = asyncio.run(web.parse_web_page("https://x.com/a/status/2119128837267378509"))
    assert page["source"] == "FxTwitter" and "hello" in page["content_raw"]


def _status(post_id, screen, text, to=None, replies=None, name=None):
    return {"id": post_id, "text": text, "created_at": "Sat Nov 07 09:36:00 +0000 2026",
            "author": {"name": name or screen, "screen_name": screen}, "media": {},
            "replying_to": {"screen_name": to, "status": "1"} if to else None, "replies": replies}


def _routes(routes, asked):
    """A fake client answering by URL substring; a list answers page after page."""
    class Client:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, url, params=None):
            asked.append(url + (f"?cursor={params['cursor']}" if params else ""))
            for part, answer in routes.items():
                if part in url:
                    if isinstance(answer, list):
                        answer = answer.pop(0) if answer else (200, {"replies": []})
                    if isinstance(answer, Exception):
                        raise answer
                    return _Resp(*answer)
            return _Resp(404, {})
    return Client


MAIN = _status("100000", "goan", "Codex + claude-mem 这套组合", replies=3, name="G哥")
THREAD = {"status": MAIN, "thread": [MAIN, _status("100001", "goan", "安装方法：https://github.com/thedotmack/claude-mem",
                                                    to="goan"),
                                     _status("100009", "someone", "not the author", to="goan")]}


def test_the_authors_follow_up_posts_and_the_replies_are_read_page_after_page(monkeypatch):
    asked = []
    monkeypatch.setattr(x_posts, "public_http_client", _routes({
        "/2/thread/": (200, THREAD),
        "/2/conversation/": [
            (200, {"replies": [_status("100001", "goan", "安装方法", to="goan"),  # already in the thread
                               _status("200001", "Dicklong", "@goan 现在马上去试试", to="goan", name="liftoff")],
                   "cursor": {"bottom": "c2"}}),
            (200, {"replies": [_status("200002", "goan", "@Dicklong 用起来吧", to="Dicklong", name="G哥")],
                   "cursor": {"bottom": "c3"}}),
            (200, {"replies": [], "cursor": {"bottom": "c4"}}),
        ],
    }, asked))
    page = asyncio.run(parse_x_post("https://x.com/goan/status/100000"))
    text = page["content_raw"]
    assert page["source"] == "FxTwitter" and REPLIES_MISSING not in text
    assert "作者接著發的 1 則貼文：\n\n（1）安装方法：https://github.com/thedotmack/claude-mem" in text
    assert "not the author" not in text.split("留言")[0]
    assert "留言（收錄 2 則，貼文顯示共 3 則）：" in text
    assert "- liftoff (@Dicklong)：现在马上去试试" in text  # the leading @mention is dropped
    assert "- G哥 (@goan) 回覆 @Dicklong：用起来吧" in text
    assert text.count("安装方法") == 1
    assert [u.rsplit("/", 1)[-1] for u in asked] == ["100000", "100000", "100000?cursor=c2", "100000?cursor=c3"]


def test_replies_that_cannot_be_read_are_marked_for_a_later_try(monkeypatch):
    monkeypatch.setattr(x_posts, "public_http_client", _routes({
        "/2/thread/": (200, THREAD), "/2/conversation/": (500, {})}, []))
    page = asyncio.run(parse_x_post("https://x.com/goan/status/100000"))
    assert page["source"] == "FxTwitter" and "安装方法" in page["content_raw"]
    assert page["content_raw"].endswith(REPLIES_MISSING)


def test_a_post_with_no_replies_does_not_ask_for_them(monkeypatch):
    asked = []
    quiet = {"status": {**MAIN, "replies": 0}, "thread": [MAIN]}
    monkeypatch.setattr(x_posts, "public_http_client", _routes({"/2/thread/": (200, quiet)}, asked))
    page = asyncio.run(parse_x_post("https://x.com/goan/status/100000"))
    assert REPLIES_MISSING not in page["content_raw"] and "留言" not in page["content_raw"]
    assert len(asked) == 1
