from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol
from uuid import uuid4

from src.agents.news.application.ports import (
    NewsArtifactTextReaderPort,
)
from src.agents.news.interface.contracts import AIAnalysisModel
from src.agents.news.interface.prompt_renderers import build_analysis_chain_payload
from src.llm_provider.entrypoint import (
    ChatMessage,
    ChatRole,
    CompletionRequest,
    ModelRoute,
    StructuredRequest,
)
from src.model_inference.entrypoint import (
    InferenceFailure,
    ModelInference,
    NewsSentimentResult,
)
from src.shared.kernel.tools.logger import get_logger, log_event
from src.shared.kernel.types import JSONObject

logger = get_logger(__name__)


class AnalysisModelProvider(Protocol):
    async def acomplete_structured(
        self, request: StructuredRequest[AIAnalysisModel]
    ) -> AIAnalysisModel: ...


@dataclass(frozen=True)
class AnalysisRuntime:
    provider: AnalysisModelProvider
    route: ModelRoute
    system_prompt: str
    basic_user_prompt: str
    finbert_user_prompt: str


@dataclass(frozen=True)
class AnalystExecutionResult:
    news_items: list[JSONObject]
    article_errors: list[str]


def build_analysis_chains(
    *,
    llm_provider: AnalysisModelProvider,
    llm_route: ModelRoute,
    system_prompt: str,
    user_prompt_basic: str,
    user_prompt_with_finbert: str,
) -> AnalysisRuntime:
    return AnalysisRuntime(
        provider=llm_provider,
        route=llm_route,
        system_prompt=system_prompt,
        basic_user_prompt=user_prompt_basic,
        finbert_user_prompt=user_prompt_with_finbert,
    )


async def _invoke_analysis(
    *, chains: AnalysisRuntime, payload: JSONObject, user_prompt: str
) -> JSONObject:
    prompt_values = {
        "ticker": payload.get("ticker", "UNKNOWN"),
        "title": payload.get("title", "Unknown"),
        "source": payload.get("source", "Unknown"),
        "published_at": payload.get("published_at", "N/A"),
        "content": payload.get("content", ""),
        "search_tag": payload.get("search_tag", ""),
        "finbert_sentiment": payload.get("finbert_sentiment", ""),
        "finbert_confidence": payload.get("finbert_confidence", ""),
        "finbert_has_numbers": payload.get("finbert_has_numbers", ""),
    }
    request = CompletionRequest(
        messages=(
            ChatMessage(role=ChatRole.SYSTEM, content=chains.system_prompt),
            ChatMessage(
                role=ChatRole.USER,
                content=user_prompt.format(**prompt_values),
            ),
        ),
        route=chains.route,
        request_id=f"news-analysis-{uuid4().hex}",
        operation="news.analyze_article",
        timeout_seconds=60.0,
    )
    result = await chains.provider.acomplete_structured(
        StructuredRequest[AIAnalysisModel](
            completion=request,
            response_schema=AIAnalysisModel,
        )
    )
    return result.model_dump(mode="json")


async def run_analysis_with_resilience(
    *,
    chains: AnalysisRuntime,
    chain_payload: JSONObject,
    prefer_finbert_chain: bool,
) -> tuple[JSONObject, bool]:
    if prefer_finbert_chain:
        try:
            return await _invoke_analysis(
                chains=chains,
                payload=chain_payload,
                user_prompt=chains.finbert_user_prompt,
            ), False
        except Exception:
            return await _invoke_analysis(
                chains=chains,
                payload=chain_payload,
                user_prompt=chains.basic_user_prompt,
            ), True

    return await _invoke_analysis(
        chains=chains,
        payload=chain_payload,
        user_prompt=chains.basic_user_prompt,
    ), False


async def analyze_news_items(
    *,
    news_items: list[JSONObject],
    ticker: str | None,
    port: NewsArtifactTextReaderPort,
    model_inference: ModelInference,
    chains: AnalysisRuntime,
) -> AnalystExecutionResult:
    article_errors: list[str] = []
    ticker_value = ticker or "UNKNOWN"

    for index, item in enumerate(news_items):
        try:
            content_to_analyze = str(item.get("snippet", ""))

            content_id = item.get("content_id")
            if content_id:
                try:
                    full_text = await port.load_news_article_text(content_id)
                    if isinstance(full_text, str):
                        content_to_analyze = full_text
                except Exception as exc:
                    log_event(
                        logger,
                        event="news_analysis_full_content_load_failed",
                        message="failed to load full content for analysis; falling back to snippet",
                        level=logging.WARNING,
                        error_code="NEWS_ANALYSIS_CONTENT_LOAD_FAILED",
                        fields={"content_id": content_id, "exception": str(exc)},
                    )

            finbert_result: NewsSentimentResult | None = None
            finbert_summary: JSONObject | None = None
            try:
                finbert_result = await model_inference.news_sentiment(
                    content_to_analyze
                )
            except InferenceFailure as exc:
                log_event(
                    logger,
                    event="news_analysis_model_inference_unavailable",
                    message="news sentiment inference failed; basic prompt is active",
                    level=logging.WARNING,
                    fields={"code": exc.code.value, "request_id": exc.request_id},
                )
            if finbert_result is not None:
                item["finbert_analysis"] = {
                    "label": finbert_result.label,
                    "score": finbert_result.confidence,
                    "all_scores": dict(finbert_result.scores),
                    "has_numbers": finbert_result.has_numbers,
                }
                finbert_summary = {
                    "label": finbert_result.label,
                    "confidence": f"{finbert_result.confidence:.1%}",
                    "has_numbers": finbert_result.has_numbers,
                }

            chain_payload = build_analysis_chain_payload(
                ticker=ticker_value,
                item=item,
                content_to_analyze=content_to_analyze,
                finbert_summary=finbert_summary,
            )
            analysis_payload, _used_degraded_path = await run_analysis_with_resilience(
                chains=chains,
                chain_payload=chain_payload,
                prefer_finbert_chain=finbert_result is not None,
            )
            item["analysis"] = analysis_payload
            item["analysis"]["source"] = "llm"
        except Exception as exc:
            log_event(
                logger,
                event="news_analysis_item_failed",
                message="news item analysis failed",
                level=logging.ERROR,
                error_code="NEWS_ANALYSIS_ITEM_FAILED",
                fields={
                    "index": index + 1,
                    "ticker": ticker_value,
                    "title": item.get("title"),
                    "exception": str(exc),
                },
            )
            article_errors.append(
                f"Analysis failed for {item.get('title', 'Unknown')}: {exc}"
            )

    return AnalystExecutionResult(news_items=news_items, article_errors=article_errors)
