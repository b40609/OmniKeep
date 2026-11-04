"""
OmniKeep Telegram Private Ingestion Bot
Allows forwarding links, articles, and text notes directly into your Second Brain.
Uses httpx for lightweight, zero-dependency async Telegram Bot API polling.
Decoupled architecture: Ingestion loop acknowledges in <50ms and persists to SQLite;
Background worker executes dual-stream analysis and asynchronously renders cards.
"""

import asyncio
import html
import inspect
import json
import logging
import re
from typing import Optional, Dict, Any, List
import httpx

from app.bot.telegram_pairing import bind_telegram_user, redeem_pairing_code
from app.config import settings
from app.database import (
    get_ingest_task,
    get_db_connection,
    update_task_status,
    get_items,
    get_item_by_id,
    update_item_field,
    get_status_counts,
    create_ingest_task,
    set_ingest_task_message_id,
    get_user_setting,
    set_user_setting,
    get_swipe_deck,
    log_behavior_event,
    get_proposals,
    get_proposal,
    decide_proposal,
    get_interest_profile_record,
    set_interest_profile,
    get_sub_entities_for_parent
)

logger = logging.getLogger("omnikeep.telegram_bot")

_bot_instance: Optional["TelegramBot"] = None

def get_telegram_bot() -> Optional["TelegramBot"]:
    """Global singleton access to TelegramBot for asynchronous notifications"""
    global _bot_instance
    if not settings.TELEGRAM_BOT_TOKEN:
        return None
    if _bot_instance is None:
        _bot_instance = TelegramBot()
    return _bot_instance

async def notify_task_heartbeat(chat_id: int, message_id: int, text: str):
    """Worker notification: updates progress heartbeat in place"""
    bot = get_telegram_bot()
    if not bot:
        return
    try:
        await bot.edit_message_text(chat_id, message_id, text)
    except Exception as e:
        logger.warning(f"[Telegram Heartbeat] Failed to update ({chat_id}:{message_id}): {e}")

def build_failure_keyboard(task_id: Optional[str] = None, message_id: Optional[int] = None) -> Dict[str, Any]:
    buttons = []
    if task_id:
        buttons.append({"text": "🔄 重新解析", "callback_data": f"retry_task:{task_id}"})
    if message_id:
        buttons.append({"text": "🗑️ 刪除", "callback_data": f"delete_msg:{message_id}"})
    return {"inline_keyboard": [buttons]} if buttons else {"inline_keyboard": []}

async def notify_task_completed(chat_id: int, message_id: int, item: Dict[str, Any], *, strict: bool = False, task_id: Optional[str] = None):
    """Worker notification: renders finished intelligence card in place or as reply"""
    bot = get_telegram_bot()
    if not bot:
        if strict:
            raise RuntimeError("Telegram bot unavailable for completion delivery")
        return
    try:
        card = bot.build_item_card_html(item)
        kb = bot.build_item_keyboard(item, mode="summary")
        link_opts = None
        if item.get("cover_image"):
            link_opts = {
                "is_disabled": False,
                "url": item["cover_image"],
                "prefer_large_media": True,
                "show_above_text": True
            }
        result = await bot.edit_message_text(chat_id, message_id, card, reply_markup=kb, link_preview_options=link_opts)
        if isinstance(result, dict) and result.get("ok") is False:
            description = str(result.get("description", "Telegram API error"))
            if "message is not modified" not in description.lower():
                send_call = bot.send_message(
                    chat_id, card, reply_markup=kb,
                    reply_to_message_id=message_id,
                    link_preview_options=link_opts
                )
                send_res = await send_call if inspect.isawaitable(send_call) else send_call
                if strict:
                    if not isinstance(send_res, dict) or send_res.get("ok") is False:
                        raise RuntimeError(f"Telegram completion delivery: {description}")
        rx = bot.set_message_reaction(chat_id, message_id, "✅")
        if inspect.isawaitable(rx):
            await rx
    except Exception as e:
        logger.warning(f"[Telegram Complete] Failed to render card ({chat_id}:{message_id}): {e}")
        if strict:
            raise

async def notify_task_failed(chat_id: int, message_id: int, error_text: str):
    """Worker notification: updates error state with actionable retry and cleanup buttons"""
    bot = get_telegram_bot()
    if not bot:
        return
    try:
        task_id = None
        try:
            conn = get_db_connection()
            row = conn.execute(
                "SELECT id FROM ingest_tasks WHERE chat_id = ? AND message_id = ? ORDER BY created_at DESC LIMIT 1",
                (chat_id, message_id)
            ).fetchone()
            conn.close()
            if row:
                task_id = row["id"]
        except Exception:
            pass

        err_msg = f"⚠️ <b>情報處理失敗</b>\n\n原因: <code>{html.escape(error_text)}</code>"
        kb = build_failure_keyboard(task_id=task_id, message_id=message_id)
        result = await bot.edit_message_text(chat_id, message_id, err_msg, reply_markup=kb)
        if isinstance(result, dict) and result.get("ok") is False:
            description = str(result.get("description", "Telegram API error"))
            logger.warning(f"[Telegram Failed] Telegram rejected edit ({chat_id}:{message_id}): {description}")
            send_call = bot.send_message(chat_id, err_msg, reply_markup=kb, reply_to_message_id=message_id)
            if inspect.isawaitable(send_call):
                await send_call
        rx = bot.set_message_reaction(chat_id, message_id, "⚠️")
        if inspect.isawaitable(rx):
            await rx
    except Exception as e:
        logger.warning(f"[Telegram Failed] Failed to update error ({chat_id}:{message_id}): {e}")

def build_mode_keyboard(current_mode: str) -> Dict[str, Any]:
    heartbeat_check = " ✓" if current_mode == "heartbeat" else ""
    quiet_check = " ✓" if current_mode == "quiet" else ""
    return {
        "inline_keyboard": [
            [
                {"text": f"即時心跳{heartbeat_check}", "callback_data": "set_mode:heartbeat"},
                {"text": f"靜默模式{quiet_check}", "callback_data": "set_mode:quiet"}
            ]
        ]
    }

def build_deck_keyboard(item_id: str) -> Dict[str, Any]:
    """P1 swipe deck: 👍/👎/⭐ are training labels, 💤 re-queues only (never a label)."""
    return {
        "inline_keyboard": [
            [
                {"text": "保留", "callback_data": f"swipe_up:{item_id}"},
                {"text": "收藏", "callback_data": f"swipe_star:{item_id}"},
                {"text": "💤 稍後", "callback_data": f"snooze:{item_id}"},
                {"text": "略過", "callback_data": f"swipe_down:{item_id}"},
            ]
        ]
    }

def build_proposal_keyboard(proposal_id: str) -> Dict[str, Any]:
    return {
        "inline_keyboard": [
            [
                {"text": "核准", "callback_data": f"prop:{proposal_id}:approve"},
                {"text": "💤 稍後", "callback_data": f"prop:{proposal_id}:snooze"},
                {"text": "忽略", "callback_data": f"prop:{proposal_id}:dismiss"},
            ]
        ]
    }

def build_dreampass_keyboard(proposal_id: int) -> Dict[str, Any]:
    return {
        "inline_keyboard": [
            [
                {"text": "採用調整", "callback_data": f"dreampass:{proposal_id}:apply"},
                {"text": "忽略", "callback_data": f"dreampass:{proposal_id}:dismiss"},
            ]
        ]
    }

def build_dreampass_card_html(prop: Dict[str, Any]) -> str:
    obs = html.escape(str(prop.get("observations", "")))
    sug = html.escape(str(prop.get("suggested_profile", "")))
    diff = html.escape(str(prop.get("diff_summary", "")))
    return (
        f"<b>Dream Pass 偏好自省</b>\n\n"
        f"<b>近期偏好觀察</b>\n{obs}\n\n"
        f"<b>建議調整方向</b>\n<code>{diff}</code>\n\n"
        f"<b>調整後畫像描述</b>\n<i>{sug}</i>\n\n"
        f"點擊下方按鈕以核准更新畫像："
    )

def build_deck_card_html(item: Dict[str, Any], remaining: int) -> str:
    tags = " ".join(f"#{t}" for t in (item.get("tech_tags") or [])[:4])
    title = html.escape(item.get("title_l1", ""))
    summary = html.escape((item.get("summary_l1") or "")[:200])
    reasons = [str(r) for r in (item.get("reasons") or []) if str(r)]
    reason_block = ""
    if reasons:
        shown = "\n".join(f"· {html.escape(r)}" for r in reasons[:3])
        reason_block = f"\n<b>為什麼給你看：</b>\n{shown}\n"
    return (
        f"<b>雷達候選情報</b> <i>（剩 {remaining} 張）</i>\n\n"
        f"<b>{title}</b>\n"
        f"{summary}\n"
        f"{reason_block}\n"
        f"<i>{html.escape(tags)}</i>\n\n"
        f"<i>👍/👎/⭐ 會教會 OmniKeep 你的品味；稍後明天再出現，不算意見。</i>"
    )

def build_proposal_card_html(prop: Dict[str, Any]) -> str:
    title = html.escape(prop.get("title_l1") or "（無標題）")
    summary = html.escape((prop.get("summary_l1") or "")[:200])
    deep = prop.get("deep_analysis") or ""
    evidence_block = ""
    if "雙邊證據鏈" in deep or "模組與結論" in deep:
        lines = []
        for line in deep.split("\n"):
            line_s = line.strip()
            if any(line_s.startswith(prefix) for prefix in (
                "- **建議改動模組**：",
                "- **外部情報依據**：",
                "- **本機現狀依據**：",
                "- **最小改動步驟**：",
                "- **驗收方式**："
            )):
                clean = line_s.lstrip("- ").replace("**", "").replace("`", "")
                lines.append(f"· {html.escape(clean)}")
        if lines:
            evidence_block = "\n<b>📋 模組與證據鏈：</b>\n" + "\n".join(lines[:4]) + "\n"

    return (
        f"🔭 <b>模組提案卡</b>\n\n<b>{title}</b>\n{summary}\n"
        f"{evidence_block}\n"
        f"🎯 影響 {prop.get('impact', '?')} · 🔍 信心 {prop.get('confidence', '?')} · 🏗️ 成本 {prop.get('effort', '?')}"
    )

def markdown_to_telegram_html(text: str) -> str:
    """
    Robust Markdown to Telegram HTML converter.
    Telegram HTML only supports: <b>, <i>, <u>, <s>, <a>, <code>, <pre>, <blockquote>.
    """
    if not text:
        return ""

    code_blocks = []
    def save_code_block(match):
        code = match.group(2)
        idx = len(code_blocks)
        code_blocks.append(code)
        return f"\n__CODE_BLOCK_{idx}__\n"

    cleaned = re.sub(r'```([a-zA-Z0-9_\-\+]*)\n?(.*?)```', save_code_block, text, flags=re.DOTALL)
    lines = cleaned.splitlines()
    out_lines = []

    def format_inline(s: str) -> str:
        s = re.sub(r'`([^`]+)`', r'<code>\1</code>', s)
        s = re.sub(r'\*\*([^*]+)\*\*', r'<b>\1</b>', s)
        s = re.sub(r'__([^_]+)__', r'<b>\1</b>', s)
        s = re.sub(r'(?<!\*)\*([^*]+)\*(?!\*)', r'<i>\1</i>', s)
        s = re.sub(r'\[([^\]]+)\]\((https?://[^\s)]+)\)', r'<a href="\2">\1</a>', s)
        return s

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("__CODE_BLOCK_") and stripped.endswith("__"):
            out_lines.append(stripped)
            continue
        if not stripped:
            out_lines.append("")
            continue

        # Header
        m_head = re.match(r'^(#{1,6})\s+(.+)$', line)
        if m_head:
            header_text = html.escape(m_head.group(2).strip())
            out_lines.append(f"<b>{format_inline(header_text)}</b>")
            continue

        # Blockquote
        m_quote = re.match(r'^>\s*(.+)$', line)
        if m_quote:
            q_text = html.escape(m_quote.group(1).strip())
            out_lines.append(f"<blockquote>{format_inline(q_text)}</blockquote>")
            continue

        # Bullet list
        m_bullet = re.match(r'^(\s*)[-*+•]\s+(.+)$', line)
        if m_bullet:
            indent = "  " if len(m_bullet.group(1)) >= 2 else ""
            b_text = html.escape(m_bullet.group(2).strip())
            out_lines.append(f"{indent}• {format_inline(b_text)}")
            continue

        # Ordered list
        m_num = re.match(r'^(\s*)(\d+)\.\s+(.+)$', line)
        if m_num:
            indent = "  " if len(m_num.group(1)) >= 2 else ""
            n_text = html.escape(m_num.group(3).strip())
            out_lines.append(f"{indent}{m_num.group(2)}. {format_inline(n_text)}")
            continue

        # Normal line
        norm_text = html.escape(line)
        out_lines.append(format_inline(norm_text))

    assembled = "\n".join(out_lines)
    for idx, code in enumerate(code_blocks):
        escaped_code = html.escape(code.strip())
        assembled = assembled.replace(f"__CODE_BLOCK_{idx}__", f"<pre><code>{escaped_code}</code></pre>")

    return re.sub(r'\n{3,}', '\n\n', assembled).strip()

class TelegramBot:
    def __init__(self, token: Optional[str] = None):
        self.token = token or settings.TELEGRAM_BOT_TOKEN
        if not self.token:
            raise ValueError("TELEGRAM_BOT_TOKEN 未配置，請於 .env 填入 Bot Token。")
        self.api_url = f"https://api.telegram.org/bot{self.token}"
        self.running = False
        self._client: Optional[httpx.AsyncClient] = None
        self._username: Optional[str] = None

    async def get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=45.0)
        return self._client

    async def close(self):
        self.running = False
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    def is_authorized(self, user_id: int) -> bool:
        allowed = settings.telegram_allowed_ids
        if not allowed:
            return False
        return user_id in allowed

    async def send_api(self, method: str, data: Dict[str, Any]) -> Dict[str, Any]:
        client = await self.get_client()
        resp = await client.post(f"{self.api_url}/{method}", json=data)
        return resp.json()

    async def get_username(self) -> Optional[str]:
        """The bot's @username (for t.me links), looked up once with getMe."""
        if not self._username:
            res = await self.send_api("getMe", {})
            self._username = (res.get("result") or {}).get("username")
        return self._username

    async def pair(self, chat: Dict[str, Any], user_id: int, code: str):
        """Bind the sender of a one-time pairing link (/start <code>) as an owner."""
        chat_id = chat.get("id")
        if chat.get("type") != "private" or not user_id:
            await self.send_message(chat_id, "⛔ 只能在與 Bot 的私人對話中配對。")
            return
        if not redeem_pairing_code(code):
            await self.send_message(chat_id, "⛔ <b>配對連結無效或已過期</b>。請在 OmniKeep 網頁的「設定 → Telegram」重新產生。")
            return
        earlier_owners = [owner for owner in settings.telegram_allowed_ids if owner != user_id]
        persisted = bind_telegram_user(user_id)
        logger.warning("Telegram user %s bound as an owner through a pairing link", user_id)
        await self.send_message(
            chat_id,
            f"🎉 <b>已綁定為 OmniKeep 擁有者</b>（<code>{user_id}</code>）。傳 /help 看看能做什麼。"
            + ("" if persisted else "\n\n⚠️ 綁定沒有存進資料庫，重新啟動後需要再配對一次。"),
        )
        for owner in earlier_owners:
            await self.send_message(
                owner,
                f"🔐 Telegram 帳號 <code>{user_id}</code> 剛透過配對連結取得 OmniKeep 存取權。"
                f"如果不是你操作的，請到 OmniKeep 網頁的「設定 → Telegram」移除它。",
            )

    async def set_message_reaction(self, chat_id: int, message_id: int, emoji: str = "") -> bool:
        """Set or clear emoji reaction on a message (Telegram Bot API 7.0+)"""
        try:
            payload: Dict[str, Any] = {
                "chat_id": chat_id,
                "message_id": message_id,
                "reaction": [{"type": "emoji", "emoji": emoji}] if emoji else []
            }
            res = await self.send_api("setMessageReaction", payload)
            return bool(res.get("ok"))
        except Exception as e:
            logger.debug(f"[Telegram Reaction] Notice: {e}")
            return False

    async def delete_message(self, chat_id: int, message_id: int) -> bool:
        """Delete a message from chat"""
        try:
            res = await self.send_api("deleteMessage", {"chat_id": chat_id, "message_id": message_id})
            return bool(res.get("ok"))
        except Exception as e:
            logger.warning(f"[Telegram Delete] Failed: {e}")
            return False

    async def send_message(
        self,
        chat_id: int,
        text: str,
        parse_mode: str = "HTML",
        reply_markup: Optional[Dict[str, Any]] = None,
        reply_to_message_id: Optional[int] = None,
        link_preview_options: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode,
        }
        if link_preview_options is not None:
            payload["link_preview_options"] = link_preview_options
        else:
            payload["disable_web_page_preview"] = True
        if reply_markup:
            payload["reply_markup"] = reply_markup
        if reply_to_message_id:
            payload["reply_to_message_id"] = reply_to_message_id
        return await self.send_api("sendMessage", payload)

    async def edit_message_text(
        self,
        chat_id: int,
        message_id: int,
        text: str,
        parse_mode: str = "HTML",
        reply_markup: Optional[Dict[str, Any]] = None,
        link_preview_options: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
            "parse_mode": parse_mode,
        }
        if link_preview_options is not None:
            payload["link_preview_options"] = link_preview_options
        else:
            payload["disable_web_page_preview"] = True
        if reply_markup:
            payload["reply_markup"] = reply_markup
        return await self.send_api("editMessageText", payload)

    async def answer_callback_query(self, callback_query_id: str, text: str = "", show_alert: bool = False):
        await self.send_api("answerCallbackQuery", {
            "callback_query_id": callback_query_id,
            "text": text,
            "show_alert": show_alert
        })

    def build_item_card_html(self, item: Dict[str, Any]) -> str:
        title = html.escape(item.get("title_l1", "未命名情報"))
        category = html.escape(item.get("category_name", "INBOX")).upper()
        source = html.escape(item.get("source_type", "WEB")).upper()
        author = html.escape((item.get("author") or "").strip())
        summary = html.escape((item.get("summary_l1") or "").strip())

        # Extract user note from content_raw if present
        user_note = ""
        content_raw = item.get("content_raw", "")
        if "## 使用者隨手筆記" in content_raw:
            m_note = re.search(r'## 使用者隨手筆記(?:/備忘)?\s*\n+(.*?)\n\n', content_raw, re.DOTALL)
            if m_note:
                user_note = m_note.group(1).strip()

        # Metadata line: [CATEGORY] · Author · SOURCE
        meta_parts = [f"<code>{category}</code>"]
        if author and author.upper() not in (source, "WEB", "THREADS", "YOUTUBE", "BILIBILI"):
            meta_parts.append(author)
        meta_parts.append(source)
        meta_line = " · ".join(meta_parts)

        # Tech tags pills
        raw_tags = item.get("tech_tags", [])
        if isinstance(raw_tags, str):
            try:
                raw_tags = json.loads(raw_tags)
            except Exception:
                raw_tags = [t.strip() for t in raw_tags.split(",") if t.strip()]

        tags_section = ""
        if raw_tags:
            tag_pills = " ".join(f"<code>{html.escape(t)}</code>" for t in raw_tags[:6])
            tags_section = f"\n\n<b>關鍵技術</b>\n{tag_pills}"

        note_section = ""
        if user_note:
            note_section = f"\n\n💡 <b>個人備忘</b>：<i>{html.escape(user_note)}</i>"

        # Mentioned open-source tools & sub-entities
        tools_section = ""
        item_id = item.get("id")
        if item_id:
            try:
                sub_entities = get_sub_entities_for_parent(item_id)
                if sub_entities:
                    competitor_items = []
                    taiwan_items = []
                    verified_items = []
                    candidate_items = []
                    for sub in sub_entities:
                        t_name = html.escape(sub.get("target_name") or "開源專案")
                        t_url = sub.get("target_canonical_url") or ""
                        ctx = html.escape((sub.get("mention_context") or "").strip())
                        if t_url:
                            link_markup = f"<a href=\"{html.escape(t_url)}\">{t_name}</a>"
                        else:
                            link_markup = f"<b>{t_name}</b>"

                        if "[庫內競品]" in ctx:
                            ctx_clean = ctx.replace("[庫內競品]", "").strip(" ·-")
                            competitor_items.append(
                                f"• <b>同賽道競品</b>：{link_markup}" + (f"\n  <i>💡 {ctx_clean}</i>" if ctx_clean else "")
                            )
                        elif "[上位替代]" in ctx:
                            ctx_clean = ctx.replace("[上位替代]", "").strip(" ·-")
                            competitor_items.append(
                                f"• <b>上位替代</b>：{link_markup}" + (f"\n  <i>💡 {ctx_clean}</i>" if ctx_clean else "")
                            )
                        elif "[庫內重複]" in ctx:
                            ctx_clean = ctx.replace("[庫內重複]", "").strip(" ·-")
                            competitor_items.append(
                                f"• <b>重複收錄</b>：{link_markup}" + (f"\n  <i>💡 {ctx_clean}</i>" if ctx_clean else "")
                            )
                        elif "[台灣對等資源]" in ctx:
                            ctx_clean = ctx.replace("[台灣對等資源]", "").strip(" ·-")
                            taiwan_items.append(
                                f"• {link_markup}" + (f" — {ctx_clean}" if ctx_clean else "")
                            )
                        elif "[疑似候選]" in ctx:
                            ctx_clean = ctx.replace("[疑似候選]", "").strip(" ·-")
                            candidate_items.append(
                                f"• {link_markup}" + (f" — {ctx_clean}" if ctx_clean else "")
                            )
                        else:
                            verified_items.append(
                                f"• {link_markup}" + (f" — {ctx}" if ctx else "")
                            )

                    if competitor_items:
                        tools_section += f"\n\n⚖️ <b>庫內競品與關聯提醒</b>\n" + "\n".join(competitor_items[:3])

                    if taiwan_items:
                        tools_section += f"\n\n🇹🇼 <b>台灣/在地對等資源</b>\n" + "\n".join(taiwan_items[:3])

                    if verified_items:
                        has_hf = any("huggingface.co" in x for x in verified_items)
                        has_gh = any("github.com" in x for x in verified_items)
                        count_suffix = f" ({len(verified_items)})" if len(verified_items) > 1 else ""
                        if has_hf and has_gh:
                            section_title = f"📦 🤗 <b>提及專案與 AI 模型{count_suffix}</b>"
                        elif has_hf:
                            section_title = f"🤗 <b>提及 AI 模型 / 權重{count_suffix}</b>"
                        else:
                            section_title = f"📦 <b>提及開源專案{count_suffix}</b>"

                        max_verified = 8
                        tools_section += f"\n\n{section_title}\n" + "\n".join(verified_items[:max_verified])
                        if len(verified_items) > max_verified:
                            rem = len(verified_items) - max_verified
                            tools_section += f"\n<i>...以及另外 {rem} 個專案（可點擊「深入剖析」查看全貌）</i>"
                    if candidate_items:
                        count_cand = f" ({len(candidate_items)})" if len(candidate_items) > 1 else ""
                        max_cand = 5
                        tools_section += f"\n\n🔍 <b>疑似提及專案（未確認{count_cand}）</b>\n" + "\n".join(candidate_items[:max_cand])
                        if len(candidate_items) > max_cand:
                            rem_cand = len(candidate_items) - max_cand
                            tools_section += f"\n<i>...以及另外 {rem_cand} 個候選專案</i>"
            except Exception as e:
                logger.debug(f"[Telegram Card] Error getting sub-entities: {e}")

        card = (
            f"<b>{title}</b>\n"
            f"{meta_line}\n\n"
            f"<blockquote>{summary}</blockquote>"
            f"{note_section}"
            f"{tools_section}"
            f"{tags_section}"
        )
        return card

    def build_item_keyboard(self, item: Dict[str, Any], mode: str = "summary") -> Dict[str, Any]:
        item_id = item.get("id")
        is_starred = item.get("is_starred", 0)
        is_read = item.get("is_read", 0)

        star_btn = {
            "text": "★ 已收藏" if is_starred else "☆ 收藏",
            "callback_data": f"star:{item_id}"
        }
        archive_btn = {
            "text": "✓ 已封存" if is_read else "封存",
            "callback_data": f"archive:{item_id}"
        }
        
        if mode == "detail":
            toggle_btn = {
                "text": "▴ 收合摘要",
                "callback_data": f"collapse:{item_id}"
            }
        else:
            toggle_btn = {
                "text": "深入剖析 ▾",
                "callback_data": f"detail:{item_id}"
            }

        row1 = [toggle_btn]
        url = item.get("url", "")
        if url.startswith("http"):
            clean_url = url.split("#")[0]
            row1.append({
                "text": "原始來源 ↗",
                "url": clean_url
            })

        # Extra tool repository buttons if verified GitHub project attached (up to 4, max 2 per row)
        rows = [row1]
        if item_id:
            try:
                sub_entities = get_sub_entities_for_parent(item_id)
                tool_btns = []
                for sub in sub_entities:
                    t_url = sub.get("target_canonical_url") or ""
                    t_name = sub.get("target_name") or ""
                    ctx = sub.get("mention_context") or ""
                    if t_url.startswith("http") and "[疑似候選]" not in ctx:
                        clean_name = re.sub(r'^[📦🤗\s]+', '', t_name).strip()
                        prefix = "🤗" if "huggingface.co" in t_url else "📦"
                        btn_label = f"{prefix} {clean_name[:12]} ↗"
                        tool_btns.append({
                            "text": btn_label,
                            "url": t_url
                        })
                        if len(tool_btns) >= 4:
                            break
                if tool_btns:
                    for i in range(0, len(tool_btns), 2):
                        rows.append(tool_btns[i:i + 2])
            except Exception:
                pass

        row_actions = [star_btn, archive_btn]
        rows.append(row_actions)

        return {"inline_keyboard": rows}

    async def handle_update(self, update: Dict[str, Any]):
        # 1. Callback query (Button click)
        if "callback_query" in update:
            await self.handle_callback(update["callback_query"])
            return

        # 2. Message (Text, link, forward)
        message = update.get("message")
        if not message:
            return

        chat_id = message["chat"]["id"]
        from_user = message.get("from", {})
        user_id = from_user.get("id", 0)
        text = (message.get("text") or message.get("caption") or "").strip()

        # A one-time pairing link from the web app arrives as "/start <code>".
        start = re.fullmatch(r"/start(?:@\w+)?\s+(\S+)", text)
        if start:
            await self.pair(message.get("chat", {}), user_id, start.group(1))
            return

        # Only owners get further. Messaging first binds nobody.
        if not self.is_authorized(user_id):
            if not settings.telegram_allowed_ids:
                msg = (
                    f"⚠️ <b>OmniKeep Bot 尚未綁定擁有者</b>\n\n"
                    f"請在 OmniKeep 網頁開啟「設定 → Telegram」，按「產生 Telegram 配對連結」，再用這個帳號開啟連結。\n"
                    f"你的 User ID 是 <code>{user_id}</code>。"
                )
            else:
                msg = f"⛔ <b>未授權的存取</b>。你的 User ID (<code>{user_id}</code>) 不在允許名單中。"
            await self.send_message(chat_id, msg)
            return

        # Commands
        if text.startswith("/start") or text.startswith("/help"):
            help_text = (
                f"<b>OmniKeep 情報工作台</b>\n\n"
                f"已成功驗證！你的 User ID: <code>{user_id}</code>\n\n"
                f"<b>使用方式：</b>\n"
                f"• <b>隨手轉發/貼上</b>：直接發送任何網址、YouTube 或短影音連結，後端佇列即時收件並非同步解析。\n"
                f"• <b>指令支援：</b>\n"
                f"  /deck - 🃏 雷達滑卡（👍/👎/⭐ 教它你的品味，稍後）\n"
                f"  /proposals - 待決提案審閱（核准 / 忽略）\n"
                f"  /mode [heartbeat|quiet] - 切換即時心跳或安靜模式\n"
                f"  /stats - 庫存狀態統計\n"
                f"  /profile [內容] - 檢視或更新自由文字興趣設定檔（織入 LLM Prompt）\n"
                f"  /inbox - 檢視最近 5 則未讀情報\n"
                f"  /search [關鍵字] - 快速檢索庫存"
            )
            await self.send_message(chat_id, help_text)
            return

        if text.startswith("/mode"):
            parts = text.split()
            if len(parts) > 1:
                target_mode = parts[1].lower().strip()
                if target_mode in ("heartbeat", "quiet"):
                    set_user_setting(chat_id, target_mode)
                    desc = "即時心跳（原地更新處理進度）" if target_mode == "heartbeat" else "安靜模式（僅提示排隊，完成時一次性刷出情報卡片）"
                    await self.send_message(
                        chat_id,
                        f"⚙️ <b>互動模式已更新</b>\n\n目前設定為：<b>{target_mode.upper()}</b>\n說明：{desc}",
                        reply_markup=build_mode_keyboard(target_mode)
                    )
                    return
            current_mode = get_user_setting(chat_id)
            desc = "即時心跳（原地更新處理進度）" if current_mode == "heartbeat" else "安靜模式（僅提示排隊，完成時一次性刷出情報卡片）"
            msg = (
                f"⚙️ <b>OmniKeep 互動模式設定</b>\n\n"
                f"目前模式：<b>{current_mode.upper()}</b>\n"
                f"說明：{desc}\n\n"
                f"• <b>/mode heartbeat</b>：即時心跳（排隊、多模態解構、卡片輸出）\n"
                f"• <b>/mode quiet</b>：靜默模式（確認收件後一次性呈現卡片）\n\n"
                f"請點擊下方按鈕切換偏好："
            )
            await self.send_message(chat_id, msg, reply_markup=build_mode_keyboard(current_mode))
            return

        if text.startswith("/rules"):
            from app.database import get_all_rules
            rules = get_all_rules()
            if not rules:
                await self.send_message(chat_id, "⚙️ <b>硬規則引擎</b>\n\n目前尚未建立任何自動化規則。可在工作台設定或透過 API 建立。")
                return
            lines = [f"⚙️ <b>硬規則引擎（共 {len(rules)} 條）</b>\n"]
            for r in rules:
                status = "🟢" if r.get("is_active") else "⚪"
                name = html.escape(r.get("name", "未命名"))
                field = r.get("field")
                op = r.get("operator")
                val = html.escape(r.get("value", ""))
                act = r.get("action_type")
                act_v = html.escape(r.get("action_value", ""))
                lines.append(f"{status} <b>{name}</b> (優先級 {r.get('priority', 10)})\n   條件: <code>{field} {op} '{val}'</code>\n   動作: <code>{act} {act_v}</code>")
            await self.send_message(chat_id, "\n\n".join(lines))
            return

        if text.startswith("/stats"):
            stats = get_status_counts()
            stats_text = (
                f"<b>庫存狀態統計</b>\n\n"
                f"待讀收件匣：<b>{stats.get('inbox', 0)}</b> 篇\n"
                f"精選收藏：<b>{stats.get('starred', 0)}</b> 篇\n"
                f"已封存：<b>{stats.get('archived', 0)}</b> 篇\n"
                f"總計收錄：<b>{stats.get('total', 0)}</b> 篇"
            )
            await self.send_message(chat_id, stats_text)
            return

        if text.startswith("/inbox"):
            items = get_items(is_read=False, limit=5)
            if not items:
                await self.send_message(chat_id, "待讀收件匣目前為空。")
                return
            for item in items:
                card = self.build_item_card_html(item)
                kb = self.build_item_keyboard(item)
                await self.send_message(chat_id, card, reply_markup=kb)
            return

        if text.startswith("/search"):
            query = text.replace("/search", "", 1).strip()
            if not query:
                await self.send_message(chat_id, "請在指令後加上搜尋關鍵字，例如：<code>/search OpenHands</code>")
                return
            items = get_items(query=query, limit=5)
            if not items:
                await self.send_message(chat_id, f"找不到與「{html.escape(query)}」相關的情報。")
                return
            await self.send_message(chat_id, f"找到 {len(items)} 筆與「{html.escape(query)}」相關的情報：")
            for item in items:
                card = self.build_item_card_html(item)
                kb = self.build_item_keyboard(item)
                await self.send_message(chat_id, card, reply_markup=kb)
            return

        if text.startswith("/deck"):
            deck = get_swipe_deck(limit=50)
            if not deck:
                await self.send_message(chat_id, "雷達卡片已審閱完畢。")
                return
            card = build_deck_card_html(deck[0], len(deck))
            await self.send_message(chat_id, card, reply_markup=build_deck_keyboard(deck[0]["id"]))
            return

        if text.startswith("/proposals"):
            props = get_proposals(status="pending", limit=3)
            if not props:
                await self.send_message(chat_id, "目前無待決提案。")
                return
            for p in props:
                item = get_item_by_id(p["item_id"]) or {}
                p["title_l1"] = item.get("title_l1", "")
                p["summary_l1"] = item.get("summary_l1", "")
                p["deep_analysis"] = item.get("deep_analysis", "")
                await self.send_message(chat_id, build_proposal_card_html(p),
                                        reply_markup=build_proposal_keyboard(p["id"]))
            return

        if text.startswith("/profile"):
            parts = text.split(maxsplit=1)
            if len(parts) > 1:
                new_profile = parts[1].strip()
                set_interest_profile(new_profile)
                await self.send_message(
                    chat_id,
                    f"✅ <b>興趣設定檔已更新</b>（{len(new_profile)} 字）：\n\n"
                    f"{html.escape(new_profile)}"
                )
            else:
                rec = get_interest_profile_record()
                prof = rec["profile"] or "（尚未設定）"
                updated = rec["updated_at"] or "無"
                await self.send_message(
                    chat_id,
                    f"📝 <b>當前興趣設定檔</b>（更新時間：{html.escape(str(updated))}）：\n\n"
                    f"{html.escape(prof)}\n\n"
                    f"<i>提示：輸入 <code>/profile 你的興趣與專案方向...</code> 可直接更新設定檔。</i>"
                )
            return

        if text.startswith("/dreampass"):
            from app.database import get_latest_dreampass_proposal
            from app.radar.dreampass import run_dreampass_reflection
            prop = get_latest_dreampass_proposal(status="pending")
            if not prop:
                await self.send_message(chat_id, "⏳ 正在分析近 7 天互動數據進行品味自省，請稍候...")
                prop = await run_dreampass_reflection(days=7)
            card = build_dreampass_card_html(prop)
            await self.send_message(chat_id, card, reply_markup=build_dreampass_keyboard(prop["id"]))
            return

        # Normal Content Ingestion (Multi-URL & Note extraction with Emoji Reaction)
        if not text:
            await self.send_message(chat_id, "請發送網址或文字段落。")
            return

        # Extract all URLs
        found_urls = re.findall(r'https?://[^\s<>"\'\)]+', text)
        clean_urls = []
        for u in found_urls:
            u = u.rstrip(".,;:!?)]}>\"'")
            if u and u not in clean_urls:
                clean_urls.append(u)

        user_msg_id = message.get("message_id")
        mode = get_user_setting(chat_id)

        # 1. If URLs are present:
        if clean_urls:
            if user_msg_id:
                try:
                    await self.set_message_reaction(chat_id, user_msg_id, "⚡")
                except Exception:
                    pass

            # Extract residual text as user note
            residual = text
            for u in found_urls:
                residual = residual.replace(u, "")
            user_note = re.sub(r'\s+', ' ', residual).strip()

            tasks = []
            for idx, target_url in enumerate(clean_urls):
                url_with_note = target_url
                if user_note:
                    from urllib.parse import quote
                    url_with_note = f"{target_url}#note={quote(user_note)}"

                task_dedupe = str(user_msg_id or update.get("update_id"))
                if len(clean_urls) > 1:
                    task_dedupe += f"_{idx}"

                task = create_ingest_task(
                    url=url_with_note,
                    source="telegram",
                    chat_id=chat_id,
                    message_id=None,
                    dedupe_key=task_dedupe
                )
                if task.get("message_id") is not None:
                    # Replayed update already has a receipt attached
                    return
                tasks.append(task)

            if not tasks:
                return

            initial_status = "<b>[Queued] 已加入處理佇列，啟動解析...</b>" if len(clean_urls) == 1 else f"<b>[Queued] 已收到 {len(clean_urls)} 則連結，排入批次解析...</b>"
            try:
                wait_msg = await self.send_message(
                    chat_id,
                    initial_status,
                    reply_to_message_id=user_msg_id
                )
                wait_msg_id = wait_msg.get("result", {}).get("message_id")
                if wait_msg_id:
                    for t in tasks:
                        set_ingest_task_message_id(t["id"], wait_msg_id)
            except Exception:
                logger.exception("Telegram receipt failed for persisted task %s", tasks[0]["id"])
            return

        # 2. Pure text note (no URLs)
        if user_msg_id:
            try:
                await self.set_message_reaction(chat_id, user_msg_id, "⚡")
            except Exception:
                pass

        task = create_ingest_task(
            url=text,
            source="telegram",
            chat_id=chat_id,
            message_id=None,
            dedupe_key=str(user_msg_id or update.get("update_id"))
        )
        if task.get("message_id") is not None:
            return

        try:
            wait_msg = await self.send_message(
                chat_id,
                "<b>[Queued] 筆記已排入處理佇列...</b>",
                reply_to_message_id=user_msg_id
            )
            wait_msg_id = wait_msg.get("result", {}).get("message_id")
            if wait_msg_id:
                set_ingest_task_message_id(task["id"], wait_msg_id)
        except Exception:
            logger.exception("Telegram receipt failed for persisted task %s", task["id"])

    async def handle_callback(self, query: Dict[str, Any]):
        query_id = query["id"]
        from_user = query.get("from", {})
        user_id = from_user.get("id", 0)
        data = query.get("data", "")
        message = query.get("message", {})
        chat_id = message.get("chat", {}).get("id")
        message_id = message.get("message_id")

        if not self.is_authorized(user_id):
            await self.answer_callback_query(query_id, "未授權的操作", show_alert=True)
            return

        if ":" not in data:
            await self.answer_callback_query(query_id)
            return

        action, item_id = data.split(":", 1)

        # Mode toggle callback
        if action == "set_mode":
            target_mode = item_id.lower().strip()
            if target_mode in ("heartbeat", "quiet"):
                set_user_setting(chat_id, target_mode)
                await self.answer_callback_query(query_id, f"已切換為 {target_mode.upper()} 模式")
                desc = "即時心跳（原地更新處理進度）" if target_mode == "heartbeat" else "安靜模式（僅提示排隊，完成時一次性刷出情報卡片）"
                msg = (
                    f"⚙️ <b>OmniKeep 互動模式設定</b>\n\n"
                    f"目前模式：<b>{target_mode.upper()}</b>\n"
                    f"說明：{desc}\n\n"
                    f"• <b>/mode heartbeat</b>：即時心跳（排隊、多模態解構、卡片輸出）\n"
                    f"• <b>/mode quiet</b>：靜默模式（確認收件後一次性呈現卡片）\n\n"
                    f"請點擊下方按鈕切換偏好："
                )
                await self.send_api("editMessageText", {
                    "chat_id": chat_id,
                    "message_id": message_id,
                    "text": msg,
                    "parse_mode": "HTML",
                    "reply_markup": build_mode_keyboard(target_mode)
                })
            return

        # ── P1 swipe deck: 👍/👎/⭐ = training labels, 💤 snooze = re-queue only ──
        if action in ("swipe_up", "swipe_down", "swipe_star", "snooze"):
            item = get_item_by_id(item_id)
            if not item:
                await self.answer_callback_query(query_id, "找不到此項目", show_alert=True)
                return
            from app.database import record_swipe
            record_swipe(action, item_id, source="telegram")
            deck = get_swipe_deck(limit=50)
            if deck:
                await self.send_api("editMessageText", {
                    "chat_id": chat_id,
                    "message_id": message_id,
                    "text": build_deck_card_html(deck[0], len(deck)),
                    "parse_mode": "HTML",
                    "reply_markup": build_deck_keyboard(deck[0]["id"]),
                })
            else:
                await self.send_api("editMessageText", {
                    "chat_id": chat_id,
                    "message_id": message_id,
                    "text": "雷達卡片已審閱完畢。",
                    "parse_mode": "HTML",
                    "reply_markup": {"inline_keyboard": []},
                })
            toasts = {"swipe_up": "已保留", "swipe_star": "已收藏",
                      "swipe_down": "已略過", "snooze": "已保留於佇列"}
            await self.answer_callback_query(query_id, toasts[action])
            return

        # ── Proposal decide buttons: prop:<id>:approve|dismiss|snooze ──
        if action == "prop":
            prop_id, _, verb = item_id.partition(":")
            if verb not in ("approve", "dismiss", "snooze"):
                await self.answer_callback_query(query_id)
                return
            log_behavior_event(f"proposal_{verb}", proposal_id=prop_id, source="telegram")
            status_note = "稍後再議"
            if verb in ("approve", "dismiss"):
                decided = decide_proposal(prop_id, "approved" if verb == "approve" else "dismissed")
                status_note = "已核准" if verb == "approve" else "已忽略"
                if not decided:
                    await self.answer_callback_query(query_id, "提案不存在", show_alert=True)
                    return
            prop = get_proposal(prop_id)
            if prop:
                prop["title_l1"] = (get_item_by_id(prop["item_id"]) or {}).get("title_l1", "")
                await self.send_api("editMessageText", {
                    "chat_id": chat_id,
                    "message_id": message_id,
                    "text": build_proposal_card_html(prop) + f"\n\n<b>{status_note}</b>",
                    "parse_mode": "HTML",
                    "reply_markup": {"inline_keyboard": []},
                })
            await self.answer_callback_query(query_id, status_note)
            return

        # ── Dream Pass decide buttons: dreampass:<id>:apply|dismiss ──
        if action == "dreampass":
            prop_id_str, _, verb = item_id.partition(":")
            try:
                p_id = int(prop_id_str)
            except ValueError:
                await self.answer_callback_query(query_id, "無效的自省編號")
                return
            if verb == "apply":
                from app.database import apply_dreampass_proposal
                ok = apply_dreampass_proposal(p_id)
                msg = "✅ 已成功採用自省建議，興趣畫像已更新！" if ok else "自省提案已過期或已處理"
                await self.answer_callback_query(query_id, msg)
                await self.send_api("editMessageText", {
                    "chat_id": chat_id,
                    "message_id": message_id,
                    "text": f"<b>偏好畫像調整完成</b>\n\n{msg}",
                    "parse_mode": "HTML",
                    "reply_markup": {"inline_keyboard": []},
                })
            elif verb == "dismiss":
                from app.database import dismiss_dreampass_proposal
                dismiss_dreampass_proposal(p_id)
                await self.answer_callback_query(query_id, "已忽略此次建議")
                await self.send_api("editMessageText", {
                    "chat_id": chat_id,
                    "message_id": message_id,
                    "text": "<b>偏好畫像調整已忽略</b>\n\n保留原興趣畫像不變。",
                    "parse_mode": "HTML",
                    "reply_markup": {"inline_keyboard": []},
                })
            return

        if action == "retry_task":
            task_id = item_id
            t = get_ingest_task(task_id)
            if not t:
                await self.answer_callback_query(query_id, "找不到此任務", show_alert=True)
                return
            update_task_status(task_id, status="queued", error_message=None)
            conn = get_db_connection()
            conn.execute("UPDATE ingest_tasks SET retry_count = 0 WHERE id = ?", (task_id,))
            conn.commit()
            conn.close()
            await self.answer_callback_query(query_id, "已排入重試佇列")
            await self.edit_message_text(
                chat_id, message_id,
                f"<b>⏳ 正在重新排隊解析中...</b>\n\n<code>{html.escape(t.get('url', ''))}</code>",
                reply_markup={"inline_keyboard": []}
            )
            if t.get("message_id"):
                await self.set_message_reaction(chat_id, t["message_id"], "⚡")
            return

        if action == "delete_msg":
            target_msg_id = int(item_id) if item_id.isdigit() else message_id
            await self.delete_message(chat_id, target_msg_id)
            await self.answer_callback_query(query_id, "已清除訊息")
            return

        item = get_item_by_id(item_id)
        if not item:
            await self.answer_callback_query(query_id, "找不到此項目", show_alert=True)
            return

        if action == "star":
            next_star = 0 if item.get("is_starred") else 1
            update_item_field(item_id, {"is_starred": next_star})
            item["is_starred"] = next_star
            kb = self.build_item_keyboard(item)
            await self.send_api("editMessageReplyMarkup", {
                "chat_id": chat_id,
                "message_id": message_id,
                "reply_markup": kb
            })
            await self.answer_callback_query(query_id, "已加入收藏" if next_star else "已取消收藏")

        elif action == "archive":
            next_read = 0 if item.get("is_read") else 1
            update_item_field(item_id, {"is_read": next_read})
            item["is_read"] = next_read
            kb = self.build_item_keyboard(item)
            await self.send_api("editMessageReplyMarkup", {
                "chat_id": chat_id,
                "message_id": message_id,
                "reply_markup": kb
            })
            await self.answer_callback_query(query_id, "已封存" if next_read else "已移回待讀")

        elif action == "detail":
            await self.answer_callback_query(query_id, "展開架構深析")
            deep = item.get("deep_analysis", "") or "此項目無深入剖析內容。"
            formatted_deep = markdown_to_telegram_html(deep)

            title = html.escape(item.get("title_l1", ""))
            category = html.escape(item.get("category_name", "INBOX")).upper()
            source = html.escape(item.get("source_type", "WEB")).upper()

            # 提及開源專案（深析模式全量呈現）
            tools_block = ""
            if item_id:
                try:
                    sub_entities = get_sub_entities_for_parent(item_id)
                    if sub_entities:
                        tool_lines = []
                        for sub in sub_entities:
                            t_name = html.escape(sub.get("target_name") or "開源專案")
                            t_url = sub.get("target_canonical_url") or ""
                            ctx = html.escape((sub.get("mention_context") or "").strip())
                            link = f"<a href=\"{html.escape(t_url)}\">{t_name}</a>" if t_url else f"<b>{t_name}</b>"
                            tool_lines.append(f"• {link}" + (f" — {ctx}" if ctx else ""))
                        if tool_lines:
                            tools_block = f"\n\n📦 <b>提及開源專案清單 ({len(tool_lines)})</b>\n" + "\n".join(tool_lines)
                except Exception as e:
                    logger.debug(f"[Telegram Detail] Error getting sub-entities: {e}")

            max_deep_len = 3800 - len(tools_block)
            if len(formatted_deep) > max_deep_len:
                formatted_deep = formatted_deep[:max_deep_len] + "\n\n<i>...(全文篇幅較長，請於 Web 閱讀完整內容)...</i>"

            detail_card = (
                f"<b>{title}</b>\n"
                f"<code>{category}</code> · <b>架構深析</b> · {source}\n\n"
                f"{formatted_deep}"
                f"{tools_block}"
            )
            kb = self.build_item_keyboard(item, mode="detail")
            await self.send_api("editMessageText", {
                "chat_id": chat_id,
                "message_id": message_id,
                "text": detail_card,
                "parse_mode": "HTML",
                "reply_markup": kb,
                "disable_web_page_preview": True
            })

        elif action == "collapse":
            await self.answer_callback_query(query_id, "收合摘要")
            card = self.build_item_card_html(item)
            kb = self.build_item_keyboard(item, mode="summary")
            link_opts = None
            if item.get("cover_image"):
                link_opts = {
                    "is_disabled": False,
                    "url": item["cover_image"],
                    "prefer_large_media": True,
                    "show_above_text": True
                }
            await self.edit_message_text(
                chat_id, message_id, card, reply_markup=kb, link_preview_options=link_opts
            )



    async def run_polling(self):
        self.running = True
        offset = 0
        client = await self.get_client()

        logger.warning("Telegram polling started (authorized users: %d)", len(settings.telegram_allowed_ids))

        while self.running:
            try:
                resp = await client.get(
                    f"{self.api_url}/getUpdates",
                    params={"offset": offset, "timeout": 25}
                )
                if resp.status_code != 200:
                    logger.warning("Telegram polling HTTP status %s", resp.status_code)
                    await asyncio.sleep(3)
                    continue

                data = resp.json()
                if not data.get("ok"):
                    logger.error(f"Telegram API 錯誤: {data}")
                    await asyncio.sleep(3)
                    continue

                for update in data.get("result", []):
                    try:
                        await self.handle_update(update)
                    except Exception as e:
                        # Keep the failing update unacknowledged so it can be
                        # replayed; earlier updates have durable dedupe keys.
                        logger.exception("Telegram update %s not yet persisted: %s", update.get("update_id"), e)
                        await asyncio.sleep(3)
                        break
                    offset = update["update_id"] + 1

            except httpx.TimeoutException:
                continue
            except asyncio.CancelledError:
                self.running = False
                raise
            except Exception as e:
                logger.error("Polling 異常 (%s)", type(e).__name__)
                await asyncio.sleep(3)
        self.running = False

def run_bot():
    if not settings.TELEGRAM_BOT_TOKEN:
        print("=" * 60)
        print("OmniKeep Telegram Bot")
        print("請先於 .env 設定 TELEGRAM_BOT_TOKEN 才能啟動 Bot。")
        print("教學請參閱 docs/telegram_bot.md")
        print("=" * 60)
        return

    from app.queue.worker import task_worker

    async def _main():
        bot = TelegramBot()
        global _bot_instance
        _bot_instance = bot
        # Start background queue worker
        from app.background import follow_up_pool
        follow_up_pool.start()
        worker_started = False
        try:
            task_worker.start()
            worker_started = True
            await bot.run_polling()
        finally:
            try:
                try:
                    if worker_started:
                        await task_worker.stop()
                finally:
                    await follow_up_pool.stop()
            finally:
                await bot.close()

    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        print("\nTelegram Bot 已安全停止。")

if __name__ == "__main__":
    run_bot()
