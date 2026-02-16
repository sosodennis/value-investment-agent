from __future__ import annotations

from src.agents.debate.application.view_models import derive_debate_preview_view_model
from src.agents.debate.interface.formatters import format_debate_preview
from src.shared.kernel.types import JSONObject


def summarize_debate_for_preview(ctx: JSONObject) -> JSONObject:
    view_model = derive_debate_preview_view_model(ctx)
    return format_debate_preview(view_model)
