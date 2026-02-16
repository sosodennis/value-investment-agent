from __future__ import annotations

from src.shared.kernel.types import AgentOutputArtifactPayload, JSONObject


def build_fetch_node_update(
    *, news_items_id: str | None, article_errors: list[str]
) -> JSONObject:
    status = "degraded" if article_errors else "running"
    update: JSONObject = {
        "financial_news_research": {"news_items_artifact_id": news_items_id},
        "current_node": "fetch_node",
        "internal_progress": {"fetch_node": "done", "analyst_node": "running"},
        "node_statuses": {"financial_news_research": status},
    }
    if article_errors:
        update["error_logs"] = [
            {
                "node": "fetch_node",
                "error": article_errors[0],
                "severity": "warning",
            }
        ]
    return update


def build_analyst_node_update(
    *, news_items_id: str | None, article_errors: list[str]
) -> JSONObject:
    status = "degraded" if article_errors else "running"
    update: JSONObject = {
        "financial_news_research": {"news_items_artifact_id": news_items_id},
        "current_node": "analyst_node",
        "internal_progress": {"analyst_node": "done", "aggregator_node": "running"},
        "node_statuses": {"financial_news_research": status},
    }
    if article_errors:
        update["error_logs"] = [
            {
                "node": "analyst_node",
                "error": f"Failed to analyze {len(article_errors)} articles.",
                "severity": "warning",
            }
        ]
    return update


def build_search_node_no_ticker_update() -> JSONObject:
    return {
        "current_node": "search_node",
        "internal_progress": {"search_node": "done"},
    }


def build_search_node_error_update(error_message: str) -> JSONObject:
    return {
        "current_node": "search_node",
        "internal_progress": {"search_node": "error"},
        "node_statuses": {"financial_news_research": "error"},
        "error_logs": [
            {
                "node": "search_node",
                "error": f"Search failed: {error_message}",
                "severity": "error",
            }
        ],
    }


def build_search_node_empty_update() -> JSONObject:
    return {
        "news_items": [],
        "current_node": "search_node",
        "internal_progress": {"search_node": "done"},
    }


def build_search_node_success_update(
    *,
    artifact: AgentOutputArtifactPayload,
    article_count: int,
    search_artifact_id: str | None,
) -> JSONObject:
    return {
        "financial_news_research": {
            "artifact": artifact,
            "article_count": article_count,
            "search_artifact_id": search_artifact_id,
        },
        "current_node": "search_node",
        "internal_progress": {"search_node": "done", "selector_node": "running"},
        "node_statuses": {"financial_news_research": "running"},
    }


def build_selector_node_update(
    *,
    selection_artifact_id: str | None,
    is_degraded: bool,
    error_message: str,
) -> JSONObject:
    update: JSONObject = {
        "financial_news_research": {"selection_artifact_id": selection_artifact_id},
        "current_node": "selector_node",
        "internal_progress": {"selector_node": "done", "fetch_node": "running"},
    }
    if is_degraded:
        normalized_error = (
            error_message
            if "Selection failed" in error_message
            else f"Selection failed: {error_message}. Falling back to top articles."
            if error_message
            else "Selection failed due to an unknown error. Falling back to top articles."
        )
        update["node_statuses"] = {"financial_news_research": "degraded"}
        update["error_logs"] = [
            {
                "node": "selector_node",
                "error": normalized_error,
                "severity": "warning",
            }
        ]
    return update


def build_analyst_chain_error_update(error_message: str) -> JSONObject:
    return {
        "current_node": "analyst_node",
        "internal_progress": {"analyst_node": "error"},
        "node_statuses": {"financial_news_research": "error"},
        "error_logs": [
            {
                "node": "analyst_node",
                "error": f"Failed to create analysis chains: {error_message}",
                "severity": "error",
            }
        ],
    }


def build_aggregator_node_update(
    *,
    status: str,
    sentiment_summary: str,
    sentiment_score: float,
    article_count: int,
    report_id: str | None,
    top_headlines: list[str],
    artifact: AgentOutputArtifactPayload | None,
) -> JSONObject:
    news_update: JSONObject = {
        "status": status,
        "sentiment_summary": sentiment_summary,
        "sentiment_score": sentiment_score,
        "article_count": article_count,
        "report_id": report_id,
        "top_headlines": top_headlines,
    }
    if artifact is not None:
        news_update["artifact"] = artifact

    return {
        "financial_news_research": news_update,
        "current_node": "aggregator_node",
        "internal_progress": {"aggregator_node": "done"},
        "node_statuses": {"financial_news_research": "done"},
    }
