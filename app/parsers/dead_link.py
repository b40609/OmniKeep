"""Addresses that cannot be opened for good: nothing is saved, and the sender is told why.

The 2026-11-18 new-user trial saved a GitHub 404 and a domain that does not exist as items whose
title was the address and whose summary promised an automatic refetch; two YouTube videos that do
not exist were saved as "YouTube Video". A refetch cannot help any of them, and an empty item only
clutters the library. A failure that may pass (a timeout, an anti-bot page, a 403) is still kept
and fetched again later, as before (app/refetch.py).
"""
import socket
from typing import Optional
from urllib.parse import urlsplit


class DeadLinkError(RuntimeError):
    """The address cannot be opened: no such page, no such domain, or a video that is gone."""


KEEP_ANOTHER_WAY = "沒有收藏。要收的話，從瀏覽器用書籤小工具收，或把內容貼成筆記。"

_STATUS_WORDS = {404: "找不到這一頁", 410: "這一頁已經移除"}


def is_dns_failure(exc: BaseException) -> bool:
    """The host name does not resolve (no such domain), judged from the exception and its causes."""
    seen = set()
    current: Optional[BaseException] = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, socket.gaierror):
            return True
        text = str(current).lower()
        if any(word in text for word in ("getaddrinfo failed", "name or service not known",
                                         "nodename nor servname", "no address associated with hostname",
                                         "temporary failure in name resolution")):
            return True
        current = current.__cause__ or current.__context__
    return False


def page_message(url: str, http_status: Optional[int], fetch_error: str = "") -> Optional[str]:
    """Why a web page cannot be opened for good, or None when it may still open later."""
    if fetch_error == "dns":
        host = urlsplit(url).hostname or url
        return f"這個網址打不開：找不到網域 {host}，可能打錯字，或網站已經不在了。沒有收藏。"
    if http_status in _STATUS_WORDS:
        return (f"這個網址打不開：網站回應 {http_status}（{_STATUS_WORDS[http_status]}）。"
                "連結可能打錯、頁面已刪除，或要登入才看得到（例如私人的 GitHub 專案）。" + KEEP_ANOTHER_WAY)
    return None


def video_message(reason: str) -> str:
    return f"這支 YouTube 影片打不開：{reason}。沒有收藏。"
