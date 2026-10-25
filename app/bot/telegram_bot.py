"""
OmniKeep Telegram Private Ingestion Bot
Allows forwarding links, articles, and text notes directly into your Second Brain.
Uses httpx for lightweight, zero-dependency async Telegram Bot API polling.
Decoupled architecture: Ingestion loop acknowledges in <50ms and persists to SQLite;
Background worker executes dual-stream analysis and asynchronously renders cards.
"""

import asyncio
import html
import json
import logging
import re
from typing import Optional, Dict, Any, List
import httpx

from app.config import settings
from app.database import (
    get_items,
    get_item_by_id,
    update_item_field,
    get_status_counts,
    create_ingest_task,
    get_user_setting,
    set_user_setting,
    get_swipe_deck,
    log_behavior_event,
    get_proposals,
    get_proposal,
    decide_proposal
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

async def notify_task_completed(chat_id: int, message_id: int, item: Dict[str, Any]):
    """Worker notification: renders finished intelligence card in place"""
    bot = get_telegram_bot()
    if not bot:
        return
    try:
        card = bot.build_item_card_html(item)
        kb = bot.build_item_keyboard(item)
        await bot.edit_message_text(chat_id, message_id, card, reply_markup=kb)
    except Exception as e:
        logger.warning(f"[Telegram Complete] Failed to render card ({chat_id}:{message_id}): {e}")

async def notify_task_failed(chat_id: int, message_id: int, error_text: str):
    """Worker notification: updates error state in place"""
    bot = get_telegram_bot()
    if not bot:
        return
    try:
        err_msg = f"❌ <b>情報處理失敗</b>\n\n原因: <code>{html.escape(error_text)}</code>"
        await bot.edit_message_text(chat_id, message_id, err_msg)
    except Exception as e:
        logger.warning(f"[Telegram Failed] Failed to update error ({chat_id}:{message_id}): {e}")

def build_mode_keyboard(current_mode: str) -> Dict[str, Any]:
    heartbeat_check = " ✅" if current_mode == "heartbeat" else ""
    quiet_check = " ✅" if current_mode == "quiet" else ""
    return {
        "inline_keyboard": [
            [
                {"text": f"💓 心跳模式{heartbeat_check}", "callback_data": "set_mode:heartbeat"},
                {"text": f"🤫 安靜模式{quiet_check}", "callback_data": "set_mode:quiet"}
            ]
        ]
    }

def build_deck_keyboard(item_id: str) -> Dict[str, Any]:
    """P1 swipe deck: 👍/👎/⭐ are training labels, 💤 re-queues only (never a label)."""
    return {
        "inline_keyboard": [
            [
                {"text": "👍 想看", "callback_data": f"swipe_up:{item_id}"},
                {"text": "⭐ 收藏", "callback_data": f"swipe_star:{item_id}"},
                {"text": "💤 稍後", "callback_data": f"snooze:{item_id}"},
                {"text": "👎 略過", "callback_data": f"swipe_down:{item_id}"},
            ]
        ]
    }

def build_proposal_keyboard(proposal_id: str) -> Dict[str, Any]:
    return {
        "inline_keyboard": [
            [
                {"text": "✅ 核准", "callback_data": f"prop:{proposal_id}:approve"},
                {"text": "💤 稍後", "callback_data": f"prop:{proposal_id}:snooze"},
                {"text": "❌ 忽略", "callback_data": f"prop:{proposal_id}:dismiss"},
            ]
        ]
    }

def build_deck_card_html(item: Dict[str, Any], remaining: int) -> str:
    tags = " ".join(f"#{t}" for t in (item.get("tech_tags") or [])[:4])
    title = html.escape(item.get("title_l1", ""))
    summary = html.escape((item.get("summary_l1") or "")[:200])
    return (
        f"🃏 <b>雷達滑卡</b> <i>（剩 {remaining} 張）</i>\n\n"
        f"<b>{title}</b>\n"
        f"{summary}\n\n"
        f"<i>{html.escape(tags)}</i>\n\n"
        f"<i>👍/👎/⭐ 會教會 OmniKeep 你的品味；💤 稍後明天再出現，不算意見。</i>"
    )

def build_proposal_card_html(prop: Dict[str, Any]) -> str:
    title = html.escape(prop.get("title_l1") or "（無標題）")
    summary = html.escape((prop.get("summary_l1") or "")[:150])
    return (
        f"🔭 <b>提案卡</b>\n\n<b>{title}</b>\n{summary}\n\n"
        f"🎯 影響 {prop.get('impact', '?')} · 🔍 信心 {prop.get('confidence', '?')} · 🏗️ 成本 {prop.get('effort', '?')}"
    )

class TelegramBot:
    def __init__(self, token: Optional[str] = None):
        self.token = token or settings.TELEGRAM_BOT_TOKEN
        if not self.token:
            raise ValueError("TELEGRAM_BOT_TOKEN 未配置，請於 .env 填入 Bot Token。")
        self.api_url = f"https://api.telegram.org/bot{self.token}"
        self.running = False
        self._client: Optional[httpx.AsyncClient] = None

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

    async def send_message(
        self,
        chat_id: int,
        text: str,
        parse_mode: str = "HTML",
        reply_markup: Optional[Dict[str, Any]] = None,
        reply_to_message_id: Optional[int] = None
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True
        }
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
        reply_markup: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True
        }
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
        category = html.escape(item.get("category_name", "Inbox"))
        source = html.escape(item.get("source_type", "web").upper())
        summary = html.escape(item.get("summary_l1", ""))
        tags = [f"#{html.escape(t)}" for t in item.get("tech_tags", [])]
        tags_str = " ".join(tags)

        url = item.get("url", "")
        url_line = ""
        if url.startswith("http"):
            clean_url = html.escape(url.split("#snippet-")[0])
            url_line = f"\n🔗 <a href=\"{clean_url}\">前往原始來源</a>"

        card = (
            f"🧠 <b>[{category}] {title}</b>\n"
            f"<i>來源: {source}</i>\n\n"
            f"⚡ <b>白話核心痛點與解法：</b>\n"
            f"{summary}\n\n"
            f"🏷️ <b>技術標籤：</b>\n"
            f"<code>{tags_str}</code>"
            f"{url_line}"
        )
        return card

    def build_item_keyboard(self, item: Dict[str, Any]) -> Dict[str, Any]:
        item_id = item.get("id")
        is_starred = item.get("is_starred", 0)
        is_read = item.get("is_read", 0)

        star_btn = {
            "text": "⭐ 已星標" if is_starred else "☆ 加星標",
            "callback_data": f"star:{item_id}"
        }
        archive_btn = {
            "text": "✅ 已封存" if is_read else "📦 封存 (Archive)",
            "callback_data": f"archive:{item_id}"
        }
        detail_btn = {
            "text": "📊 L2 深入剖析",
            "callback_data": f"detail:{item_id}"
        }

        row1 = [star_btn, archive_btn]
        row2 = [detail_btn]

        url = item.get("url", "")
        if url.startswith("http"):
            row2.append({
                "text": "🌐 原始網址",
                "url": url.split("#snippet-")[0]
            })

        return {"inline_keyboard": [row1, row2]}

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

        # Authorization check & First-time Auto-pairing
        if not self.is_authorized(user_id):
            allowed = settings.telegram_allowed_ids
            if not allowed:
                logger.info(f"Auto-pairing initial Telegram user as owner: {user_id}")
                settings.TELEGRAM_ALLOWED_USER_IDS_RAW = str(user_id)
                try:
                    import dotenv
                    dotenv.set_key(".env", "TELEGRAM_ALLOWED_USER_IDS", str(user_id))
                except Exception as e:
                    logger.warning(f"Failed to persist TELEGRAM_ALLOWED_USER_IDS to .env: {e}")

                await self.send_message(
                    chat_id,
                    f"🎉 <b>OmniKeep 擁有者驗證成功！</b>\n\n"
                    f"已將你的帳號 (<code>{user_id}</code>) 綁定為安全白名單。\n"
                    f"第二大腦現已全功能就緒！"
                )
            else:
                msg = f"⛔ <b>未授權的存取</b>。你的 User ID (<code>{user_id}</code>) 不在允許名單中。"
                await self.send_message(chat_id, msg)
                return

        # Commands
        if text.startswith("/start") or text.startswith("/help"):
            help_text = (
                f"🧠 <b>OmniKeep 第二大腦情報採集 Bot</b>\n\n"
                f"已成功驗證！你的 User ID: <code>{user_id}</code>\n\n"
                f"<b>使用方式：</b>\n"
                f"• <b>隨手轉發/貼上</b>：直接發送任何網址、YouTube 或短影音連結，後端佇列即時收件並非同步解析。\n"
                f"• <b>指令支援：</b>\n"
                f"  /deck - 🃏 雷達滑卡（👍/👎/⭐ 教它你的品味，💤 稍後）\n"
                f"  /proposals - 🔭 待決提案卡（核准／忽略）\n"
                f"  /mode [heartbeat|quiet] - 切換即時心跳或安靜模式\n"
                f"  /stats - 查看大腦庫存與待讀數量\n"
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
                    desc = "心跳模式（即時原地編輯狀態心跳）" if target_mode == "heartbeat" else "安靜模式（僅提示排隊，完成時一次性刷出情報卡片）"
                    await self.send_message(
                        chat_id,
                        f"⚙️ <b>互動模式已更新</b>\n\n目前設定為：<b>{target_mode.upper()}</b>\n說明：{desc}",
                        reply_markup=build_mode_keyboard(target_mode)
                    )
                    return
            current_mode = get_user_setting(chat_id)
            desc = "心跳模式（即時原地編輯狀態心跳）" if current_mode == "heartbeat" else "安靜模式（僅提示排隊，完成時一次性刷出情報卡片）"
            msg = (
                f"⚙️ <b>OmniKeep 互動模式設定</b>\n\n"
                f"目前模式：<b>{current_mode.upper()}</b>\n"
                f"說明：{desc}\n\n"
                f"• <b>/mode heartbeat</b>：原地編輯心跳（📥 排隊 → ⚡ 下載音影 → 🔍 雙軌解構 → 完成卡片）\n"
                f"• <b>/mode quiet</b>：安靜模式（僅回覆排隊，完成時一次性原地刷出情報卡片）\n\n"
                f"請點擊下方按鈕切換偏好："
            )
            await self.send_message(chat_id, msg, reply_markup=build_mode_keyboard(current_mode))
            return

        if text.startswith("/stats"):
            stats = get_status_counts()
            stats_text = (
                f"📊 <b>OmniKeep 第二大腦即時庫存</b>\n\n"
                f"📥 待讀 Inbox：<b>{stats.get('inbox', 0)}</b> 篇\n"
                f"⭐ 星標精選：<b>{stats.get('starred', 0)}</b> 篇\n"
                f"📦 已封存：<b>{stats.get('archived', 0)}</b> 篇\n"
                f"📚 總計情報：<b>{stats.get('total', 0)}</b> 篇"
            )
            await self.send_message(chat_id, stats_text)
            return

        if text.startswith("/inbox"):
            items = get_items(is_read=False, limit=5)
            if not items:
                await self.send_message(chat_id, "🎉 待讀 Inbox 目前是空的！零負擔。")
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
            await self.send_message(chat_id, f"🔍 找到 {len(items)} 筆與「{html.escape(query)}」相關的情報：")
            for item in items:
                card = self.build_item_card_html(item)
                kb = self.build_item_keyboard(item)
                await self.send_message(chat_id, card, reply_markup=kb)
            return

        if text.startswith("/deck"):
            from app.watch.taste import rank_deck
            deck = rank_deck(get_swipe_deck(limit=50))
            if not deck:
                await self.send_message(chat_id, "🎉 雷達滑卡全部清空！等雷達進貨後再來 /deck。")
                return
            card = build_deck_card_html(deck[0], len(deck))
            await self.send_message(chat_id, card, reply_markup=build_deck_keyboard(deck[0]["id"]))
            return

        if text.startswith("/proposals"):
            props = get_proposals(status="pending", limit=3)
            if not props:
                await self.send_message(chat_id, "🔭 目前沒有待決提案。用 /deck 滑雷達卡，或到工作台「監看中心」看看。")
                return
            for p in props:
                item = get_item_by_id(p["item_id"]) or {}
                p["title_l1"] = item.get("title_l1", "")
                p["summary_l1"] = item.get("summary_l1", "")
                await self.send_message(chat_id, build_proposal_card_html(p),
                                        reply_markup=build_proposal_keyboard(p["id"]))
            return

        # Normal Content Ingestion (Hoarder Fast Queueing: <50ms acknowledge)
        if not text:
            await self.send_message(chat_id, "請發送網址或文字段落。")
            return

        mode = get_user_setting(chat_id)
        if mode == "quiet":
            initial_status = "📥 <b>已收件排隊中 (Quiet 模式)...</b>"
        else:
            initial_status = "📥 <b>已加入處理佇列，準備啟動雙軌解析...</b>"

        wait_msg = await self.send_message(
            chat_id,
            initial_status,
            reply_to_message_id=message.get("message_id")
        )
        wait_msg_id = wait_msg.get("result", {}).get("message_id")

        # Persist to SQLite Task Queue (Immediate non-blocking return)
        create_ingest_task(
            url=text,
            source="telegram",
            chat_id=chat_id,
            message_id=wait_msg_id
        )

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
                desc = "心跳模式（即時原地編輯狀態心跳）" if target_mode == "heartbeat" else "安靜模式（僅提示排隊，完成時一次性刷出情報卡片）"
                msg = (
                    f"⚙️ <b>OmniKeep 互動模式設定</b>\n\n"
                    f"目前模式：<b>{target_mode.upper()}</b>\n"
                    f"說明：{desc}\n\n"
                    f"• <b>/mode heartbeat</b>：原地編輯心跳（📥 排隊 → ⚡ 下載音影 → 🔍 雙軌解構 → 完成卡片）\n"
                    f"• <b>/mode quiet</b>：安靜模式（僅回覆排隊，完成時一次性原地刷出情報卡片）\n\n"
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
            log_behavior_event(action, item_id=item_id, source="telegram")
            # P2: true labels feed the radar topic-weight engine (💤 never does)
            from app.watch.taste import apply_swipe_learning
            apply_swipe_learning(action, item_id)
            if action in ("swipe_up", "swipe_down"):
                update_item_field(item_id, {"is_read": 1})
            elif action == "swipe_star":
                update_item_field(item_id, {"is_read": 1, "is_starred": 1})
            # snooze: no state change — the deck query hides snoozed cards for a day

            from app.watch.taste import rank_deck
            deck = rank_deck(get_swipe_deck(limit=50))
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
                    "text": "🎉 雷達滑卡全部清空！明天再來 /deck。",
                    "parse_mode": "HTML",
                    "reply_markup": {"inline_keyboard": []},
                })
            toasts = {"swipe_up": "已記錄 👍", "swipe_star": "已收藏 ⭐",
                      "swipe_down": "已略過 👎", "snooze": "明天再見 💤"}
            await self.answer_callback_query(query_id, toasts[action])
            return

        # ── Proposal decide buttons: prop:<id>:approve|dismiss|snooze ──
        if action == "prop":
            prop_id, _, verb = item_id.partition(":")
            if verb not in ("approve", "dismiss", "snooze"):
                await self.answer_callback_query(query_id)
                return
            log_behavior_event(f"proposal_{verb}", proposal_id=prop_id, source="telegram")
            status_note = "💤 稍後再議"
            if verb in ("approve", "dismiss"):
                decided = decide_proposal(prop_id, "approved" if verb == "approve" else "dismissed")
                status_note = "✅ 已核准" if verb == "approve" else "❌ 已忽略"
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
            await self.answer_callback_query(query_id, "已標記為星標 ⭐" if next_star else "已取消星標")

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
            await self.answer_callback_query(query_id, "已歸檔至封存區 📦" if next_read else "已移回待讀 Inbox 📥")

        elif action == "detail":
            await self.answer_callback_query(query_id, "正在調出 L2 架構剖析...")
            deep = item.get("deep_analysis", "")
            if not deep:
                deep = "此項目無深入剖析內容。"

            escaped_deep = html.escape(deep)
            if len(escaped_deep) > 3800:
                escaped_deep = escaped_deep[:3800] + "\n\n<i>...(過長已截斷)...</i>"

            detail_msg = (
                f"📊 <b>L2 深度技術架構解構：{html.escape(item.get('title_l1', ''))}</b>\n\n"
                f"<pre>{escaped_deep}</pre>"
            )
            await self.send_message(chat_id, detail_msg)

    async def run_polling(self):
        self.running = True
        offset = 0
        client = await self.get_client()

        print("=" * 60)
        print("🤖 OmniKeep Telegram Private Ingest Bot 已啟動")
        print(f"📡 Polling 模式運行中 (Ctrl+C 停止)...")
        if settings.telegram_allowed_ids:
            print(f"🔒 授權白名單 User IDs: {settings.telegram_allowed_ids}")
        else:
            print("⚠️ 尚未設定 TELEGRAM_ALLOWED_USER_IDS，首次私訊時 Bot 會回傳你的 User ID。")
        print("=" * 60)

        while self.running:
            try:
                resp = await client.get(
                    f"{self.api_url}/getUpdates",
                    params={"offset": offset, "timeout": 25}
                )
                if resp.status_code != 200:
                    await asyncio.sleep(3)
                    continue

                data = resp.json()
                if not data.get("ok"):
                    logger.error(f"Telegram API 錯誤: {data}")
                    await asyncio.sleep(3)
                    continue

                for update in data.get("result", []):
                    offset = update["update_id"] + 1
                    try:
                        await self.handle_update(update)
                    except Exception as e:
                        logger.exception(f"處理 Telegram Update 失敗: {e}")

            except httpx.TimeoutException:
                continue
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Polling 異常: {e}")
                await asyncio.sleep(3)

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
        task_worker.start()
        try:
            await bot.run_polling()
        finally:
            await task_worker.stop()
            await bot.close()

    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        print("\nTelegram Bot 已安全停止。")

if __name__ == "__main__":
    run_bot()
