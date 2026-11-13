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
from app.parsers.screen import screen_notes
from app.parsers.transcript import TRANSCRIPT_MISSING, get_transcript
from app.parsers.threads import is_threads_url, parse_threads_page
from app.providers import get_primary_provider, get_gemini_provider, has_video_provider
from app.providers.base import UnconfiguredProvider
from app.config import settings
from app.error_translate import mark_ai_failure
from app.schemas.intelligence import AnalysisFailedError, generate_structured_intelligence, usable_analysis

logger = logging.getLogger("omnikeep.pipeline")

# Prompt v2.4 (2026-11-14). Title and summary rules are v2.3 (three rounds of blind review by the
# owner): dense written Chinese, a title that says why the reader should care, a summary that never
# restates the title. The deep analysis is layout A, which won the 2026-11-13 blind review (4.8 against
# 3.2 for v2.3): a one-line verdict and 3 key points always shown, the rest in <details> sections, plus
# a comparison table or a mermaid flowchart only when the content has one. Raw string: the line breaks in the
# example must reach the model as the escape it would write in JSON.
_ANALYSIS_PROMPT_TEMPLATE = r"""你幫使用者整理他自己收藏的內容。他看標題和摘要的 10 秒內要能決定值不值得細看；點開分析後，要拿到完整的重點，並知道這東西能怎麼用在自己身上。
<<BACKGROUND_ANCHOR>>
## 寫法
- 精煉的書面中文，資訊密度高：每個詞都要帶資訊，能用名詞片語講完的就不寫成整句。不要口語、不要鋪陳情境，也不要用「往往」「其實」「多數人」這類泛泛的開場。
- 產品、套件、模型、指令保留原文名稱，其餘一律寫中文。一個詞只用一種寫法，不中英並列。
- 補充說明直接寫進句子，不放在括號裡。
- 只根據上面提供的內容寫：事實、數字、名稱都要來自原文，原文沒有的就不寫。
- 數學符號和單位用純文字，例如「約 6 GB」「>= 85%」「0 到 100 A」。數字一律用阿拉伯數字，例如「3.5 倍」「12 小時」。
- 標點用全形中文標點：，。：「」。

## 各欄位
title_l1：25 字以內，一般讀者一看就懂的白話，不要堆疊術語。
- 專案、工具、模型：「名稱：最吸引人的具體事實或用途」，例如「sparqlite：AI 代理自主 12 小時生出 SQLite 擴充」「web-edit：用手機安全修改伺服器設定檔」。
- 文章、貼文、影片：寫它最核心的主張或發現，例如「Gemini 3 的限制條件要放在提示詞最後」。
- 標題寫讀者為什麼要在意，不寫章節數、條數這類目錄資訊；「怎麼學」「教你」這類口語開頭也不要。

summary_l1：2 到 3 句，合計 70 到 120 字，放在標題正下方。
字數算法：中文字一個算 1 字，英文單字或數字一組算 1 字，例如「sparqlite」算 1 字、「12 小時」算 3 字。
- 第 1 句：它交付什麼、和一般做法差在哪。直接用名詞片語開頭，不寫「某某是一個」，也不再寫一次標題裡的名稱；標題已經講過的事，例如「正式發布」，摘要不再講。
- 第 2 句：最關鍵的具體事實，優先寫數字、規模、授權、部署方式、能不能在本機跑。
- 第 3 句，有必要才寫：適用對象或適用情境。
- 範例：「X 客戶交付開源變現手冊，跳過門檻高、回報低的官方流量分潤。歸納求職輔導、會員等 7 條變現路徑與 26 章教程，附平台規則與報價模板，適合獨立開發者與顧問驗證商業閉環。」

deep_analysis：Markdown，分兩層。讀者點開後要在 5 秒內知道值不值得看、最重要的是什麼；其餘細節收合起來，需要才點開。
第一層，一定顯示：
- 第一行用「> 」開頭的引言，1 到 2 句、合計 60 字以內：直接回答這篇值不值得細看、最適合誰。不寫客套話。
- 「## 最重要的 3 件事」：剛好 3 條，每條格式是「- **2 到 4 字關鍵詞**：一句話」，一句話 40 字以內，寫原文最關鍵的事實、數字或主張。
- 「## 我可以怎麼用」：技術類內容才寫，1 到 2 條，每條寫「什麼情境下用＋第一步做什麼」。<<BACKGROUND_ADVICE>>跟使用者的工作或興趣真的接得上才寫；接不上就只寫 1 條一般用法，不要硬套。
第二層，用 HTML 收合區，依下面的順序，每一區的標題要直接帶出裡面的重點，讓人不點開也知道有什麼：
- 更多重點：其餘重點 2 到 6 條，格式同上；原文是清單、步驟或規格時全部列出。
- 比較表：原文比較 2 個以上的對象，例如工具、模型、方案、版本，而且有共通的比較維度時才加。標題寫一句比較結論，例如「比較表：Qwen3 顯存最省，Llama 4 最快」。裡面放 Markdown 表格，第一欄是對象，共 3 到 5 欄、2 到 8 列，每格 15 字以內，數字照原文寫，不自己換算或加總；原文沒提到的格子填「原文未提及」，不推測。只有 1 個對象或沒有共通維度時不要做表格。
- 流程圖：原文明確描述 4 步以上的流程、資料流或模組之間的呼叫順序時才加。標題寫「流程圖：N 步，從起點到終點」。裡面放一個 mermaid 程式碼區塊：用 flowchart TD 由上往下排，時序互動用 sequenceDiagram；4 到 12 個節點；節點 ID 用英文字母，標籤一律寫成 A["標籤"] 加雙引號，12 字以內；不用 subgraph、style、classDef、click。觀點文章、3 步以內的清單、沒有明確先後的概念都不要畫。
- 限制：只寫原文明確提到的門檻、缺點、還沒做好的地方，0 到 3 條；原文沒提就不要這一區。
- 如果內容是可以在本機跑的 AI 模型，再加一區「<<HARDWARE_LABEL>>」：顯存需求一行、<<HARDWARE_VERDICT>>、一行可以直接複製執行的安裝或啟動指令。
- 內容講的是中國或歐美特有的制度、政策、環境時，加一區「台灣的情況」1 到 2 條。
比較表與流程圖各最多 1 個，沒有符合條件的內容就不要加，大多數文章兩者都不需要。
收合區一律用下面的寫法，<summary> 那一行後面要空一行，</details> 前面也要空一行：
<details>
<summary>更多重點 4 條：授權 MIT、支援 Docker</summary>

- **授權**：MIT，可商用。

</details>
流程圖收合區的寫法：
<details>
<summary>流程圖：4 步，從收到連結到存進資料庫</summary>

```mermaid
flowchart TD
  A["收到連結"] --> B["抓取原文"] --> C["AI 分析"] --> D["存進資料庫"]
```

</details>

生活、娛樂、觀點類：引言改寫成「最值得記住的一句原話」並加上引號；「## 最重要的 3 件事」照寫；不寫「## 我可以怎麼用」；其他原話最多 5 句放進收合區「更多原話」。
內容很短、資訊很少時：只寫引言與「## 最重要的 3 件事」，條數可以少於 3。

## 範例（只示範語氣、密度和長度，內容與本次無關）
{"title_l1": "web-edit：用手機安全修改伺服器設定檔",
 "summary_l1": "手機瀏覽器即可編輯遠端檔案的輕量服務，讓 AI 代理遠端工作時，API key 等敏感設定不經過模型。只開在 Tailscale 內網，不對外開 port，以 Python 單檔啟動，編輯器採 CodeMirror 6。",
 "deep_analysis": "> 外出時要改伺服器的 .env 又不想讓 AI 看到金鑰，這是最省事的做法，值得先裝。\n\n## 最重要的 3 件事\n- **金鑰不經模型**：AI 代理只負責啟動服務，敏感檔案由人用手機自己改。\n- **只走內網**：只綁 Tailscale 內網，不對外開 port，也不用 Nginx。\n- **手機好打字**：編輯器選 CodeMirror 6，Monaco 在手機上的鍵盤與手勢支援差。\n\n## 我可以怎麼用\n- 外出時要改伺服器的 .env：先在伺服器啟動 web-edit，再用已登入 Tailscale 的手機開啟。\n\n<details>\n<summary>更多重點 1 條：Python 單檔啟動</summary>\n\n- **部署**：以 Python 單檔執行，提供目錄瀏覽與就地編輯。\n\n</details>\n\n<details>\n<summary>限制 1 條：沒有帳號權限管理</summary>\n\n- **單人使用**：原文只描述單人情境，沒有帳號與權限管理。\n\n</details>"}

## 輸出格式
只輸出一個合法的 JSON 物件：
{
  "category": "從候選分類清單選 1 個最適合的；都不適合就填 Inbox",
  "title_l1": "見上方規定",
  "summary_l1": "見上方規定",
  "tech_tags": ["3 個標籤"],
  "deep_analysis": "見上方規定",
  "is_composite": false,
  "sub_entities": [{"name": "提到的開源專案、模型或工具名稱", "canonical_url": "GitHub、Hugging Face 或官網網址，不知道就填空字串", "reason": "原文對它的評價或亮點，一句話"}]
}
- 內容是多個專案或工具的推薦、盤點時，is_composite 設為 true，sub_entities 列出全部項目。
- 只講單一主題時，is_composite 設為 false；有提到開源專案或工具就記在 sub_entities，完全沒提到就給空陣列 []。

## 送出前逐項檢查
1. 標題 25 字以內，是一般人看得懂的白話；超過就刪修飾語。
2. 摘要第一句沒有重寫標題裡的名稱，也沒有「某某是一個」的句型。
3. 沒有「旨在」「致力於」「本文」「該專案」「是一款」「聚焦於」「作者分享」「往往」這類空話，也沒有鋪陳情境的開場句。
4. 沒有括號補充、沒有中英並列。
5. 原文裡的清單、步驟、規格、數字、授權與部署方式，重要的都有寫進摘要或重點。
6. 收合區的 <summary> 後面與 </details> 前面都有空行；比較表與流程圖只在符合條件時才出現。"""


# Extra rule appended to the analysis prompt per the ANALYSIS_DEPTH setting; "standard" leaves it unchanged.
ANALYSIS_DEPTH_RULES = {
    "standard": "",
    "concise": ("- 分析深度（使用者設定：重點摘要）：deep_analysis 只寫引言、「## 最重要的 3 件事」與最多 1 條「## 我可以怎麼用」，不加任何收合區；"
                "AI 模型的硬體只在最後加一行結論，不附指令。"
                "這一條優先於上面對 deep_analysis 段落與條數的要求。"),
    "technical": ("- 分析深度（使用者設定：技術細節）：收合區「更多重點」不設條數上限，"
                  "原文有的架構、關鍵參數、數據規模、限制與已知問題、與同類方案的差異都要列出，不要為了精簡省略。"),
    "actionable": ("- 分析深度（使用者設定：含落地建議）：工程、工具或策略類內容，"
                   "「## 我可以怎麼用」寫 3 條，每條寫要做什麼、怎麼確認有沒有效。"),
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
SCREEN_PROMPT_CHARS = 6000  # the OCR section's cap (app/parsers/screen.py); added after the 30000 of transcript


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


# Marks an item kept while no AI was connected: title, address, cover and the fetched text are
# stored, nothing was analysed. The item also carries analysis_status = 'pending' (the state a
# radar stub waiting for its analysis has); app/refetch.py analyses it once an AI is connected.
NOT_ANALYSED_TAG = "（尚未分析）"
NOT_ANALYSED = "pending"
EXCERPT_CHARS = 160


def not_analysed_summary(description: str, content: str) -> str:
    """The summary of an item kept without analysis: the page's own description, else the
    start of its text. Never written by an AI, and tagged so no one takes it for one."""
    text = " ".join((description or "").split())
    if not text:
        lines = [line.strip() for line in (content or "").splitlines()]
        text = " ".join(" ".join(line for line in lines if line and not line.startswith(("#", "URL:", "http"))).split())
    if len(text) > EXCERPT_CHARS:
        text = text[:EXCERPT_CHARS].rstrip() + "…"
    return f"{NOT_ANALYSED_TAG}{text}" if text else f"{NOT_ANALYSED_TAG}還沒有接上 AI，先存下原文。"


KIND_NAMES = {"reel": "短影音（含畫面文字辨識與語音轉錄）", "youtube": "YouTube 影片資訊", "bilibili": "Bilibili 影片",
              "threads": "Threads 貼文與討論串", "github": "GitHub 專案", "rss": "文章", "web": "網頁／文章",
              "snippet": "使用者的筆記片段"}


def saved_item_prompt(item: Dict[str, Any], categories: str) -> str:
    """The analysis prompt for an item's stored content (nothing is fetched again)."""
    kind = KIND_NAMES.get(item.get("source_type") or "", "內容")
    prompt = f"""請深度分析以下{kind}：
網址：{item.get('url') or ''}
原始標題：{item.get('title_l1') or ''}
作者／發布者：{item.get('author') or ''}

候選分類清單：[{categories}]

=== 內容節錄 ===
{(item.get('content_raw') or '')[:15000]}
=== 內容結束 ===

請依據規範輸出結構化 JSON。若內容提及多個開源專案或工具，請將 is_composite 設為 true 並於 sub_entities 列出。"""
    return prompt + interest_profile_block()


def hardware_label() -> str:
    """Name of the AI-model hardware section; names the machine only if the owner entered it."""
    hardware = (settings.LOCAL_HARDWARE or "").strip()
    if hardware:
        return f"在你的電腦上跑：{hardware}"
    return "硬體需求"


def analysis_system_prompt() -> str:
    """System prompt for item analysis, personalised from the in-app settings.

    USER_BACKGROUND and LOCAL_HARDWARE are read on every call, so a value saved
    in the app applies to the next analysis without a restart. Left empty, the
    prompt stays neutral instead of assuming who the owner is.
    """
    background = (settings.USER_BACKGROUND or "").strip().rstrip("。.")
    hardware = (settings.LOCAL_HARDWARE or "").strip()
    if background:
        anchor = f"使用者背景：{background}。\n"
        advice = "建議要貼合使用者背景和他的電腦配置。"
    else:
        anchor = ""
        advice = "有附使用者興趣設定檔時，優先貼合他關注的領域。"
    if hardware:
        verdict = f"在 {hardware} 上能不能跑、建議用什麼精度，一行結論。"
    else:
        verdict = "8 GB、16 GB、24 GB 顯存各能不能跑、建議用什麼精度，一行結論。"
    parts = {
        "BACKGROUND_ANCHOR": anchor,
        "BACKGROUND_ADVICE": advice,
        "HARDWARE_LABEL": hardware_label(),
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

def analysis_missing_note(reason: str) -> str:
    return f"⚠️ AI 沒有產生可用的分析（{reason}）。這裡的摘要是瀏覽器看到的網頁描述，不是 AI 寫的。"


async def _analyze_with_guardrails(provider, prompt: str, system_prompt: Optional[str] = None,
                                   browser_summary: str = "") -> Dict[str, Any]:
    """Execute LLM generation protected by strict Pydantic contract & reflection self-healing.

    A failed analysis is raised, never returned as an empty result: run_pipeline() then saves
    nothing and its caller decides what to do (the queue retries and backs off, the ingest
    API answers with the reason). It used to come back empty and was saved as a finished
    item with a placeholder summary, which also kept the same link from being analysed again.

    One case still keeps the item: the bookmarklet sent the page's own description
    (`browser_summary`) and the model answered, but never with a usable analysis. Then the
    description stands in as the summary, as it did before, and a note says so.

    With no AI connected at all (UnconfiguredProvider) nothing is sent and {} comes back:
    run_pipeline() then keeps the item as "not analysed yet". That is not a failure.
    """
    if isinstance(provider, UnconfiguredProvider):
        return {}
    try:
        return await generate_structured_intelligence(provider, prompt, system_prompt or analysis_system_prompt())
    except Exception as exc:
        if isinstance(exc, AnalysisFailedError) and browser_summary:
            logger.warning("[Pipeline] %s Keeping the item with the description the browser sent.", exc)
            return {"deep_analysis": f"> {analysis_missing_note(exc.reason)}"}
        mark_ai_failure(exc)  # callers tell it from a failed fetch (app/error_translate.py)
        raise

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
        "http_status": None, "transcript_status": "", "transcript_reason": "", "screen_text": "",
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
        # What the frames show and the speech does not say (optional OCR, app/parsers/screen.py).
        screen = await screen_notes(url, meta, transcript.text) if transcript and transcript.status == "ok" else ""
        screen_part = f"\n\n{screen}" if screen else ""
        parsed.update(kind="youtube", source_type="youtube",
                      transcript_status=transcript.status if transcript else "",
                      transcript_reason=transcript.reason if transcript else "",
                      screen_text=screen,
                      content_raw=f"# {meta['title']}\n\n頻道: {meta['author']}\nURL: {url}{desc_part}{transcript_part}{screen_part}",
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
                       page_title: str = "", page_description: str = "",
                       as_note: bool = False, saved: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Fetch, analyse and save one link or note.

    With no AI connected (a fresh install) nothing is sent to any AI: the item is saved with
    its title, address, cover and fetched text, tagged NOT_ANALYSED_TAG. `saved` is such an
    item being analysed later: its stored content is analysed, nothing is fetched again.
    """
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
    description = ""  # the page's own description, for the summary of an item kept without analysis
    # A fresh install has no AI: every analysis below comes back empty without a request.
    no_ai = isinstance(get_primary_provider(), UnconfiguredProvider)

    user_note = ""
    if saved is None and not as_note and "#note=" in clean_input:
        from urllib.parse import unquote
        parts = clean_input.split("#note=", 1)
        clean_input = parts[0]
        user_note = unquote(parts[1]).strip()

    # 2. Route by input type (Pure URL / Mobile Share Snippet vs Text Note)
    # as_note: the owner chose to keep the text itself, even if it is short and holds one address.
    detected_url = None if as_note or saved is not None else extract_target_url(clean_input)
    if saved is not None:
        # Kept earlier without analysis: analyse what is stored. Fetching again could come
        # back with an error page and replace the text that is already here.
        url = saved["url"]
        source_type = saved.get("source_type") or "web"
        content_raw = saved.get("content_raw") or ""
        cover_image = saved.get("cover_image") or ""
        author = saved.get("author") or ""
        default_title = saved.get("title_l1") or _title_from_url(url)
        origin = saved.get("origin") or origin
        if manual_category is None and (saved.get("category_name") or "Inbox") != "Inbox":
            manual_category = saved["category_name"]  # the owner filed it already
        description = (saved.get("summary_l1") or "").removeprefix(NOT_ANALYSED_TAG)
        ai_result = await _analyze_with_guardrails(get_primary_provider(), saved_item_prompt(saved, cat_list_str))
    elif detected_url:
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
        description = page_description or parsed["description"]
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
                ai_result = await _analyze_with_guardrails(primary, prompt,
                                                           browser_summary=parsed["fallback_summary"])
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
- deep_analysis 的重點要收錄它的架構、規格參數與核心機制；若是 AI 模型，加上收合區「{hardware_label()}」。
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
                    # An answer with no analysis in it is a failure too (usable_analysis raises):
                    # an empty {} used to count as the result and kept the transcript from being used.
                    ai_result = usable_analysis(await gemini.analyze_youtube(url, prompt))
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
                # The screen text is kept apart: a long transcript must not push it out, nor it the transcript.
                screen = parsed.get("screen_text") or ""
                spoken_part = content_raw.removesuffix(f"\n\n{screen}") if screen else content_raw
                screen_block = f"""
=== 畫面文字（從影片畫面 OCR 讀出、旁白沒講到的字）===
{screen[:SCREEN_PROMPT_CHARS]}
=== 畫面文字結束 ===
""" if screen else ""
                screen_rule = ("\n畫面文字是投影片、圖表、截圖上的字，不是旁白，[MM:SS] 是出現的時間；可以用來補數字、名稱、"
                               "圖表標題，但 OCR 會有錯字和斷字，看不懂的不要猜。") if screen else ""
                prompt = f"""深度分析以下 YouTube 影片，依據逐字稿（影片實際說的內容）輸出專業中文結構化總結、技術標籤與核心洞見：
影片標題：{default_title}
頻道：{author}
URL：{url}

候選分類清單：[{cat_list_str}]

=== 影片說明欄與逐字稿 ===
{spoken_part[:30000]}
=== 內容結束 ===
{screen_block}
逐字稿可能有語音辨識的錯字，依上下文判讀；逐字稿沒說到的細節不要補。逐字稿的 [MM:SS] 是該段開始的時間。{screen_rule}"""
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
            ai_result = await _analyze_with_guardrails(primary, prompt,
                                                       browser_summary=parsed["fallback_summary"])

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
    # No AI connected and nothing analysed (a video slot of its own may still have answered).
    not_analysed = no_ai and not fetch_failed and not (ai_result.get("summary_l1") or "").strip()
    if not_analysed:
        logger.info("[Pipeline] %s: no AI connected; kept without analysis", url)
        title_l1 = default_title
        summary_l1 = not_analysed_summary(description, "" if blocked else content_raw)
        deep_analysis = ""
        tech_tags = []
    elif fetch_failed:
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
        "analysis_status": NOT_ANALYSED if not_analysed else "done",
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
    # Nor without an analysis: these steps ask the AI, and there is none.
    follow_up = not is_sub_task and not blocked and not not_analysed
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


def is_not_analysed(item: Dict[str, Any]) -> bool:
    """Kept while no AI was connected (radar stubs waiting their turn are not these)."""
    return item.get("analysis_status") == NOT_ANALYSED and item.get("origin") != "radar"


async def analyse_saved_item(item: Dict[str, Any]) -> Dict[str, Any]:
    """Analyse an item that was kept without analysis; the item is rewritten in place.

    The stored text is analysed as it is. Only when there is none (the fetch got an error
    page, and the title and description were all there was) is the link fetched again, the
    same as collecting it again. Raises what run_pipeline() raises when the AI fails; the
    item then stays as it was.
    """
    content = item.get("content_raw") or ""
    refetch = not content.strip() or (item.get("source_type") in BLOCK_CHECKED_KINDS and bool(detect_blocked_page(content)))
    if refetch and str(item.get("url") or "").startswith(("http://", "https://")):
        category = item.get("category_name")
        return await run_pipeline(
            item["url"], manual_category=category if category and category != "Inbox" else None,
            origin=item.get("origin") or "manual", page_title=item.get("title_l1") or "",
            page_description=(item.get("summary_l1") or "").removeprefix(NOT_ANALYSED_TAG))
    return await run_pipeline(item["url"], saved=item)
