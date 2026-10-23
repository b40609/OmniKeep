"""
OmniKeep Telegram Private Ingestion Bot
Allows forwarding links, articles, and text notes directly into your Second Brain.
Uses httpx for lightweight, zero-dependency async Telegram Bot API polling.
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
    get_status_counts
)
from app.pipeline import run_pipeline

logger = logging.getLogger("omnikeep.telegram_bot")

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
            # If empty, nobody is authorized for security
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
                # Auto-pair first user as owner and persist to .env
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
                f"• <b>隨手轉發/貼上</b>：直接發送任何網址、YouTube 連結或技術長文段落，AI 會在幾秒內提煉 L1/L2 情報並入庫。\n"
                f"• <b>指令支援</b>：\n"
                f"  /stats - 查看大腦庫存與待讀數量\n"
                f"  /inbox - 檢視最近 5 則未讀情報\n"
                f"  /search [關鍵字] - 快速檢索庫存"
            )
            await self.send_message(chat_id, help_text)
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

        # Normal Content Ingestion (URL or Raw Text / Forward)
        if not text:
            await self.send_message(chat_id, "請發送網址或文字段落。")
            return

        # 1. Send initial progress message
        wait_msg = await self.send_message(
            chat_id,
            "⚡ <b>已收到內容，正在由 AI 深入解析情報架構 (L1/L2)...</b>",
            reply_to_message_id=message.get("message_id")
        )
        wait_msg_id = wait_msg.get("result", {}).get("message_id")

        # 2. Run Ingest Pipeline
        try:
            item = await run_pipeline(text)
            card = self.build_item_card_html(item)
            kb = self.build_item_keyboard(item)

            if wait_msg_id:
                await self.edit_message_text(chat_id, wait_msg_id, card, reply_markup=kb)
            else:
                await self.send_message(chat_id, card, reply_markup=kb)

        except Exception as e:
            err_msg = f"❌ <b>情報存入失敗</b>\n\n原因: <code>{html.escape(str(e))}</code>"
            if wait_msg_id:
                await self.edit_message_text(chat_id, wait_msg_id, err_msg)
            else:
                await self.send_message(chat_id, err_msg)

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

            # Clean markdown for Telegram HTML
            escaped_deep = html.escape(deep)
            # Truncate if exceeding Telegram 4000 char limit
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

    bot = TelegramBot()
    try:
        asyncio.run(bot.run_polling())
    except KeyboardInterrupt:
        print("\nTelegram Bot 已安全停止。")

if __name__ == "__main__":
    run_bot()
