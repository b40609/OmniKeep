from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
from datetime import datetime
from collections import Counter
from pydantic import BaseModel

class RawFeedItem(BaseModel):
    url: str
    title: str
    content: str
    published_at: Optional[str] = None
    author: Optional[str] = None
    source_id: str
    source_type: str
    tier: int = 2

class BaseSourceAdapter(ABC):
    source_type: str = "base"

    @abstractmethod
    async def fetch_latest(self, source: Dict[str, Any]) -> List[RawFeedItem]:
        """
        Polls or queries the source. Returns newly detected raw items.
        Should handle ETag / 304 caching where applicable.
        """
        pass

    def calculate_hot_hours(self, date_list: List[datetime], min_samples: int = 3) -> List[int]:
        """
        Calculates peak publication hours from history (Local Time / UTC+8).
        Returns hours with publication frequency >= 25% of samples.
        """
        if len(date_list) < min_samples:
            return []

        # Convert to local hours (0 - 23)
        hours = [d.hour for d in date_list]
        counts = Counter(hours)
        total = len(hours)

        hot_hours = []
        for hour, cnt in counts.most_common(3):
            if (cnt / total) >= 0.25:
                hot_hours.append(hour)

        hot_hours.sort()
        return hot_hours
