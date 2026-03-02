from __future__ import annotations

from src.agents.technical.interface.formatters import format_ta_preview
from src.agents.technical.interface.preview_projection_service import project_ta_preview
from src.shared.kernel.types import JSONObject


def summarize_ta_for_preview(ctx: JSONObject) -> JSONObject:
    preview_projection = project_ta_preview(ctx)
    return format_ta_preview(preview_projection)
