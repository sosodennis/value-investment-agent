from __future__ import annotations

from src.agents.fundamental.interface.contracts import FundamentalPreviewInputModel
from src.agents.fundamental.interface.formatters import format_fundamental_preview
from src.agents.fundamental.interface.preview_projection_service import (
    project_fundamental_preview,
)
from src.shared.kernel.types import JSONObject


def summarize_fundamental_for_preview(
    ctx: FundamentalPreviewInputModel,
    financial_reports: list[JSONObject] | None = None,
) -> JSONObject:
    preview_projection = project_fundamental_preview(
        ctx.model_dump(mode="json"),
        financial_reports,
    )
    return format_fundamental_preview(preview_projection)
