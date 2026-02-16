from __future__ import annotations

from src.agents.intent.domain.models import TickerCandidate
from src.agents.intent.interface.contracts import TickerCandidateModel
from src.shared.kernel.types import JSONObject


def summarize_intent_for_preview(ctx: JSONObject) -> JSONObject:
    status = ctx.get("status")
    profile = ctx.get("company_profile") or {}

    return {
        "ticker": ctx.get("resolved_ticker"),
        "company_name": profile.get("name"),
        "status_label": _get_status_label(status if isinstance(status, str) else None),
        "exchange": profile.get("exchange"),
    }


def _get_status_label(status: str | None) -> str:
    mapping = {
        "extraction": "解析意圖中...",
        "searching": "搜尋股票代號中...",
        "deciding": "正在確認結果...",
        "clarifying": "等待訊息輸入...",
        "resolved": "已確認標的",
    }
    return mapping.get(status, "準備中" if not status else f"狀態: {status}")


def to_ticker_candidate(model: TickerCandidateModel) -> TickerCandidate:
    return TickerCandidate(
        symbol=model.symbol,
        name=model.name,
        exchange=model.exchange,
        type=model.type,
        confidence=model.confidence,
    )


def from_ticker_candidate(candidate: TickerCandidate) -> TickerCandidateModel:
    return TickerCandidateModel(
        symbol=candidate.symbol,
        name=candidate.name,
        exchange=candidate.exchange,
        type=candidate.type,
        confidence=candidate.confidence,
    )
