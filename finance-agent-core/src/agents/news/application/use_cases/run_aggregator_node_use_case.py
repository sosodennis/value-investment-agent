from __future__ import annotations

import logging
import time
from collections.abc import Callable, Mapping

from langchain_core.messages import AIMessage

from src.agents.news.application.ports import INewsArtifactRepository
from src.agents.news.application.state_readers import (
    aggregator_ticker_from_state,
    news_items_artifact_id_from_state,
)
from src.agents.news.application.state_updates import build_aggregator_node_update
from src.agents.news.domain.aggregation.aggregation_service import aggregate_news_items
from src.agents.news.domain.aggregation.contracts import NewsAggregationResult
from src.agents.news.domain.aggregation.summary_message_service import (
    build_news_summary_message,
)
from src.agents.news.domain.news_item_projection_service import to_news_item_entities
from src.agents.news.interface.contracts import parse_news_artifact_model
from src.agents.news.interface.parsers import parse_news_items
from src.shared.kernel.tools.incident_logging import (
    CONTRACT_KIND_ARTIFACT_JSON,
    build_replay_diagnostics,
    log_boundary_event,
)
from src.shared.kernel.tools.logger import get_logger, log_event
from src.shared.kernel.types import AgentOutputArtifactPayload, JSONObject
from src.shared.kernel.workflow_contracts import WorkflowNodeResult

logger = get_logger(__name__)


def _truncate_error_message(message: str, *, limit: int = 320) -> str:
    if len(message) <= limit:
        return message
    return f"{message[:limit]}..."


def _append_source_once(sources: list[str], source: str) -> None:
    if source not in sources:
        sources.append(source)


async def run_aggregator_node_use_case(
    *,
    state: Mapping[str, object],
    port: INewsArtifactRepository,
    summarize_preview: Callable[[JSONObject, list[JSONObject] | None], JSONObject],
    build_news_report_payload: Callable[
        [str, list[JSONObject], NewsAggregationResult], JSONObject
    ],
    build_output_artifact: Callable[
        [str, JSONObject, str | None], AgentOutputArtifactPayload | None
    ],
) -> WorkflowNodeResult:
    news_items_id = news_items_artifact_id_from_state(state)
    degrade_sources: list[str] = []
    degrade_messages: list[str] = []

    news_items: list[JSONObject] = []
    try:
        news_items = await port.load_news_items_data(news_items_id)
        parsed_news_items = parse_news_items(
            list(news_items),
            context="news aggregator items",
        )
        news_items = [item.model_dump(mode="json") for item in parsed_news_items]
    except Exception as exc:
        log_event(
            logger,
            event="news_aggregator_items_load_failed",
            message="failed to load news items for aggregation",
            level=logging.ERROR,
            error_code="NEWS_AGGREGATOR_ITEMS_LOAD_FAILED",
            fields={"news_items_artifact_id": news_items_id, "exception": str(exc)},
        )
        log_boundary_event(
            logger,
            node="news.aggregator",
            artifact_id=None,
            contract_kind=CONTRACT_KIND_ARTIFACT_JSON,
            error_code="NEWS_AGGREGATOR_ITEMS_LOAD_FAILED",
            state=state,
            detail={
                "exception": str(exc),
                "news_items_artifact_id": news_items_id,
            },
            level=logging.ERROR,
        )
        return WorkflowNodeResult(
            update={
                "financial_news_research": {
                    "status": "error",
                    "sentiment_summary": "unknown",
                    "sentiment_score": 0.0,
                    "article_count": 0,
                    "report_id": None,
                    "top_headlines": [],
                },
                "current_node": "aggregator_node",
                "internal_progress": {"aggregator_node": "error"},
                "node_statuses": {"financial_news_research": "error"},
                "error_logs": [
                    {
                        "node": "aggregator_node",
                        "error": f"Failed to load news items: {str(exc)}",
                        "severity": "error",
                        "error_code": "NEWS_AGGREGATOR_ITEMS_LOAD_FAILED",
                        "contract_kind": CONTRACT_KIND_ARTIFACT_JSON,
                        "artifact_id": news_items_id,
                        "diagnostics": build_replay_diagnostics(
                            state, node="news.aggregator"
                        ),
                    }
                ],
            },
            goto="END",
        )

    news_item_entities = to_news_item_entities(news_items)
    ticker = aggregator_ticker_from_state(state)
    log_event(
        logger,
        event="news_aggregator_started",
        message="news aggregator started",
        fields={"ticker": ticker, "news_items_count": len(news_items)},
    )

    try:
        aggregation = aggregate_news_items(news_item_entities, ticker=ticker)
        report_payload = build_news_report_payload(
            ticker=ticker,
            news_items=news_items,
            aggregation=aggregation,
        )
        report_data = parse_news_artifact_model(report_payload)
    except Exception as exc:
        log_boundary_event(
            logger,
            node="news.aggregator",
            artifact_id=None,
            contract_kind=CONTRACT_KIND_ARTIFACT_JSON,
            error_code="NEWS_REPORT_PAYLOAD_BUILD_FAILED",
            state=state,
            detail={
                "exception": str(exc),
                "ticker": ticker,
                "news_items_count": len(news_items),
            },
            level=logging.ERROR,
        )
        return WorkflowNodeResult(
            update={
                "financial_news_research": {
                    "status": "error",
                    "sentiment_summary": "unknown",
                    "sentiment_score": 0.0,
                    "article_count": len(news_items),
                    "report_id": None,
                    "top_headlines": [],
                },
                "current_node": "aggregator_node",
                "internal_progress": {"aggregator_node": "error"},
                "node_statuses": {"financial_news_research": "error"},
                "error_logs": [
                    {
                        "node": "aggregator_node",
                        "error": f"Failed to build news report payload: {str(exc)}",
                        "severity": "error",
                        "error_code": "NEWS_REPORT_PAYLOAD_BUILD_FAILED",
                        "contract_kind": CONTRACT_KIND_ARTIFACT_JSON,
                        "artifact_id": None,
                        "diagnostics": build_replay_diagnostics(
                            state, node="news.aggregator"
                        ),
                    }
                ],
            },
            goto="END",
        )

    timestamp = int(time.time())
    try:
        report_id = await port.save_news_report(
            data=report_data,
            produced_by="financial_news_research.aggregator_node",
            key_prefix=f"news_report_{ticker}_{timestamp}",
        )
    except Exception as exc:
        log_event(
            logger,
            event="news_aggregator_report_save_failed",
            message="failed to save final news report artifact",
            level=logging.ERROR,
            error_code="NEWS_REPORT_SAVE_FAILED",
            fields={"ticker": ticker, "exception": str(exc)},
        )
        report_id = None
        _append_source_once(degrade_sources, "report_save")
        degrade_messages.append(
            f"Failed to save final news report artifact: {str(exc)}"
        )
        log_boundary_event(
            logger,
            node="news.aggregator",
            artifact_id=None,
            contract_kind=CONTRACT_KIND_ARTIFACT_JSON,
            error_code="NEWS_REPORT_SAVE_FAILED",
            state=state,
            detail={"exception": str(exc), "ticker": ticker},
            level=logging.ERROR,
        )

    try:
        preview = summarize_preview(report_payload, news_items)
        artifact = build_output_artifact(
            f"News Research: {aggregation.sentiment_label.upper()} ({aggregation.weighted_score:.2f})",
            preview,
            report_id,
        )
    except Exception as exc:
        log_event(
            logger,
            event="news_aggregator_output_artifact_failed",
            message="failed to build news output artifact",
            level=logging.ERROR,
            error_code="NEWS_OUTPUT_ARTIFACT_FAILED",
            fields={"ticker": ticker, "exception": str(exc)},
        )
        artifact = None
        _append_source_once(degrade_sources, "output_artifact")
        degrade_messages.append(f"Failed to build output artifact: {str(exc)}")

    log_boundary_event(
        logger,
        node="news.aggregator",
        artifact_id=report_id,
        contract_kind=CONTRACT_KIND_ARTIFACT_JSON,
        error_code="OK",
        state=state,
        detail={
            "ticker": ticker,
            "news_items_count": len(news_items),
            "sentiment_label": aggregation.sentiment_label,
        },
    )
    log_event(
        logger,
        event="news_aggregator_completed",
        message="news aggregator completed",
        fields={
            "ticker": ticker,
            "news_items_count": len(news_items),
            "sentiment_label": aggregation.sentiment_label,
            "sentiment_score": aggregation.weighted_score,
            "report_id": report_id,
            "is_degraded": bool(degrade_messages),
            "degrade_sources": degrade_sources,
        },
    )
    if degrade_messages:
        log_event(
            logger,
            event="news_aggregator_degraded",
            message="news aggregator degraded with partial failures",
            level=logging.WARNING,
            error_code="NEWS_AGGREGATOR_DEGRADED",
            fields={
                "ticker": ticker,
                "news_items_artifact_id": news_items_id,
                "news_items_count": len(news_items),
                "report_id": report_id,
                "degrade_sources": degrade_sources,
                "degrade_reason": _truncate_error_message("; ".join(degrade_messages)),
            },
        )
    summary_message = build_news_summary_message(ticker=ticker, result=aggregation)
    status = "degraded" if degrade_messages else "success"
    node_status = "degraded" if degrade_messages else "done"
    update = build_aggregator_node_update(
        status=status,
        node_status=node_status,
        sentiment_summary=aggregation.sentiment_label,
        sentiment_score=aggregation.weighted_score,
        article_count=len(news_items),
        report_id=report_id,
        top_headlines=aggregation.top_headlines,
        artifact=artifact,
    )
    if degrade_messages:
        update["error_logs"] = [
            {
                "node": "aggregator_node",
                "error": _truncate_error_message("; ".join(degrade_messages)),
                "severity": "warning",
            }
        ]
    update["messages"] = [
        AIMessage(
            content=summary_message,
            additional_kwargs={
                "type": "text",
                "agent_id": "financial_news_research",
            },
        )
    ]
    return WorkflowNodeResult(
        update=update,
        goto="END",
    )
