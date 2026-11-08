import json
import logging
import re
import uuid
import asyncio
from typing import Dict, Any, Optional
from app.database import (
    get_all_categories,
    get_item_by_id,
    save_item,
    normalize_canonical_url,
    find_item_by_canonical_or_url,
    save_citation
)
from app.parsers import (
    is_youtube_url,
    is_youtube_shorts_url,
    fetch_youtube_metadata,
    parse_web_page,
    is_bilibili_url,
    parse_bilibili_video
)
from app.parsers.blocked import detect_blocked_page, is_error_title, reason_text
from app.parsers.reel import is_video_reel_url, parse_video_reel
from app.parsers.transcript import TRANSCRIPT_MISSING, get_transcript
from app.parsers.threads import is_threads_url, parse_threads_page
from app.providers import get_primary_provider, get_gemini_provider, has_video_provider
from app.config import settings
from app.schemas.intelligence import generate_structured_intelligence

logger = logging.getLogger("omnikeep.pipeline")

_ANALYSIS_PROMPT_TEMPLATE = """你是一位客觀、專業的技術情報與全領域知識提煉官，兼具使用者的專屬 AI 參謀角色。
<<BACKGROUND_ANCHOR>>你的任務是將輸入內容以「事實優先（Fact-first）」原則消化，輸出冷靜、高密度、直擊本質的結構化摘要（L1 核心提要 + L2 深度剖析）。

嚴格規範：
1. 一律使用繁體中文（台灣習慣用語）。絕對嚴禁使用任何 LaTeX 數學語法（嚴禁 $ 或 KaTeX 符號，數學與關係符號一律採純文字，如「!=」、「約」、「>=」）。
2. 絕對禁止廢話、客套話、自言自語與說教元敘事：
   - 嚴禁「作者介紹了/分享了/指出」、「本篇主要在於」、「推廣某工具」等旁白廢話。
   - 絕對禁止出現「此內容為純娛樂」、「缺乏實質工程細節」、「無技術負載」、「無法進行技術深析」等自言自語的說教與價值批判。使用者非常清楚內容性質，無需 AI 評判。
3. 雙軌自適應提煉（依內容本體動態適配）：
   A. 專業工程與架構內容（AI、代碼、開源工具、硬體、量化金融、技術架構）：
      - L1 summary_l1：首句直陳該專案/系統是什麼、解決何種工程痛點；次句陳述核心機制、量化規格或適用情境（80-120字）。
      - L2 deep_analysis：Markdown 格式，結構化條列：
        * ## 系統架構與關鍵技術規格（核心機制、架構參數、數據規模與技術邊界）。
        * 若涉及 AI 模型（LLM / VLM / 視覺模型 / 擴散模型 / 語音模型）：
          強制增設「<<HARDWARE_HEADING>>」：
          - **顯存需求試算**：精確標註參數量級、FP16 顯存佔用（純文字如「約 6.0 GB」）、INT4/8-bit 量化佔用；<<HARDWARE_VERDICT>>
          - **最小可執行驗證代碼（30秒上手）**：提供包含 pip 依賴與 3-5 行開箱即用的 Python / Transformers / Ollama 最小推理代碼段（指定 device_map="cuda"），複製即可跑通。
   B. 生活文化、迷因語錄與娛樂內容（幹話短劇、脫口秀、金句名言、美食旅遊、泛生活）：
      - L1 summary_l1：直陳其段子核心包袱、諷刺邏輯或生活精要，並串聯最具代表性的金句（80-120字）。
      - L2 deep_analysis：Markdown 格式，結構化整理「## 經典金句與台詞原話節錄」（務必完整收錄口播轉錄中的精彩原話）與「## 荒謬/反諷邏輯拆解」。
   C. 個人化與在地決策延伸（在 deep_analysis 末尾增設專屬視角）：
      - 若內容涉及特定地域生態（如中國特有生態/政策/潤學/牆內套利、歐美特有 H-1B/401K/GDPR）：
        強制在 deep_analysis 增設「### 🇹🇼 台灣在地視角與延伸對照」：
        * 分析客觀條件與痛點差異（如免簽優勢、資訊斷層落差、外匯法規）。
        * 提供台灣工程師出海、遠距或套利的務實替代路徑。
      - 若內容為工程架構、技術工具或量化商業策略：
        增設「### 💡 專屬決策評估與落地啟發」：
        * <<BACKGROUND_ADVICE>>
4. 針對純宣傳或低資訊量貼文（既無技術規格亦無實質台詞）：若文字極度殘缺，如實記錄發布者之主要主張，嚴禁無中生有捏造數據。
5. 嚴格輸出合法 JSON 物件，格式如下：
{
  "category": "從候選清單精選1個最適分類（若無合適填 Inbox）",
  "title_l1": "直擊本質或名言主題的專業中文標題（25字以內，嚴禁使用「無法解析/無效內容/未公開」等敷衍命名）",
  "summary_l1": "L1 核心提要（80-120字，依上述雙軌規範直陳本體，嚴禁說教）",
  "tech_tags": ["核心標籤1", "核心標籤2", "核心標籤3"],
  "deep_analysis": "L2 深度剖析（Markdown 格式，工程內容列架構規格，生活內容列金句原話與邏輯拆解）",
  "is_composite": false,
  "sub_entities": [
    {
      "name": "開源專案、AI 模型、工具、GitHub 倉庫或知識庫名稱（若無提及填空陣列 []）",
      "canonical_url": "標準 GitHub 倉庫、Hugging Face 模型頁或官方網站網址（若未知填空字串）",
      "reason": "文中對此專案/模型的核心評價或關鍵亮點（1句話）"
    }
  ]
}

注意事項：
- 若為多專案/多工具推薦或盤點彙總，is_composite 必須設為 true，並於 sub_entities 完整抽離所有項目與標準網址。
- 若內容為單一主題或貼文提及特定開源專案/GitHub 倉庫，is_composite 設為 false，並於 sub_entities 記錄該專案名稱（若完全未提及任何開源專案或軟體工具，sub_entities 設為空陣列 []）。"""


# Extra rule appended to the analysis prompt per the ANALYSIS_DEPTH setting; "standard" leaves it unchanged.
ANALYSIS_DEPTH_RULES = {
    "standard": "",
    "concise": ("- 分析深度（使用者設定：重點摘要）：deep_analysis 只保留 3 到 5 個最重要的條列，每條一到兩句；"
                "不附最小可執行驗證代碼，硬體需求只寫一行結論；落地啟發最多 1 點。"
                "這一條優先於上面對 deep_analysis 長度與段落的要求。"),
    "technical": ("- 分析深度（使用者設定：技術細節）：deep_analysis 盡量完整列出架構、關鍵參數與數據規模、"
                  "限制與已知問題、與同類方案的差異；原文有的規格不要為了精簡而省略。"),
    "actionable": ("- 分析深度（使用者設定：含落地建議）：工程架構、技術工具或策略類內容，"
                   "「### 💡 專屬決策評估與落地啟發」擴充為 3 點，每點寫明要做什麼、怎麼驗證是否有效。"),
}


# Marks an analysis made without seeing the content (survey 2026-10-25, gap P1): the
# reader must not mistake a guess from the title for a summary of the video.
METADATA_ONLY_TAG = "（只看了標題與說明）"


def metadata_only_note(description: str, no_speech: bool = False) -> str:
    source = "影片標題與說明欄" if (description or "").strip() else "影片標題（沒有說明欄）"
    if no_speech:
        return f"⚠️ 影片沒有字幕，音訊裡也沒有辨識到口語內容，這篇分析只根據{source}。重點請回原影片確認。"
    return f"⚠️ 證據不足：這篇分析只根據{source}，沒有看到影片內容或逐字稿。重點請回原影片確認。"


# Marks an item whose fetch got only an error / anti-bot page (or nothing) and that had no
# title or description to go on either: no AI analysis was made, so nothing could be invented.
FETCH_FAILED_TAG = "（擷取失敗）"

# Kinds whose content_raw is text scraped from the page, so may be the site's error page.
BLOCK_CHECKED_KINDS = ("web", "threads")


def blocked_page_note(reason_line: str, source: str) -> str:
    return f"⚠️ 證據不足：{reason_line}，沒有看到原文。這篇分析只根據{source}。重點請回原網頁確認。"


def fetch_failed_note(reason_line: str) -> str:
    return (f"⚠️ 擷取失敗：{reason_line}，沒有看到原文，也沒有標題或描述可以分析，所以沒有做 AI 分析。"
            "OmniKeep 會在 7 天內自動重抓，抓到原文就補做分析；也可以從瀏覽器用書籤小工具重新收藏。")


def _title_from_url(url: str) -> str:
    from urllib.parse import urlparse
    parts = urlparse(url)
    return f"{parts.netloc}{parts.path}".rstrip("/")[:80] or url[:80]


def video_failed_note(reason_line: str) -> str:
    return (f"⚠️ 擷取失敗：{reason_line}。只憑標題和說明欄猜不出影片講了什麼，所以沒有做 AI 分析。"
            "OmniKeep 會在 7 天內自動重抓，讀到逐字稿就補做分析。")


def fetch_failed_fields(url: str, reason_line: str, title: str = "", video: bool = False) -> Dict[str, Any]:
    """Title, summary, deep analysis and tags of an item kept without any AI analysis."""
    if video:
        return {"title_l1": title or _title_from_url(url),
                "summary_l1": f"{FETCH_FAILED_TAG}{reason_line}，稍後會自動重抓。",
                "deep_analysis": f"> {video_failed_note(reason_line)}",
                "tech_tags": []}
    return {"title_l1": _title_from_url(url),
            "summary_l1": f"{FETCH_FAILED_TAG}{reason_line}，沒有看到原文，稍後會自動重抓。",
            "deep_analysis": f"> {fetch_failed_note(reason_line)}",
            "tech_tags": []}


def hardware_heading() -> str:
    """Heading of the AI-model hardware section; names the machine only if the owner entered it."""
    hardware = (settings.LOCAL_HARDWARE or "").strip()
    if hardware:
        return f"### 🖥️ 本機硬體適配與快速上手評估（{hardware}）"
    return "### 🖥️ 硬體需求與快速上手評估"


def analysis_system_prompt() -> str:
    """System prompt for item analysis, personalised from the in-app settings.

    USER_BACKGROUND and LOCAL_HARDWARE are read on every call, so a value saved
    in the app applies to the next analysis without a restart. Left empty, the
    prompt stays neutral instead of assuming who the owner is.
    """
    background = (settings.USER_BACKGROUND or "").strip().rstrip("。.")
    hardware = (settings.LOCAL_HARDWARE or "").strip()
    if background:
        anchor = f"使用者背景錨點：{background}。\n"
        advice = "結合上述使用者背景，給出 1-2 點具體技術借鏡或落地改進建議。"
    else:
        anchor = ""
        advice = "給出 1-2 點具體技術借鏡或落地改進建議；若附有使用者興趣設定檔，優先貼合其關注領域。"
    if hardware:
        verdict = f"明確標註在本機（{hardware}）上的運行結論（例如「✅ 可全精度運行」或「⚠️ 建議採 4-bit 量化」）。"
    else:
        verdict = ("分別標註 8 GB、16 GB、24 GB 顯存的運行結論"
                   "（例如「✅ 16 GB 可全精度運行」或「⚠️ 8 GB 建議採 4-bit 量化」）。")
    parts = {
        "BACKGROUND_ANCHOR": anchor,
        "BACKGROUND_ADVICE": advice,
        "HARDWARE_HEADING": hardware_heading(),
        "HARDWARE_VERDICT": verdict,
    }
    # One pass, so text the owner typed is never scanned for placeholders.
    prompt = re.sub(r"<<([A-Z_]+)>>", lambda m: parts[m.group(1)], _ANALYSIS_PROMPT_TEMPLATE)
    depth_rule = ANALYSIS_DEPTH_RULES.get((settings.ANALYSIS_DEPTH or "").strip(), "")
    return f"{prompt}\n{depth_rule}" if depth_rule else prompt


def interest_profile_block() -> str:
    """User-written free-text interest profile woven into LLM prompts.

    Cruxwire/Brain pattern: a profile in the prompt expresses intent far
    better than tag weights alone. Kept phrasing generic so digest
    generation reuses it. Local DB read only — never an extra cloud call.
    """
    try:
        from app.database import get_interest_profile
        profile = get_interest_profile().strip()
    except Exception:
        return ""
    if not profile:
        return ""
    return (
        "\n\n=== 使用者興趣設定檔（挑選、分類與取捨請參考） ===\n"
        f"{profile[:2000]}\n=== 設定檔結束 ==="
    )

async def _analyze_with_guardrails(provider, prompt: str, system_prompt: Optional[str] = None) -> Dict[str, Any]:
    """Execute LLM generation protected by strict Pydantic contract & reflection self-healing"""
    return await generate_structured_intelligence(provider, prompt, system_prompt or analysis_system_prompt())

def is_pure_url(text: str) -> bool:
    clean = text.strip()
    if "\n" in clean or "\r" in clean or " " in clean:
        return False
    return clean.startswith("http://") or clean.startswith("https://")

def extract_target_url(text: str) -> Optional[str]:
    clean = text.strip()
    if is_pure_url(clean):
        return clean
    # Detect single URL within mobile share text snippets
    urls = re.findall(r'https?://[^\s<>"]+', clean)
    if len(urls) == 1 and len(clean) < 500:
        return urls[0]
    return None

async def _spawn_child_entity_background(source_parent_id: str, cit_id: str, target_name: str, target_url: str, mention_context: str):
    """Background worker to ingest an unpacked sub-project into its own standalone entry and link citation"""
    try:
        clean_url = normalize_canonical_url(target_url)
        # Check again if already exists
        existing = find_item_by_canonical_or_url(clean_url)
        if existing:
            save_citation({
                "id": cit_id,
                "source_parent_id": source_parent_id,
                "target_item_id": existing["id"],
                "target_canonical_url": clean_url,
                "target_name": target_name or existing.get("title_l1", ""),
                "mention_context": mention_context
            })
            return

        child_item = await run_pipeline(clean_url, manual_category="Github" if "github.com" in clean_url else None, is_sub_task=True)
        if child_item and "id" in child_item:
            save_citation({
                "id": cit_id,
                "source_parent_id": source_parent_id,
                "target_item_id": child_item["id"],
                "target_canonical_url": clean_url,
                "target_name": target_name or child_item.get("title_l1", ""),
                "mention_context": mention_context
            })
    except Exception as e:
        logger.warning(f"[Entity Fan-out] Background spawn failed for {target_url}: {e}")

async def parse_url(url: str, page_title: str = "", page_description: str = "",
                    light: bool = False) -> Dict[str, Any]:
    """Fetch and parse one URL: no AI call, nothing saved.

    run_pipeline() analyzes what this returns; the setup tools (app.setup_flow)
    use it on its own to show a link's title and text. "kind" says which parser
    ran and so which analysis prompt fits. light=True keeps short videos to their
    metadata: the full path downloads the clip and calls a vision model and STT.
    """
    from app.network import validate_url
    validate_url(url)
    parsed: Dict[str, Any] = {
        "url": url, "content_raw": "", "cover_image": "", "author": "", "title": "",
        "original_title": "", "description": "", "raw_html": "", "fallback_summary": "",
        "http_status": None, "transcript_status": "", "transcript_reason": "",
    }
    short_video = is_youtube_shorts_url(url) or is_video_reel_url(url)
    if short_video and not light:
        reel_data = await parse_video_reel(url)
        parsed.update(kind="reel_vision", source_type="youtube" if is_youtube_url(url) else "reel",
                      content_raw=reel_data.get("content_raw", ""),
                      cover_image=reel_data.get("cover_image", ""),
                      author=reel_data.get("author", ""),
                      title=reel_data.get("title", "短影音情報"),
                      transcript_status=reel_data.get("transcript_status", ""),
                      transcript_reason=reel_data.get("transcript_reason", ""))
    elif is_youtube_url(url):
        meta = await fetch_youtube_metadata(url)
        desc_text = meta.get("description", "").strip()
        desc_part = f"\n\n## 影片說明欄\n{desc_text}" if desc_text else ""
        # light (setup previews) stays on the page metadata; the full path reads what is said.
        transcript = None if light else await get_transcript(url, meta)
        transcript_part = f"\n\n{transcript.section()}" if transcript else ""
        parsed.update(kind="youtube", source_type="youtube",
                      transcript_status=transcript.status if transcript else "",
                      transcript_reason=transcript.reason if transcript else "",
                      content_raw=f"# {meta['title']}\n\n頻道: {meta['author']}\nURL: {url}{desc_part}{transcript_part}",
                      cover_image=meta.get("cover_image", ""),
                      author=meta.get("author", ""),
                      title=meta.get("title", "未命名項目"),
                      description=desc_text,
                      raw_html=meta.get("raw_html") or "")
    elif is_bilibili_url(url):
        bili_data = await parse_bilibili_video(url)
        parsed.update(kind="bilibili", source_type="bilibili",
                      content_raw=bili_data.get("content_raw", ""),
                      cover_image=bili_data.get("cover_image", ""),
                      author=bili_data.get("author", ""),
                      title=bili_data.get("title", "Bilibili 影片"))
    elif is_threads_url(url):
        threads_data = await parse_threads_page(url)
        parsed.update(kind="threads", source_type="threads",
                      url=threads_data.get("url") or url,
                      content_raw=threads_data.get("content_raw", ""),
                      cover_image=threads_data.get("cover_image", ""),
                      author=threads_data.get("author", ""),
                      title=threads_data.get("title", "Threads 貼文"),
                      raw_html=threads_data.get("raw_html", ""))
    else:
        # Standard Web Page / GitHub / Article (and, when light, a reel's page metadata)
        page_data = await parse_web_page(url)
        # The bookmarklet sends what the user's browser shows. Prefer it: the server's
        # own fetch may only reach a login wall ("未知標題").
        parsed.update(kind="web", source_type="reel" if short_video else "web",
                      content_raw=page_data.get("content_raw", ""),
                      cover_image=page_data.get("cover_image", ""),
                      author=page_data.get("author", ""),
                      title=page_title or page_data.get("title", "未命名項目"),
                      original_title=page_data.get("title", ""),
                      fallback_summary=page_description,
                      raw_html=page_data.get("raw_html") or (page_data.get("meta") or {}).get("raw_html") or "",
                      http_status=page_data.get("http_status"))
    return parsed


async def run_pipeline(content_input: str, manual_category: Optional[str] = None,
                       is_sub_task: bool = False, origin: str = "manual",
                       page_title: str = "", page_description: str = "") -> Dict[str, Any]:
    # 1. Fetch available categories
    cat_rows = get_all_categories()
    category_names = [c["name"] for c in cat_rows]
    cat_list_str = ", ".join(category_names)
    clean_input = content_input.strip()
    raw_html = ""
    fallback_summary = "已儲存內容，無詳細摘要。"
    evidence_note = ""  # set when the analysis could not see the content itself
    blocked = None  # REASONS key when the fetch got the site's error / anti-bot page
    fetch_failed = False  # blocked and nothing else to analyse: no AI call at all
    reason_line = ""

    user_note = ""
    if "#note=" in clean_input:
        from urllib.parse import unquote
        parts = clean_input.split("#note=", 1)
        clean_input = parts[0]
        user_note = unquote(parts[1]).strip()

    # 2. Route by input type (Pure URL / Mobile Share Snippet vs Text Note)
    detected_url = extract_target_url(clean_input)
    if detected_url:
        parsed = await parse_url(detected_url, page_title=page_title, page_description=page_description)
        kind = parsed["kind"]
        url = parsed["url"]
        source_type = parsed["source_type"]
        content_raw = parsed["content_raw"]
        cover_image = parsed["cover_image"]
        author = parsed["author"]
        default_title = parsed["title"]
        raw_html = parsed["raw_html"]
        fallback_summary = parsed["fallback_summary"] or fallback_summary
        if kind in BLOCK_CHECKED_KINDS:
            blocked = detect_blocked_page(content_raw, parsed.get("http_status"))

        if blocked:
            # Never analyse an error page as if it were the article (2026-11-07: X's
            # "enable JavaScript" page came back as a confident, invented deep analysis).
            reason_line = reason_text(blocked, parsed.get("http_status"))
            titles = []
            for candidate in (page_title, parsed["original_title"] or default_title):
                candidate = (candidate or "").strip()
                if candidate and candidate not in titles and not is_error_title(candidate):
                    titles.append(candidate)
            description = (page_description or "").strip()
            has_metadata = bool(titles or description or user_note)
            logger.warning("[Pipeline] %s: %s (%s)", url, reason_line,
                           "analysing title/description only" if has_metadata else "no AI analysis")
            if has_metadata:
                seen = "、".join(label for label, value in (("網頁標題", titles), ("描述", description),
                                                            ("你的備註", user_note)) if value)
                evidence_note = blocked_page_note(reason_line, seen)
                default_title = titles[0] if titles else _title_from_url(url)
                note_line = f"\n使用者備註：{user_note[:2000]}" if user_note else ""
                primary = get_primary_provider()
                prompt = f"""以下網址的內文沒有擷取到：{reason_line}，伺服器拿到的不是原文。
只能根據下面的標題與描述分析。標題與描述沒寫到的細節（數據、規格、架構、程式碼、人名、時間）一律不要補，也不要用你對這個網站或專案的既有印象延伸；不要分析錯誤頁本身或網站的擋爬機制。資訊不夠就把 summary_l1 與 deep_analysis 寫短，只條列標題與描述中明確出現的資訊。
網址：{url}
標題：{" / ".join(titles) or "（沒有標題）"}
描述：{description[:3000] or "（沒有描述）"}{note_line}

候選分類清單：[{cat_list_str}]

請依據規範輸出結構化 JSON；sub_entities 只列標題或描述中明確寫出的專案，沒有就填 []。"""
                prompt += interest_profile_block()
                ai_result = await _analyze_with_guardrails(primary, prompt)
            else:
                fetch_failed = True
                ai_result = {}

        elif kind == "reel_vision" and parsed.get("transcript_status") == "failed":
            # The clip was not downloaded, only the post's text was: same rule as a YouTube video.
            reason_line = parsed.get("transcript_reason") or "影片沒有下載到"
            logger.warning("[Pipeline] %s: %s; no AI analysis", url, reason_line)
            fetch_failed = True
            ai_result = {}

        elif kind == "reel_vision":
            # Short Video Reel (YouTube Shorts / Facebook / Instagram Reels with Vision OCR + Whisper STT)
            primary = get_primary_provider()
            prompt = f"""請深度分析以下短影音情報與畫面視覺 OCR 辨識結果：
影片標題：{default_title}
作者/發布者：{author}
URL：{url}

候選分類清單：[{cat_list_str}]

=== 短影音內容與影格 OCR 辨識 ===
{content_raw[:15000]}
=== 內容結束 ===

請依據規範輸出結構化 JSON：
- 若影片畫面（如 Hugging Face Model Card 截圖、開源卡片、論文）或說明中有提及具體開源專案/AI 模型/工具/GitHub 倉庫（如萬物定位大模型 LocateAnything 等），請務必將 is_composite 設為對應值，並於 sub_entities 完整抽離所有專案/模型（支援 Hugging Face 或 GitHub 標準網址）！
- 務必在 deep_analysis 中完整收錄其系統架構、規格參數、核心機制（如 Parallel Box Decoding 等），若涉及 AI 模型，強制附上「{hardware_heading()}」包含顯存試算與 3 行最小可執行驗證代碼！
- 嚴禁批判內容缺乏技術價值，請專注於內容本體的精華提煉。"""
            prompt += interest_profile_block()
            ai_result = await _analyze_with_guardrails(primary, prompt)

        elif kind == "youtube":
            desc_text = parsed["description"]
            status = parsed.get("transcript_status")
            ai_result = None
            # If the video slot has a Gemini connection, use native YouTube video analysis
            if has_video_provider():
                try:
                    gemini = get_gemini_provider()
                    prompt = f"""請觀看並深度分析此 YouTube 影片：{url}
影片標題：{default_title}
頻道：{author}

候選分類清單：[{cat_list_str}]
請分析影片內容，直接輸出結構化 JSON。"""
                    prompt += interest_profile_block()
                    ai_result = await gemini.analyze_youtube(url, prompt)
                except Exception as e:
                    logger.warning("YouTube video analysis failed (%s); using the transcript instead", e)
                    ai_result = None
            if ai_result is not None:
                pass
            elif status == "failed":
                # Never pass a guess from the title and description off as the video's content
                # (2026-11-08: 41 of 44 saved videos were analysed that way). Refetch tries again.
                reason_line = f"影片逐字稿沒有讀到（{parsed.get('transcript_reason') or '原因不明'}）"
                logger.warning("[Pipeline] %s: %s; no AI analysis", url, reason_line)
                fetch_failed = True
                ai_result = {}
            elif status == "ok":
                primary = get_primary_provider()
                prompt = f"""深度分析以下 YouTube 影片，依據逐字稿（影片實際說的內容）輸出專業中文結構化總結、技術標籤與核心洞見：
影片標題：{default_title}
頻道：{author}
URL：{url}

候選分類清單：[{cat_list_str}]

=== 影片說明欄與逐字稿 ===
{content_raw[:30000]}
=== 內容結束 ===

逐字稿可能有語音辨識的錯字，依上下文判讀；逐字稿沒說到的細節不要補。"""
                prompt += interest_profile_block()
                ai_result = await _analyze_with_guardrails(primary, prompt)
            else:
                # "no_speech": nothing is said, so the title and description are all there is.
                evidence_note = metadata_only_note(desc_text, no_speech=status == "no_speech")
                primary = get_primary_provider()
                prompt = f"""分析此 YouTube 影片資訊：
標題：{default_title}
頻道：{author}
URL：{url}

影片說明：
{desc_text[:5000] if desc_text else '(無說明欄)'}

候選分類清單：[{cat_list_str}]"""
                prompt += interest_profile_block()
                ai_result = await _analyze_with_guardrails(primary, prompt)

        elif kind == "bilibili":
            primary = get_primary_provider()
            prompt = f"""深度分析以下 Bilibili 影片內容，輸出專業中文結構化總結、技術標籤與核心洞見：
影片標題：{default_title}
UP主：{author}
URL：{url}

可選分類清單：[{cat_list_str}]

影片完整資訊（包含簡介與逐字稿）：
{content_raw[:12000]}
"""
            prompt += interest_profile_block()
            ai_result = await _analyze_with_guardrails(primary, prompt)

        elif kind == "reel":
            # Short Video Reel (Facebook / Instagram Reels with Vision OCR)
            primary = get_primary_provider()
            prompt = f"""請深度分析以下短影音情報與畫面視覺 OCR 辨識結果：
影片標題：{default_title}
作者/發布者：{author}
URL：{url}

候選分類清單：[{cat_list_str}]

=== 短影音內容與影格 OCR 辨識 ===
{content_raw[:15000]}
=== 內容結束 ===

請依據規範輸出結構化 JSON：
- 若影片畫面中有推薦多個開源專案/工具，請務必將 is_composite 設為 true，並於 sub_entities 完整抽離所有專案！
- 若影片為個人口播、生活短劇或迷因幹話語錄，請務必在 deep_analysis 中完整收錄其精華台詞原話！
- 嚴禁評判內容缺乏技術價值，請專注於內容本體的精華提煉。"""
            prompt += interest_profile_block()
            ai_result = await _analyze_with_guardrails(primary, prompt)

        elif kind == "threads":
            # Meta Threads Post (Threads.net / Threads.com)
            primary = get_primary_provider()
            prompt = f"""請深度分析以下 Threads 社群情報與討論內容：
貼文網址：{url}
發布作者：{author}
貼文主題：{default_title}

候選分類清單：[{cat_list_str}]

=== 貼文完整內容與討論串 ===
{content_raw[:12000]}
=== 內容結束 ===

請依據規範輸出結構化 JSON。若貼文中提及多個開源專案、工具庫、網站或架構，請務必將 is_composite 設為 true，並於 sub_entities 完整抽離所有專案！"""
            prompt += interest_profile_block()
            ai_result = await _analyze_with_guardrails(primary, prompt)

        else:
            # Standard Web Page / GitHub / Article
            browser_view = "".join(f"\n瀏覽器看到的{label}：{value}"
                                   for label, value in (("標題", page_title), ("描述", page_description)) if value)

            primary = get_primary_provider()
            prompt = f"""請深度分析以下網頁/文章內容：
網址：{url}
原始標題：{parsed["original_title"]}{browser_view}

候選分類清單：[{cat_list_str}]

=== 內容節錄 ===
{content_raw[:12000]}
=== 內容結束 ===

請依據規範輸出結構化 JSON。"""
            prompt += interest_profile_block()
            ai_result = await _analyze_with_guardrails(primary, prompt)

    else:
        # Free-form Text Snippet / Paragraph / Thought Note
        source_type = "snippet"
        content_raw = clean_input
        cover_image = ""
        
        # Extract embedded URLs if any
        embedded_urls = re.findall(r'https?://[^\s)\]">]+', clean_input)
        item_id_seed = uuid.uuid4().hex[:10]
        if embedded_urls:
            primary_url = embedded_urls[0]
            url = f"{primary_url}#snippet-{item_id_seed}"
            author = f"節錄引文 ({primary_url})"
        else:
            url = f"note://{item_id_seed}"
            author = "筆記摘錄"

        first_line = clean_input.splitlines()[0].strip() if clean_input.splitlines() else "隨手筆記"
        default_title = first_line[:30]

        primary = get_primary_provider()
        prompt = f"""請深度分析以下使用者記錄的技術段落、筆記或片段資訊：
候選分類清單：[{cat_list_str}]

=== 筆記/段落內容 ===
{content_raw[:12000]}
=== 內容結束 ===

請精準提煉這段內容的技術價值，依據規範輸出結構化 JSON。"""
        prompt += interest_profile_block()
        ai_result = await _analyze_with_guardrails(primary, prompt)

    # Extract fields with safe defaults
    category_name = manual_category or ai_result.get("category", "Inbox")
    if category_name not in category_names and category_name != "Inbox":
        category_name = "Inbox"

    title_l1 = ai_result.get("title_l1") or default_title
    summary_l1 = ai_result.get("summary_l1") or fallback_summary
    tech_tags = ai_result.get("tech_tags", [])
    if isinstance(tech_tags, str):
        tech_tags = [t.strip() for t in tech_tags.split(",") if t.strip()]

    deep_analysis = ai_result.get("deep_analysis", "")
    if fetch_failed:
        video = parsed.get("transcript_status") == "failed"  # parsed: fetch_failed is only set for a URL
        failed = fetch_failed_fields(url, reason_line, title=default_title if video else "", video=video)
        title_l1, summary_l1, deep_analysis = failed["title_l1"], failed["summary_l1"], failed["deep_analysis"]
    elif evidence_note:
        summary_l1 = f"{METADATA_ONLY_TAG}{summary_l1}"
        deep_analysis = f"> {evidence_note}\n\n{deep_analysis}" if deep_analysis else f"> {evidence_note}"

    if user_note and not content_raw.startswith("## 使用者隨手筆記"):
        content_raw = f"## 使用者隨手筆記/備忘\n{user_note}\n\n" + content_raw

    item_record = {
        "url": url,
        "source_type": source_type,
        "category_name": category_name,
        "title_l1": title_l1,
        "summary_l1": summary_l1,
        "tech_tags": tech_tags,
        "deep_analysis": deep_analysis,
        "content_raw": content_raw,
        "author": author,
        "cover_image": cover_image,
        "origin": origin,
    }

    # 2. Hard Rules Engine (Deterministic automation: Karakeep pattern)
    try:
        from app.rules import apply_rules_to_item
        item_record = apply_rules_to_item(item_record)
    except Exception as e:
        logger.warning(f"[Pipeline] Rules engine evaluation failed: {e}")

    item_id = save_item(item_record)
    item_record["id"] = item_id

    # 2.5 Monolith HTML Snapshot & Vector Embedding (B-full)
    if raw_html and not blocked:  # a snapshot of the error page would only mislead
        try:
            from app.snapshot import save_html_snapshot
            save_html_snapshot(item_id, raw_html, url)
        except Exception as e:
            logger.warning(f"[Pipeline] Failed to save HTML snapshot for {item_id}: {e}")

    try:
        from app.vector import generate_embedding_with_model, item_embedding_text, store_item_embedding
        # From the item as stored (after the rules engine), the same text a rebuild uses.
        embed_text = item_embedding_text(get_item_by_id(item_id) or item_record)
        vec, embed_model = await generate_embedding_with_model(embed_text)
        store_item_embedding(item_id, vec, model=embed_model)
    except Exception as e:
        logger.warning(f"[Pipeline] Failed to store vector embedding for {item_id}: {e}")

    # 2.8 Mentioned Open-Source Tool Resolution (Automated Entity Linking for professional domain)
    LIFE_ENTERTAINMENT_CATEGORIES = {"生活娛樂", "迷因語錄", "美食", "旅遊", "隔離區"}
    has_github_mention = "github" in (content_raw + " " + default_title).lower() or "開源" in (content_raw + " " + default_title)
    # An error page names no tools, and projects guessed from a title alone are how
    # made-up GitHub repos got collected: no tool resolution, fan-out or alternatives.
    follow_up = not is_sub_task and not blocked
    if follow_up and "github.com" not in url and (category_name not in LIFE_ENTERTAINMENT_CATEGORIES or has_github_mention):
        try:
            from app.research.tool_resolver import resolve_mentioned_tools
            resolved_subs = await resolve_mentioned_tools(content_raw, default_title, ai_result)
            if resolved_subs:
                ai_result["sub_entities"] = resolved_subs
        except Exception as e:
            logger.warning(f"[Pipeline] Tool resolution error: {e}")

    # 3. Entity Fan-out & Citation Linking (Deduplication & Unpacking)
    sub_entities = ai_result.get("sub_entities", [])
    if isinstance(sub_entities, list) and sub_entities and follow_up and (category_name not in LIFE_ENTERTAINMENT_CATEGORIES or has_github_mention):
        for sub in sub_entities:
            if not isinstance(sub, dict):
                continue
            raw_name = (sub.get("name") or "").strip()
            raw_url = (sub.get("canonical_url") or "").strip()
            reason = (sub.get("reason") or "").strip()
            if not raw_name and not raw_url:
                continue

            canon_url = normalize_canonical_url(raw_url) if raw_url else ""
            target_item_id = None

            # Deduplication check: Is this entity already indexed in OmniKeep?
            existing = find_item_by_canonical_or_url(canon_url or raw_url)
            if existing:
                # Existing entry found -> Instant citation link without duplicate item
                target_item_id = existing["id"]
                save_citation({
                    "source_parent_id": item_id,
                    "target_item_id": target_item_id,
                    "target_canonical_url": canon_url or raw_url,
                    "target_name": raw_name or existing.get("title_l1", "未命名專案"),
                    "mention_context": reason
                })
            else:
                # First time seen -> Record citation first
                cit_id = save_citation({
                    "source_parent_id": item_id,
                    "target_item_id": None,
                    "target_canonical_url": canon_url or raw_url,
                    "target_name": raw_name,
                    "mention_context": reason
                })
                # If valid HTTP/HTTPS URL and not an unconfirmed candidate, spawn background ingestion
                if canon_url and (canon_url.startswith("http://") or canon_url.startswith("https://")):
                    if sub.get("status") != "candidate":
                        try:
                            from app.background import follow_up_pool
                            follow_up_pool.submit(lambda parent=item_id, citation=cit_id, name=raw_name, url=canon_url, why=reason:
                                                  _spawn_child_entity_background(parent, citation, name, url, why))
                        except Exception as e:
                            logger.warning(f"[Entity Fan-out] Error scheduling child spawn: {e}")

    # 4. In-Database Competitor & Superior Alternative Detection
    if follow_up and (category_name not in LIFE_ENTERTAINMENT_CATEGORIES or has_github_mention):
        try:
            from app.research.competitor_detector import detect_competitors_and_alternatives
            await detect_competitors_and_alternatives(
                item_id=item_id,
                title=title_l1,
                summary=summary_l1,
                tech_tags=tech_tags,
                category_name=category_name
            )
        except Exception as e:
            logger.warning(f"[Pipeline] Competitor detection error: {e}")

    return item_record
