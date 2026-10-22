"""
OmniKeep LINE Messaging API Private Ingestion Bot
Allows sending/sharing links, articles, and text notes from LINE directly into OmniKeep.
Uses standard library hmac/hashlib + httpx (zero external dependencies).
"""

import hmac
import hashlib
import base64
import json
import logging
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

logger = logging.getLogger("omnikeep.line_bot")

LINE_API_BASE = "https://api.line.me/v2/bot"

def verify_line_signature(body_bytes: bytes, signature: Optional[str]) -> bool:
    secret = settings.LINE_CHANNEL_SECRET
    if not secret or not signature:
        return False
    hash_val = hmac.new(secret.encode("utf-8"), body_bytes, hashlib.sha256).digest()
    expected = base64.b64encode(hash_val).decode("utf-8")
    return hmac.compare_digest(expected, signature)

def is_line_user_authorized(user_id: str) -> bool:
    allowed = settings.line_allowed_ids
    if not allowed:
        return False
    return user_id in allowed

async def send_line_api(endpoint: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    token = settings.LINE_CHANNEL_ACCESS_TOKEN
    if not token:
        raise ValueError("LINE_CHANNEL_ACCESS_TOKEN 未配置。")

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.post(f"{LINE_API_BASE}/{endpoint}", headers=headers, json=payload)
        try:
            return resp.json()
        except Exception:
            return {"status_code": resp.status_code, "text": resp.text}

async def start_line_loading(chat_id: str, seconds: int = 15):
    """Starts the native LINE chat loading animation (three bouncing dots)."""
    try:
        await send_line_api("chat/loading/start", {
            "chatId": chat_id,
            "loadingSeconds": min(seconds, 60)
        })
    except Exception as e:
        logger.debug(f"Failed to start loading animation: {e}")

async def reply_line_messages(reply_token: str, messages: List[Dict[str, Any]]) -> Dict[str, Any]:
    return await send_line_api("message/reply", {
        "replyToken": reply_token,
        "messages": messages
    })

async def push_line_messages(to_user_id: str, messages: List[Dict[str, Any]]) -> Dict[str, Any]:
    return await send_line_api("message/push", {
        "to": to_user_id,
        "messages": messages
    })

def create_item_flex_bubble(item: Dict[str, Any]) -> Dict[str, Any]:
    """Generates an industrial-grade dark theme Flex Message bubble for LINE."""
    title = item.get("title_l1", "未命名情報")
    category = item.get("category_name", "Inbox")
    source = item.get("source_type", "web").upper()
    summary = item.get("summary_l1", "")
    item_id = item.get("id", "")
    url = item.get("url", "")
    is_starred = item.get("is_starred", 0)
    is_read = item.get("is_read", 0)

    tags = item.get("tech_tags", [])
    tag_str = " ".join([f"#{t}" for t in tags[:4]]) if tags else "#情報"

    bubble = {
        "type": "bubble",
        "size": "mega",
        "styles": {
            "header": {"backgroundColor": "#18181b"},
            "body": {"backgroundColor": "#09090b"},
            "footer": {"backgroundColor": "#18181b"}
        },
        "header": {
            "type": "box",
            "layout": "vertical",
            "paddingAll": "16px",
            "contents": [
                {
                    "type": "box",
                    "layout": "horizontal",
                    "contents": [
                        {
                            "type": "text",
                            "text": f"[{category}]",
                            "color": "#818cf8",
                            "size": "xs",
                            "weight": "bold",
                            "flex": 0
                        },
                        {
                            "type": "text",
                            "text": f"• {source}",
                            "color": "#71717a",
                            "size": "xs",
                            "margin": "sm",
                            "flex": 0
                        }
                    ]
                },
                {
                    "type": "text",
                    "text": title,
                    "color": "#fafafa",
                    "weight": "bold",
                    "size": "md",
                    "wrap": True,
                    "margin": "sm"
                }
            ]
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "paddingAll": "16px",
            "contents": [
                {
                    "type": "text",
                    "text": "⚡ 白話核心重點：",
                    "color": "#a1a1aa",
                    "size": "xs",
                    "weight": "bold"
                },
                {
                    "type": "text",
                    "text": summary,
                    "color": "#e4e4e7",
                    "size": "xs",
                    "wrap": True,
                    "margin": "xs",
                    "lineSpacing": "3px"
                },
                {
                    "type": "separator",
                    "margin": "lg",
                    "color": "#27272a"
                },
                {
                    "type": "text",
                    "text": tag_str,
                    "color": "#818cf8",
                    "size": "xxs",
                    "margin": "md",
                    "wrap": True
                }
            ]
        },
        "footer": {
            "type": "box",
            "layout": "horizontal",
            "spacing": "sm",
            "paddingAll": "12px",
            "contents": [
                {
                    "type": "button",
                    "style": "secondary",
                    "height": "sm",
                    "color": "#27272a",
                    "action": {
                        "type": "postback",
                        "label": "⭐ 已星標" if is_starred else "☆ 加星標",
                        "data": f"action=star&id={item_id}"
                    }
                },
                {
                    "type": "button",
                    "style": "secondary",
                    "height": "sm",
                    "color": "#27272a",
                    "action": {
                        "type": "postback",
                        "label": "✅ 已封存" if is_read else "📦 封存",
                        "data": f"action=archive&id={item_id}"
                    }
                }
            ]
        }
    }

    # Add external URL button if it's a real HTTP link
    if url.startswith("http"):
        clean_url = url.split("#snippet-")[0]
        bubble["footer"]["contents"].append({
            "type": "button",
            "style": "primary",
            "height": "sm",
            "color": "#4f46e5",
            "action": {
                "type": "uri",
                "label": "🌐 原始頁",
                "uri": clean_url
            }
        })

    return {
        "type": "flex",
        "altText": f"🧠 [{category}] {title}",
        "contents": bubble
    }

async def process_line_event(event: Dict[str, Any]):
    """Processes a single incoming LINE event (Message or Postback)."""
    event_type = event.get("type")
    source = event.get("source", {})
    user_id = source.get("userId", "")
    reply_token = event.get("replyToken")

    # 1. Authorization Gate
    if not is_line_user_authorized(user_id):
        allowed = settings.line_allowed_ids
        if not allowed:
            msg = (
                f"⚠️ OmniKeep LINE Bot 尚未綁定擁有者\n\n"
                f"你的 LINE User ID 是：\n{user_id}\n\n"
                f"請將此 ID 填入 .env 的 LINE_ALLOWED_USER_IDS 即可完成綁定！"
            )
        else:
            msg = f"⛔ 未授權的 LINE 帳號。\n你的 ID: {user_id}"

        if reply_token:
            await reply_line_messages(reply_token, [{"type": "text", "text": msg}])
        return

    # 2. Postback Action (Star / Archive clicks)
    if event_type == "postback":
        data_str = event.get("postback", {}).get("data", "")
        params = dict(p.split("=") for p in data_str.split("&") if "=" in p)
        action = params.get("action")
        item_id = params.get("id")

        item = get_item_by_id(item_id) if item_id else None
        if not item:
            if reply_token:
                await reply_line_messages(reply_token, [{"type": "text", "text": "找不到該項目。"}])
            return

        if action == "star":
            next_star = 0 if item.get("is_starred") else 1
            update_item_field(item_id, {"is_starred": next_star})
            msg_text = "已標記為星標 ⭐" if next_star else "已取消星標"
            if reply_token:
                await reply_line_messages(reply_token, [{"type": "text", "text": f"[{item.get('title_l1')[:20]}] {msg_text}"}])

        elif action == "archive":
            next_read = 0 if item.get("is_read") else 1
            update_item_field(item_id, {"is_read": next_read})
            msg_text = "已歸檔至封存區 📦" if next_read else "已移回待讀 Inbox 📥"
            if reply_token:
                await reply_line_messages(reply_token, [{"type": "text", "text": f"[{item.get('title_l1')[:20]}] {msg_text}"}])
        return

    # 3. Message Event
    if event_type == "message":
        msg_obj = event.get("message", {})
        msg_type = msg_obj.get("type")
        text = msg_obj.get("text", "").strip()

        if msg_type != "text" or not text:
            if reply_token:
                await reply_line_messages(reply_token, [{"type": "text", "text": "請傳送網址或文字段落。"}])
            return

        # Commands
        if text in ["/help", "說明", "help"]:
            help_text = (
                f"🧠 OmniKeep 第二大腦 LINE 助手\n\n"
                f"綁定身分: {user_id}\n\n"
                f"• 隨手存入：直接傳送任何網址、YouTube 或技術段落，AI 會在幾秒內提煉出 L1/L2 結構化情報卡。\n"
                f"• 輸入「庫存」或 /stats：查詢當前大腦未讀數\n"
                f"• 輸入「待讀」：列出最近待讀清單"
            )
            if reply_token:
                await reply_line_messages(reply_token, [{"type": "text", "text": help_text}])
            return

        if text in ["/stats", "庫存", "統計"]:
            stats = get_status_counts()
            stats_text = (
                f"📊 OmniKeep 第二大腦庫存：\n\n"
                f"📥 待讀 Inbox: {stats.get('inbox', 0)} 篇\n"
                f"⭐ 星標精選: {stats.get('starred', 0)} 篇\n"
                f"📦 已封存: {stats.get('archived', 0)} 篇\n"
                f"📚 總計: {stats.get('total', 0)} 篇"
            )
            if reply_token:
                await reply_line_messages(reply_token, [{"type": "text", "text": stats_text}])
            return

        if text in ["/inbox", "待讀"]:
            items = get_items(is_read=False, limit=3)
            if not items:
                if reply_token:
                    await reply_line_messages(reply_token, [{"type": "text", "text": "🎉 待讀 Inbox 目前全數消化完畢！"}])
                return
            bubbles = [create_item_flex_bubble(item) for item in items]
            if reply_token:
                await reply_line_messages(reply_token, bubbles)
            return

        # Ingestion Pipeline
        await start_line_loading(user_id, seconds=15)
        try:
            item = await run_pipeline(text)
            flex_msg = create_item_flex_bubble(item)
            if reply_token:
                await reply_line_messages(reply_token, [flex_msg])
        except Exception as e:
            err_msg = f"❌ 情報提煉失敗：{str(e)}"
            if reply_token:
                await reply_line_messages(reply_token, [{"type": "text", "text": err_msg}])
