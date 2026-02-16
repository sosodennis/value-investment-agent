from __future__ import annotations

from src.agents.technical.application.view_models import derive_ta_preview_view_model
from src.agents.technical.interface.formatters import format_ta_preview
from src.shared.kernel.types import JSONObject


def summarize_ta_for_preview(ctx: JSONObject) -> JSONObject:
    view_model = derive_ta_preview_view_model(ctx)
    return format_ta_preview(view_model)
