from __future__ import annotations

from src.agents.news.application.view_models import derive_news_preview_view_model
from src.agents.news.interface.formatters import format_news_preview
from src.common.types import JSONObject


def summarize_news_for_preview(
    ctx: JSONObject, news_items: list[JSONObject] | None = None
) -> JSONObject:
    view_model = derive_news_preview_view_model(ctx, news_items)
    return format_news_preview(view_model)
