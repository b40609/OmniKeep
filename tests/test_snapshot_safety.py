"""A saved page is untrusted: nothing in a snapshot may run or reach outside its folder."""
import pytest
from bs4 import BeautifulSoup
from fastapi.testclient import TestClient

from app.config import settings
from app.database import save_item
from app.main import app
from app.snapshot import (
    SNAPSHOT_HEADERS,
    _sanitize_and_inline_html,
    get_html_snapshot,
    get_snapshot_for_response,
    get_snapshot_info,
    has_html_snapshot,
    save_html_snapshot,
)

SOURCE = "https://site.example/dir/page.html"
HEADERS = {"Authorization": f"Bearer {settings.API_KEY}"}


def _clean(body: str, source: str = SOURCE) -> str:
    return _sanitize_and_inline_html(f"<!DOCTYPE html><html><head><title>t</title></head><body>{body}</body></html>", source)


def _page(body: str, source: str = SOURCE) -> BeautifulSoup:
    """The cleaned page without the banner OmniKeep adds itself."""
    soup = BeautifulSoup(_clean(body, source), "html.parser")
    soup.find(id="omnikeep-snapshot-banner").decompose()
    return soup


@pytest.mark.parametrize("body", [
    '<iframe srcdoc="&lt;script&gt;parent.stolen=localStorage.omnikeep_api_key&lt;/script&gt;"></iframe>',
    '<iframe src="javascript:alert(1)"></iframe>',
    '<iframe src="https://elsewhere.example/"></iframe>',
    '<frameset><frame src="https://elsewhere.example/"></frameset>',
    '<object data="movie.swf"><param name="autoplay" value="true"></object>',
    '<embed src="movie.swf" type="application/x-shockwave-flash">',
    '<applet code="A.class"></applet>',
    '<script src="https://elsewhere.example/a.js"></script>',
    '<svg><script>alert(1)</script></svg>',
    '<noscript><img src="https://elsewhere.example/pixel.gif"></noscript>',
])
def test_elements_that_run_or_load_content_are_removed(body):
    page = _page(body)
    assert not page.find(["iframe", "frame", "frameset", "object", "embed", "applet", "script", "noscript", "param"])
    for needle in ("srcdoc", "javascript:", "elsewhere.example", "movie.swf", "alert(1)"):
        assert needle not in str(page)


@pytest.mark.parametrize("attr, tag", [
    ("href", '<a {}>link text</a>'),
    ("xlink:href", '<svg><a {}><text>link text</text></a></svg>'),
    ("src", '<img alt="link text" {}>'),
    ("formaction", '<button {}>link text</button>'),
    ("action", '<form {}>link text</form>'),
    ("poster", '<video {}>link text</video>'),
    ("background", '<table {}><tr><td>link text</td></tr></table>'),
])
@pytest.mark.parametrize("value", [
    "javascript:alert(1)",
    "JavaScript:alert(1)",
    "  javascript:alert(1)",
    "java&#9;script:alert(1)",
    "java&#10;script&colon;alert(1)",
    "&#1;javascript:alert(1)",
    "vbscript:msgbox(1)",
    "data:text/html,<script>alert(1)</script>",
    "data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==",
    "DATA:Text/HTML,x",
])
def test_script_addresses_are_dropped_and_the_element_stays(attr, tag, value):
    page = _page(tag.format(f'{attr}="{value}"'))
    assert "link text" in str(page.body)
    assert not any(attr in element.attrs for element in page.body.find_all(True))
    assert "script" not in str(page.body).lower()


def test_ordinary_addresses_survive():
    page = _page('<a href="https://ok.example/x?a=1&amp;b=2">a</a><a href="/relative">b</a>'
                 '<a href="#top">c</a><a href="mailto:someone@example.com">d</a>'
                 '<img src="data:image/png;base64,AAAA"><img src="pic.png">')
    assert [a["href"] for a in page.find_all("a")] == [
        "https://ok.example/x?a=1&b=2", "/relative", "#top", "mailto:someone@example.com"]
    assert [img["src"] for img in page.find_all("img")] == ["data:image/png;base64,AAAA", "pic.png"]


def test_a_browser_sees_the_first_of_two_href_attributes():
    # This parser keeps the last one; whichever it is, only a harmless one may be written.
    page = _page('<a href="javascript:alert(1)" href="https://ok.example/">x</a>'
                 '<a href="https://ok.example/" href="javascript:alert(1)">y</a>')
    assert "javascript" not in str(page)
    assert [a.get("href") for a in page.find_all("a")] == ["https://ok.example/", None]


def test_event_handlers_and_ping_are_dropped():
    page = _page('<img src="pic.png" onerror="alert(1)"><body onload="alert(2)">'
                 '<a href="https://ok.example/" ping="https://tracker.example/p" onclick="alert(3)">x</a>'
                 '<svg><circle onbegin="alert(4)" r="1"></circle></svg><details ontoggle="alert(5)" open>d</details>')
    assert "alert(" not in str(page) and "tracker.example" not in str(page)
    assert page.find("img")["src"] == "pic.png" and page.find("a")["href"] == "https://ok.example/"


def test_meta_refresh_and_the_source_sites_policy_are_removed():
    cleaned = _sanitize_and_inline_html(
        '<html><head><meta http-equiv="Refresh" content="0;url=https://elsewhere.example/">'
        '<meta http-equiv="Content-Security-Policy" content="default-src \'self\'">'
        '<meta name="description" content="kept"></head><body>text</body></html>', SOURCE)
    soup = BeautifulSoup(cleaned, "html.parser")
    assert "elsewhere.example" not in cleaned and "default-src" not in cleaned
    assert soup.find("meta", attrs={"name": "description"})["content"] == "kept"
    policies = soup.find_all("meta", attrs={"http-equiv": "Content-Security-Policy"})
    assert [p["content"] for p in policies] == [
        "script-src 'none'; object-src 'none'; frame-src 'none'; form-action 'none'"]


def test_a_form_keeps_its_text_but_cannot_be_sent():
    page = _page('<form action="https://elsewhere.example/steal" method="post">'
                 '<label>搜尋這個網站</label><input name="q" value="typed">'
                 '<button formaction="https://elsewhere.example/other">送出</button></form>')
    assert not page.find("form")
    assert "搜尋這個網站" in page.get_text() and "送出" in page.get_text()
    assert page.find("input")["value"] == "typed"
    assert "steal" not in str(page)


def test_svg_animation_cannot_point_a_link_at_a_script():
    page = _page('<svg><a href="#ok"><animate attributeName="href" values="javascript:alert(1)"></animate>'
                 '<set attributeName="xlink:href" to="javascript:alert(2)"></set>'
                 '<animate attributeName="opacity" values="0;1" dur="1s"></animate><text>t</text></a></svg>')
    assert "javascript" not in str(page)
    assert [a["attributename"] for a in page.find_all("animate")] == ["opacity"]


@pytest.mark.parametrize("body", [
    # A browser reads <style> inside <svg> and <math> as markup; this parser reads it as CSS.
    "<svg><style><img src=x onerror=alert(1)></style></svg>",
    "<math><style><img src=x onerror=alert(1)></style></math>",
    "<svg><style></style><img src=x onerror=alert(1)></svg>",
    # A browser ends each of these at its first ">" and reads what follows as markup.
    "<![CDATA[><img src=x onerror=alert(1)>]]>",
    "<!--><img src=x onerror=alert(1)>-->",
    "<!---><img src=x onerror=alert(1)>-->",
    "<!-- a --!><img src=x onerror=alert(1)>-->",
    "<?php ?><img src=x onerror=alert(1)>?>",
    "<! doctype ><img src=x onerror=alert(1)>>",
    # Text only for a browser as well, as long as it is written back escaped.
    "<svg><title><img src=x onerror=alert(1)></title></svg>",
    "<textarea><img src=x onerror=alert(1)></textarea>",
    "<xmp><img src=x onerror=alert(1)></xmp>",
])
def test_nothing_a_browser_would_read_as_a_tag_carries_a_handler(body):
    # Gone, stripped of its handler, or no longer opening a tag: never written back as it came.
    assert "<img src=x onerror" not in _clean(body)


def test_css_keeps_working_after_it_is_made_inert():
    page = _page("<style>@media (width<600px){a>b{color:red}} i::after{content:\"<b\"}</style>"
                 "<style><!-- .old{color:blue} --></style>"
                 "<svg><style><![CDATA[ .st0{fill:#fff} ]]></style></svg>")
    first, old, exported = [style.get_text() for style in page.find_all("style")]
    assert first == '@media (width<600px){a>b{color:red}} i::after{content:"\\3c b"}'
    assert old.strip() == ".old{color:blue}"
    assert exported.strip() == ".st0{fill:#fff}"


def test_an_article_keeps_its_text_images_and_styles():
    cleaned = _sanitize_and_inline_html("""<!DOCTYPE html>
<html lang="zh-Hant"><head><meta charset="big5"><title>文章標題</title>
<link rel="stylesheet" href="/css/site.css"><style>.lead{font-weight:bold}</style></head>
<body class="article"><h1>文章標題</h1>
<p class="lead" style="color:#333">第一段 <a href="/next">下一篇</a></p>
<img src="/img/photo.jpg" alt="照片" srcset="/img/photo@2x.jpg 2x">
<table><tr><td>儲存格</td></tr></table>
<video controls src="/media/clip.mp4"></video>
</body></html>""", SOURCE)
    assert cleaned.startswith("<!DOCTYPE html>")
    soup = BeautifulSoup(cleaned, "html.parser")
    assert soup.html["lang"] == "zh-Hant" and soup.body["class"] == ["article"]
    assert soup.title.get_text() == "文章標題"
    assert soup.find("link", rel="stylesheet")["href"] == "/css/site.css"
    assert soup.find("style").get_text() == ".lead{font-weight:bold}"
    assert soup.find("p", class_="lead")["style"] == "color:#333"
    assert soup.find("a", href="/next").get_text() == "下一篇"
    img = soup.find("img")
    assert (img["src"], img["alt"], img["srcset"]) == ("/img/photo.jpg", "照片", "/img/photo@2x.jpg 2x")
    assert soup.find("td").get_text() == "儲存格"
    assert soup.find("video")["src"] == "/media/clip.mp4"
    assert "omnikeep-snapshot-banner" in cleaned


def test_charset_policy_and_base_lead_the_head():
    cleaned = _sanitize_and_inline_html(
        '<html><head><link rel="stylesheet" href="a.css"><base href="/sub/" target="_top">'
        '<meta charset="gbk"><title>t</title></head><body>x</body></html>', SOURCE)
    head = BeautifulSoup(cleaned, "html.parser").head
    lead = [child for child in head.children if child.name][:4]
    assert [tag.name for tag in lead] == ["meta", "meta", "base", "link"]
    assert lead[0].attrs == {"charset": "utf-8"}
    assert lead[1]["http-equiv"] == "Content-Security-Policy"
    # Relative to the source site, never to the address the snapshot is shown under.
    assert lead[2].attrs == {"href": "https://site.example/sub/"}
    assert len(BeautifulSoup(cleaned, "html.parser").find_all("base")) == 1


@pytest.mark.parametrize("raw", [
    "just text and <b>a fragment</b>",
    "stray text<html><head><title>t</title></head><body>late head</body></html>",
    "<p>before</p><html><head></head><body>x</body></html>",
])
def test_a_page_that_does_not_open_with_html_still_gets_a_real_head(raw):
    cleaned = _sanitize_and_inline_html(raw, SOURCE)
    assert cleaned.startswith('<!DOCTYPE html>\n<html><head><meta charset="utf-8"/><meta content="script-src')


@pytest.mark.parametrize("source", ["javascript:alert(1)", "data:text/html,<script>1</script>", "", "not a url"])
def test_only_a_web_address_becomes_the_base_or_the_banner_link(source):
    cleaned = _sanitize_and_inline_html("<html><head></head><body><p>x</p></body></html>", source)
    soup = BeautifulSoup(cleaned, "html.parser")
    assert not soup.find("base") and not soup.find("a")
    assert "<script" not in cleaned


# ── Serving ─────────────────────────────────────────────────────

def test_snapshot_response_forbids_scripts_and_sniffing(isolated_runtime):
    item_id = save_item({"url": "https://example.com/served", "title_l1": "Served", "summary_l1": "s"})
    save_html_snapshot(item_id, "<html><body><h1>Served page</h1></body></html>", "https://example.com/served")
    with TestClient(app) as client:
        assert client.get(f"/api/items/{item_id}/snapshot").status_code == 401
        res = client.get(f"/api/items/{item_id}/snapshot", headers=HEADERS)
    assert res.status_code == 200 and "Served page" in res.text
    assert res.headers["content-type"].startswith("text/html")
    policy = [part.strip() for part in res.headers["content-security-policy"].split(";")]
    assert "sandbox" in policy and "default-src 'none'" in policy
    assert "allow-scripts" not in res.headers["content-security-policy"]
    assert "allow-same-origin" not in res.headers["content-security-policy"]
    assert res.headers["x-content-type-options"] == "nosniff"
    assert res.headers["cache-control"] == "no-store"


def test_headers_also_cover_snapshots_saved_before_the_cleaning(isolated_runtime):
    # What an older version wrote to disk is served as it is; the headers are what holds.
    old = '<html><body><iframe srcdoc="<script>alert(1)</script>"></iframe></body></html>'
    (isolated_runtime / "snapshots").mkdir(exist_ok=True)
    (isolated_runtime / "snapshots" / "olditem01.html").write_text(old, encoding="utf-8")
    content, headers = get_snapshot_for_response("olditem01")
    assert content == old
    assert headers == SNAPSHOT_HEADERS and headers is not SNAPSHOT_HEADERS
    assert get_snapshot_for_response("missing01") is None


# ── Item ids are file names ─────────────────────────────────────

BAD_IDS = ["..\\..\\secret", "../secret", "..\\secret", "..", ".", "a/b", "a\\b", "C:secret", "secret.html",
           "a b", "a\x00b", "", "x" * 101, "名字", "a\n"]


@pytest.mark.parametrize("bad", BAD_IDS)
def test_an_id_that_is_not_a_plain_name_reads_and_writes_nothing(isolated_runtime, bad):
    outside = isolated_runtime / "secret.html"
    outside.write_text("<html>outside the snapshot folder</html>", encoding="utf-8")
    (isolated_runtime / "snapshots").mkdir(exist_ok=True)
    before = sorted(isolated_runtime.rglob("*.html"))

    assert get_html_snapshot(bad) is None
    assert get_snapshot_for_response(bad) is None
    assert has_html_snapshot(bad) is False
    assert get_snapshot_info(bad) == {"has_snapshot": False, "size_bytes": 0}
    assert save_html_snapshot(bad, "<html><body>x</body></html>", SOURCE) is None

    assert sorted(isolated_runtime.rglob("*.html")) == before
    assert outside.read_text(encoding="utf-8") == "<html>outside the snapshot folder</html>"


@pytest.mark.parametrize("path", ["..%5C..%5Csecret", "..%5Csecret", "%2E%2E%5Csecret", "..%2Fsecret", "secret.html"])
def test_the_api_cannot_be_walked_out_of_the_snapshot_folder(isolated_runtime, path):
    (isolated_runtime / "secret.html").write_text("<html>outside the snapshot folder</html>", encoding="utf-8")
    (isolated_runtime / "snapshots").mkdir(exist_ok=True)
    with TestClient(app) as client:
        res = client.get(f"/api/items/{path}/snapshot", headers=HEADERS)
        status = client.get(f"/api/items/{path}/snapshot/status", headers=HEADERS)
    assert res.status_code == 404 and "outside the snapshot folder" not in res.text
    assert status.status_code == 404 or status.json() == {"has_snapshot": False, "size_bytes": 0}


def test_snapshot_status_does_not_tell_where_the_file_is(isolated_runtime):
    item_id = save_item({"url": "https://example.com/where", "title_l1": "Where", "summary_l1": "s"})
    save_html_snapshot(item_id, "<html><body>x</body></html>", "https://example.com/where")
    info = get_snapshot_info(item_id)
    assert info["has_snapshot"] is True and info["size_bytes"] > 0
    assert set(info) == {"has_snapshot", "size_bytes", "mtime"}
    with TestClient(app) as client:
        body = client.get(f"/api/items/{item_id}/snapshot/status", headers=HEADERS).text
    assert str(isolated_runtime) not in body and "snapshots" not in body
