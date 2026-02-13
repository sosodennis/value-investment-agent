from __future__ import annotations

from src.agents.fundamental.application.view_models import (
    derive_fundamental_preview_view_model,
)
from src.agents.fundamental.interface.formatters import format_fundamental_preview
from src.common.types import JSONObject


def summarize_fundamental_for_preview(
    ctx: JSONObject,
    financial_reports: list[JSONObject] | None = None,
) -> JSONObject:
    view_model = derive_fundamental_preview_view_model(ctx, financial_reports)
    return format_fundamental_preview(view_model)
