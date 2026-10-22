from typing import Optional
from app.radar.adapters.base import BaseSourceAdapter, RawFeedItem
from app.radar.adapters.youtube import YouTubeAdapter
from app.radar.adapters.github import GitHubAdapter
from app.radar.adapters.rss import RSSAdapter

_ADAPTERS = {
    "youtube": YouTubeAdapter(),
    "github": GitHubAdapter(),
    "rss": RSSAdapter()
}

def get_adapter(source_type: str) -> Optional[BaseSourceAdapter]:
    return _ADAPTERS.get(source_type.lower())

def register_adapter(source_type: str, adapter: BaseSourceAdapter):
    _ADAPTERS[source_type.lower()] = adapter
