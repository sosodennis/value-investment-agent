from .aggregation_service import aggregate_news_items
from .contracts import NewsAggregationResult
from .summary_message_service import build_news_summary_message

__all__ = [
    "NewsAggregationResult",
    "aggregate_news_items",
    "build_news_summary_message",
]
