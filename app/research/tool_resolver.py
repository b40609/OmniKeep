"""
OmniKeep Entity & Tool Resolver
Automated resolution of mentioned open-source tools and projects without explicit URLs.
Features:
- GitHub Search API integration with rate-limit protection & optional GITHUB_TOKEN
- Candidate ranking & LLM multiple-choice judge (anti-hallucination constraint)
- Dual-track confidence categorization (verified >= 0.7, candidate 0.4-0.7, rejected < 0.4)
"""

import json
import logging
import re
from typing import List, Dict, Any, Optional
from urllib.parse import quote_plus

from app.config import settings
from app.network import public_http_client
from app.providers import get_primary_provider
from app.schemas.intelligence import sanitize_and_validate_judge, sanitize_and_validate_query

logger = logging.getLogger("omnikeep.tool_resolver")

GITHUB_SEARCH_API = "https://api.github.com/search/repositories"
_GITHUB_SEARCH_CACHE: Dict[str, List[Dict[str, Any]]] = {}

HUGGINGFACE_SEARCH_API = "https://huggingface.co/api/models"
_HUGGINGFACE_SEARCH_CACHE: Dict[str, List[Dict[str, Any]]] = {}

TOOL_JUDGE_SYSTEM_PROMPT = """你是一位嚴謹的軟體架構、開源生態與 AI 模型評審官。
你的任務是判定社群貼文所提及的開源工具、技術專案或 AI 模型，是否吻合 GitHub 或 Hugging Face 搜尋出的候選專案。

嚴格原則（絕對防幻覺）：
1. 只能從提供的候選項目中挑選（以數字編號 1 到 N 代表），或者若完全不吻合，必須將 matched_index 設為 null。
2. 絕對嚴禁捏造任何不在候選清單內的 URL 或專案名稱。
3. 信心指標 confidence 必須在 0.0 到 1.0 之間：
   - >= 0.7：名稱高度吻合，且功能描述、技術棧與貼文所提及的核心完全一致（若為該模型的官方開源實作、主流 C++/推理移植版或核心社群封裝庫，亦屬有效匹配）。
   - 0.4 到 0.7：名稱相似或概念吻合，但貼文資訊有限、無法 100% 確信為作者所指之唯一專案。
   - < 0.4：毫不相干或同名但完全不同領域。
4. 輸出合法的 JSON 物件：
{
  "matched_index": 1,
  "confidence": 0.95,
  "reason": "專案名稱與功能描述完全符合貼文提及內容"
}"""

QUERY_EXTRACTION_PROMPT = """分析以下貼文內容與標題（包含逐字稿、視覺文字與說明欄），判斷文中是否提及了具體的軟體工具、開源專案、AI 模型、CLI 指令、GitHub 倉庫或 Hugging Face 模型庫（如 OpenMontage、LocateAnything、baoyu-design、impeccable），但尚未附上官方網址。
若是，請提取 1 組最適合在 GitHub 或 Hugging Face 檢索的精確關鍵字（純專案/模型名稱，英文字母優先，例如 'OpenMontage'、'LocateAnything'、'baoyu-design'、'impeccable'）。
若貼文只是純個人生活瑣事、時事新聞且未提及任何開源專案、AI 模型或軟體工具，請回傳 null。

嚴格輸出合法 JSON 物件：
{
  "has_tool": true,
  "tool_name": "提及名稱（如 OpenMontage、LocateAnything）",
  "search_query": "用於搜尋的精確關鍵字（如 OpenMontage、LocateAnything）"
}"""


def normalize_query_variants(q: str) -> List[str]:
    """Generate search variants by stripping common guide/awesome/list affixes and model size suffixes."""
    clean = q.strip()
    variants = [clean]
    suffixes = [
        "指南", "手冊", "手册", "教程", "大全", "清單", "清单", "筆記", "笔记",
        "合集", "入門", "入门", "實踐", "实践", "專案", "专案", "倉庫", "仓库",
        "guide", "awesome", "cheatsheet", "list", "tutorial", "starter"
    ]
    core = clean
    for s in suffixes:
        core = re.sub(rf"(?i)(^{re.escape(s)}[\s\-_/:]*|[\s\-_/:]*{re.escape(s)}$)", "", core).strip()

    # Strip model parameter count / version suffixes (e.g. -3B, -7B, -14B, -v1.0)
    core_stripped = re.sub(r'(?i)[-_]?(?:\d+b|v\d+(?:\.\d+)*|preview|latest|small|base|large)$', '', core).strip()
    if core_stripped and len(core_stripped) >= 2:
        core = core_stripped

    if core and core.lower() != clean.lower() and len(core) >= 2:
        variants.append(core)
    return variants


async def _fetch_github_api(clean_query: str, limit: int = 5) -> List[Dict[str, Any]]:
    """Single query call to GitHub search API."""
    headers = {
        "User-Agent": "OmniKeep-ToolResolver/1.0",
        "Accept": "application/vnd.github.v3+json"
    }
    if settings.GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {settings.GITHUB_TOKEN}"

    url = f"{GITHUB_SEARCH_API}?q={quote_plus(clean_query)}&sort=stars&order=desc&per_page={limit}"

    try:
        async with public_http_client(timeout=8.0, follow_redirects=True) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                items = data.get("items", [])
                candidates = []
                for item in items[:limit]:
                    candidates.append({
                        "full_name": item.get("full_name", ""),
                        "name": item.get("name", ""),
                        "html_url": item.get("html_url", ""),
                        "description": (item.get("description") or "").strip(),
                        "stars": int(item.get("stargazers_count", 0)),
                        "language": item.get("language") or "",
                        "topics": item.get("topics", [])
                    })
                return candidates
            elif resp.status_code in (403, 429):
                logger.warning(f"[ToolResolver] GitHub search rate limit encountered (status {resp.status_code})")
                return []
            else:
                logger.debug(f"[ToolResolver] GitHub API returned status {resp.status_code} for query: {clean_query}")
                return []
    except Exception as e:
        logger.warning(f"[ToolResolver] GitHub search failed for '{clean_query}': {e}")
        return []


async def search_github_repositories(query: str, limit: int = 5) -> List[Dict[str, Any]]:
    """Search GitHub public repositories with rate limit tolerance, affix normalization and auth token support."""
    clean_query = query.strip()
    if not clean_query:
        return []

    # Clean query to prevent invalid GitHub search syntax
    clean_query = re.sub(r'[\r\n\t]+', ' ', clean_query)
    clean_query = clean_query[:100].strip()

    cache_key = f"{clean_query.lower()}:{limit}"
    if cache_key in _GITHUB_SEARCH_CACHE:
        return _GITHUB_SEARCH_CACHE[cache_key]

    variants = normalize_query_variants(clean_query)
    merged_candidates: List[Dict[str, Any]] = []
    seen_urls = set()

    for q_var in variants:
        sub_cache_key = f"{q_var.lower()}:{limit}"
        if sub_cache_key in _GITHUB_SEARCH_CACHE:
            cands = _GITHUB_SEARCH_CACHE[sub_cache_key]
        else:
            cands = await _fetch_github_api(q_var, limit)
            _GITHUB_SEARCH_CACHE[sub_cache_key] = cands

        for c in cands:
            if c["html_url"] not in seen_urls:
                seen_urls.add(c["html_url"])
                merged_candidates.append(c)

    # Sort merged candidates by stars descending
    merged_candidates.sort(key=lambda x: x["stars"], reverse=True)
    top_candidates = merged_candidates[:limit]
    _GITHUB_SEARCH_CACHE[cache_key] = top_candidates
    return top_candidates


async def search_huggingface_models(query: str, limit: int = 5) -> List[Dict[str, Any]]:
    """Search Hugging Face Hub models for open-weight models, checkpoints and spaces."""
    clean_query = query.strip()
    if not clean_query:
        return []

    clean_query = re.sub(r'[\r\n\t]+', ' ', clean_query)[:100].strip()
    cache_key = f"hf:{clean_query.lower()}:{limit}"
    if cache_key in _HUGGINGFACE_SEARCH_CACHE:
        return _HUGGINGFACE_SEARCH_CACHE[cache_key]

    variants = normalize_query_variants(clean_query)
    merged_candidates: List[Dict[str, Any]] = []
    seen_ids = set()

    for q_var in variants:
        url = f"{HUGGINGFACE_SEARCH_API}?search={quote_plus(q_var)}&limit={limit}"
        headers = {"User-Agent": "OmniKeep-ToolResolver/1.0"}
        try:
            async with public_http_client(timeout=8.0, follow_redirects=True) as client:
                resp = await client.get(url, headers=headers)
                if resp.status_code == 200:
                    items = resp.json()
                    for item in items[:limit]:
                        mid = item.get("id") or ""
                        if mid and mid not in seen_ids:
                            seen_ids.add(mid)
                            likes = int(item.get("likes", 0))
                            downloads = int(item.get("downloads", 0))
                            tag = item.get("pipeline_tag") or "model"
                            merged_candidates.append({
                                "full_name": mid,
                                "name": mid.split("/")[-1] if "/" in mid else mid,
                                "html_url": f"https://huggingface.co/{mid}",
                                "description": f"Hugging Face 模型 ({tag}) · 下載量 {downloads:,} · 愛心 {likes:,}",
                                "stars": likes,
                                "downloads": downloads,
                                "language": tag,
                                "topics": [tag, "huggingface"],
                                "platform": "huggingface"
                            })
        except Exception as e:
            logger.warning(f"[ToolResolver] HuggingFace search failed for '{q_var}': {e}")

    merged_candidates.sort(key=lambda x: (x.get("downloads", 0), x["stars"]), reverse=True)
    top_candidates = merged_candidates[:limit]
    _HUGGINGFACE_SEARCH_CACHE[cache_key] = top_candidates
    return top_candidates


async def judge_best_matching_repo(
    target_name: str,
    mention_context: str,
    candidates: List[Dict[str, Any]],
    provider=None
) -> Dict[str, Any]:
    """Judge candidates via LLM multiple-choice to guarantee factual linking without hallucinations."""
    if not candidates:
        return {"matched": None, "confidence": 0.0, "reason": "無候選專案"}

    # Exact name fast-path (e.g. repo name equals target_name exactly and has stars)
    clean_target = target_name.strip().lower()
    for idx, c in enumerate(candidates):
        c_name = c["name"].lower()
        if (c_name == clean_target or c["full_name"].lower().endswith("/" + clean_target)) and (c["stars"] >= 20 or c.get("downloads", 0) >= 100):
            # High-confidence direct match if name is distinct and well-starred
            p_prefix = "Hugging Face 模型" if c.get("platform") == "huggingface" else "倉庫"
            score_metric = f"下載 {c.get('downloads', 0):,}" if c.get("platform") == "huggingface" else f"★{c['stars']:,}"
            return {
                "matched": c,
                "confidence": 0.95,
                "reason": f"{p_prefix} '{c['full_name']}' 與提及名稱完全一致 ({score_metric})"
            }

    # Format candidates for LLM multiple choice
    candidate_lines = []
    for idx, c in enumerate(candidates, 1):
        desc = c["description"][:160] if c["description"] else "無描述"
        topics_str = ", ".join(c.get("topics", [])[:4]) if c.get("topics") else "無標籤"
        plat_label = "[Hugging Face]" if c.get("platform") == "huggingface" else "[GitHub]"
        stat_label = f"下載 {c.get('downloads', 0):,} · ♥{c['stars']:,}" if c.get("platform") == "huggingface" else f"★{c['stars']:,}"
        candidate_lines.append(
            f"[{idx}] {plat_label} {c['full_name']} ({stat_label})\n"
            f"    網址: {c['html_url']}\n"
            f"    說明: {desc}\n"
            f"    標籤: {topics_str}"
        )
    candidates_text = "\n\n".join(candidate_lines)

    prompt = f"""請審查以下開源與 AI 模型候選項目，判斷是否有吻合貼文提及之專案/模型：

提及名稱：{target_name}
提及上下文/亮點：{mention_context}

候選清單：
{candidates_text}

請根據上述規範，輸出嚴格 JSON 選擇題判定結果。"""

    try:
        active_provider = provider or get_primary_provider()
        res_raw = await active_provider.generate_json(prompt, TOOL_JUDGE_SYSTEM_PROMPT)
        judge = sanitize_and_validate_judge(res_raw)
        matched_idx = judge.matched_index
        confidence = judge.confidence
        reason = judge.reason

        if isinstance(matched_idx, int) and 1 <= matched_idx <= len(candidates):
            return {
                "matched": candidates[matched_idx - 1],
                "confidence": confidence,
                "reason": reason
            }
    except Exception as e:
        logger.warning(f"[ToolResolver] LLM judge failed: {e}")

    # Fallback when LLM judge returns inconclusive
    return {"matched": None, "confidence": 0.0, "reason": "未找到吻合專案"}


async def extract_tool_query_from_content(
    content_raw: str,
    default_title: str,
    provider=None
) -> Optional[Dict[str, str]]:
    """Determine if content describes an open-source tool and extract GitHub search keyword."""
    # Fast heuristic check before calling LLM
    combined = f"{default_title} {content_raw[:1500]}".lower()
    tech_keywords = ["github", "repo", "開源", "工具", "指令", "cli", "套件", "專案", "代碼", "code", "ai", "agent", "指南", "手冊", "手册", "教程", "大全", "awesome"]
    if not any(k in combined for k in tech_keywords):
        return None

    prompt = f"""標題：{default_title}
貼文內容節錄：
{content_raw[:2500]}

請依規範判斷是否有未附網址之開源工具/專案，並輸出 JSON。"""

    try:
        active_provider = provider or get_primary_provider()
        res_raw = await active_provider.generate_json(prompt, QUERY_EXTRACTION_PROMPT)
        q_obj = sanitize_and_validate_query(res_raw)
        if q_obj.has_tool and q_obj.search_query:
            return {"tool_name": q_obj.tool_name or q_obj.search_query, "search_query": q_obj.search_query}
    except Exception as e:
        logger.warning(f"[ToolResolver] Query extraction failed: {e}")

    return None


async def resolve_mentioned_tools(
    content_raw: str,
    default_title: str,
    ai_result: Dict[str, Any],
    provider=None
) -> List[Dict[str, Any]]:
    """Main entrypoint: enrich sub_entities with resolved open-source project & Hugging Face model links."""
    sub_entities = ai_result.get("sub_entities") or []
    if not isinstance(sub_entities, list):
        sub_entities = []

    enriched: List[Dict[str, Any]] = []

    # 1. Resolve existing sub_entities that lack a canonical_url
    for sub in sub_entities:
        if not isinstance(sub, dict):
            continue
        name = (sub.get("name") or "").strip()
        url = (sub.get("canonical_url") or "").strip()
        reason = (sub.get("reason") or "").strip()

        # If already has a valid URL, preserve as-is with platform annotation
        if url.startswith("http://") or url.startswith("https://"):
            sub["status"] = "verified"
            if "huggingface.co" in url and not sub["name"].startswith("🤗"):
                sub["name"] = f"🤗 {sub['name']}"
            elif "github.com" in url and not sub["name"].startswith("📦"):
                sub["name"] = f"📦 {sub['name']}"
            enriched.append(sub)
            continue

        # Needs lookup if name is present
        if name:
            clean_name = re.sub(r'^[📦🤗\s]+', '', name).strip()
            combined_txt = f"{clean_name} {reason} {default_title} {content_raw[:800]}".lower()
            is_model_likely = any(term in combined_txt for term in (
                "huggingface", "model", "模型", "大模型", "權重", "safetensors", "checkpoint",
                "-3b", "-7b", "-8b", "-14b", "-70b", "vlm", "llm", "定位", "grounding"
            ))

            hf_candidates = []
            if is_model_likely:
                hf_candidates = await search_huggingface_models(clean_name, limit=3)

            gh_candidates = await search_github_repositories(clean_name, limit=5)

            # Check Hugging Face match
            matched_hf = None
            if hf_candidates:
                judge_hf = await judge_best_matching_repo(clean_name, reason, hf_candidates, provider=provider)
                if judge_hf.get("confidence", 0.0) >= 0.7:
                    matched_hf = judge_hf.get("matched")

            # Check GitHub match
            matched_gh = None
            if gh_candidates:
                judge_gh = await judge_best_matching_repo(clean_name, reason, gh_candidates, provider=provider)
                if judge_gh.get("confidence", 0.0) >= 0.7:
                    matched_gh = judge_gh.get("matched")

            # Dual-track enrichment: If both matched, add both!
            if matched_hf and matched_gh:
                sub["name"] = f"🤗 {matched_hf['full_name']}"
                sub["canonical_url"] = matched_hf["html_url"]
                sub["status"] = "verified"
                sub["stars"] = matched_hf["stars"]
                sub["matched_name"] = matched_hf["full_name"]
                sub["reason"] = f"{reason} · Hugging Face 模型卡 (下載 {matched_hf.get('downloads', 0):,})"
                enriched.append(sub)

                gh_sub = {
                    "name": f"📦 {matched_gh['full_name']}",
                    "canonical_url": matched_gh["html_url"],
                    "status": "verified",
                    "stars": matched_gh["stars"],
                    "matched_name": matched_gh["full_name"],
                    "reason": f"{reason} · GitHub 代碼倉庫 (★{matched_gh['stars']:,})"
                }
                enriched.append(gh_sub)
                continue
            elif matched_hf:
                sub["name"] = f"🤗 {matched_hf['full_name']}"
                sub["canonical_url"] = matched_hf["html_url"]
                sub["status"] = "verified"
                sub["stars"] = matched_hf["stars"]
                sub["matched_name"] = matched_hf["full_name"]
                sub["reason"] = f"{reason} · Hugging Face 模型卡 (下載 {matched_hf.get('downloads', 0):,})"
                enriched.append(sub)
                continue
            elif matched_gh:
                sub["name"] = f"📦 {matched_gh['full_name']}"
                sub["canonical_url"] = matched_gh["html_url"]
                sub["status"] = "verified"
                sub["stars"] = matched_gh["stars"]
                sub["matched_name"] = matched_gh["full_name"]
                sub["reason"] = f"{reason} · GitHub: {matched_gh['full_name']} (★{matched_gh['stars']:,})"
                enriched.append(sub)
                continue
            else:
                candidates = hf_candidates + gh_candidates
                if candidates:
                    judge = await judge_best_matching_repo(clean_name, reason, candidates, provider=provider)
                    confidence = judge.get("confidence", 0.0)
                    matched = judge.get("matched")
                    if matched and confidence >= 0.4:
                        prefix = "🤗" if matched.get("platform") == "huggingface" else "📦"
                        sub["name"] = f"{prefix} {matched['full_name']}"
                        sub["canonical_url"] = matched["html_url"]
                        sub["status"] = "candidate"
                        sub["stars"] = matched["stars"]
                        sub["matched_name"] = matched["full_name"]
                        sub["reason"] = f"[疑似候選] {reason} · {matched['full_name']}"
                        sub["candidate_repos"] = [c["html_url"] for c in candidates[:3]]
                    else:
                        sub["status"] = "unverified"
                enriched.append(sub)

    # 2. Check if any sub_entity was successfully resolved with a concrete URL
    has_resolved_url = any((s.get("canonical_url") or "").startswith("http") for s in enriched)

    # If no concrete URL was found (either sub_entities was empty or contained unresolvable generic names),
    # trigger global extraction from title, description, transcripts, and visual text!
    if not has_resolved_url:
        tool_info = await extract_tool_query_from_content(content_raw, default_title, provider=provider)
        if tool_info:
            tool_name = tool_info["tool_name"]
            search_query = tool_info["search_query"]
            clean_q = re.sub(r'^[📦🤗\s]+', '', search_query).strip()
            combined_txt = f"{clean_q} {default_title} {content_raw[:800]}".lower()
            is_model_likely = any(term in combined_txt for term in (
                "huggingface", "model", "模型", "大模型", "權重", "safetensors", "checkpoint",
                "-3b", "-7b", "-8b", "-14b", "-70b", "vlm", "llm", "locate"
            ))

            hf_cands = await search_huggingface_models(clean_q, limit=3) if is_model_likely else []
            gh_cands = await search_github_repositories(clean_q, limit=5)
            candidates = hf_cands + gh_cands

            if candidates:
                context_snippet = f"{default_title}: {content_raw[:300]}"
                judge = await judge_best_matching_repo(tool_name, context_snippet, candidates, provider=provider)
                confidence = judge.get("confidence", 0.0)
                matched = judge.get("matched")
                judge_reason = judge.get("reason", "")

                if matched and confidence >= 0.7:
                    prefix = "🤗" if matched.get("platform") == "huggingface" else "📦"
                    discovered = {
                        "name": f"{prefix} {matched['full_name']}",
                        "canonical_url": matched["html_url"],
                        "reason": f"文中提及專案 · {matched['full_name']} - {judge_reason}",
                        "status": "verified",
                        "stars": matched["stars"],
                        "matched_name": matched["full_name"]
                    }
                    # Filter out ghost entries with empty URLs and prepend the discovered concrete entity
                    enriched = [discovered] + [s for s in enriched if (s.get("canonical_url") or "").startswith("http")]
                elif matched and confidence >= 0.4:
                    prefix = "🤗" if matched.get("platform") == "huggingface" else "📦"
                    discovered = {
                        "name": f"{prefix} {matched['full_name']}",
                        "canonical_url": matched["html_url"],
                        "reason": f"[疑似候選] 文中提及專案 · {matched['full_name']}",
                        "status": "candidate",
                        "stars": matched["stars"],
                        "matched_name": matched["full_name"],
                        "candidate_repos": [c["html_url"] for c in candidates[:3]]
                    }
                    enriched = [discovered] + [s for s in enriched if (s.get("canonical_url") or "").startswith("http")]

    # Clean up enriched list: prioritize entries with real URLs
    enriched = [s for s in enriched if (s.get("canonical_url") or "").startswith("http")]

    # 3. Discover Taiwan / localized counterpart for regional projects (e.g. 潤學 / 出海)
    if enriched:
        tw_counterpart = await resolve_taiwan_counterpart(
            enriched[0].get("name", ""),
            content_raw,
            provider=provider
        )
        if tw_counterpart and not any(e.get("canonical_url") == tw_counterpart["canonical_url"] for e in enriched):
            enriched.append(tw_counterpart)

    return enriched


async def resolve_taiwan_counterpart(
    target_name: str,
    content_raw: str,
    provider=None
) -> Optional[Dict[str, Any]]:
    """Discover and resolve Taiwan/localized counterpart for regional projects."""
    combined = f"{target_name} {content_raw[:1000]}".lower()

    # Regional indicators: topics like 润学 / 走线 / 出海 / 墙内 / 移民
    regional_keywords = ["润学", "出海", "移民", "墙内", "走线", "海外求职", "海外工作", "run"]
    if not any(k in combined for k in regional_keywords):
        return None

    # Search Taiwan developer counterpart repositories
    tw_queries = ["f2etw/jobs", "goodjack/developer-roadmap-chinese"]
    for q in tw_queries:
        candidates = await search_github_repositories(q, limit=1)
        if candidates:
            c = candidates[0]
            if "f2etw" in c["full_name"].lower():
                return {
                    "name": "f2etw/jobs",
                    "canonical_url": c["html_url"],
                    "reason": f"[台灣對等資源] 台灣前端與全端工程師海外與遠端職缺看板 (★{c['stars']:,}) · 提供日本/歐美遠端與簽證出海機會",
                    "status": "verified",
                    "stars": c["stars"],
                    "matched_name": c["full_name"]
                }
            elif "developer-roadmap" in c["full_name"].lower():
                return {
                    "name": "developer-roadmap-chinese",
                    "canonical_url": c["html_url"],
                    "reason": f"[台灣對等資源] 開發者技術路線圖台灣繁中版 (★{c['stars']:,}) · 涵蓋技術面試與出海指南",
                    "status": "verified",
                    "stars": c["stars"],
                    "matched_name": c["full_name"]
                }
    return None
