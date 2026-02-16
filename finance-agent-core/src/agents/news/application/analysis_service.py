from __future__ import annotations

import asyncio
from dataclasses import dataclass

from src.agents.news.application.parsers import parse_structured_llm_output
from src.agents.news.application.ports import (
    ChainLike,
    FinbertAnalyzerLike,
    FinbertResultLike,
    LLMLike,
    NewsArtifactTextReaderPort,
)
from src.agents.news.application.prompt_formatters import build_analysis_chain_payload
from src.shared.kernel.tools.logger import get_logger
from src.shared.kernel.types import JSONObject

logger = get_logger(__name__)


@dataclass(frozen=True)
class AnalysisChains:
    basic: ChainLike
    finbert: ChainLike


@dataclass(frozen=True)
class AnalystExecutionResult:
    news_items: list[JSONObject]
    article_errors: list[str]


def build_analysis_chains(
    *,
    llm: LLMLike,
    prompt_basic: object,
    prompt_finbert: object,
    analysis_model_type: type[object],
) -> AnalysisChains:
    basic_structured = llm.with_structured_output(analysis_model_type)
    finbert_structured = llm.with_structured_output(analysis_model_type)
    basic_chain = prompt_basic | basic_structured
    finbert_chain = prompt_finbert | finbert_structured
    return AnalysisChains(basic=basic_chain, finbert=finbert_chain)


def run_analysis_with_resilience(
    *,
    chains: AnalysisChains,
    chain_payload: JSONObject,
    prefer_finbert_chain: bool,
) -> tuple[JSONObject, bool]:
    if prefer_finbert_chain:
        try:
            result = chains.finbert.invoke(chain_payload)
            return parse_structured_llm_output(
                result, context="news finbert analysis response"
            ), False
        except Exception:
            result = chains.basic.invoke(chain_payload)
            return parse_structured_llm_output(
                result, context="news basic analysis degraded-path response"
            ), True

    result = chains.basic.invoke(chain_payload)
    return parse_structured_llm_output(
        result, context="news basic analysis response"
    ), False


async def analyze_news_items(
    *,
    news_items: list[JSONObject],
    ticker: str | None,
    port: NewsArtifactTextReaderPort,
    finbert_analyzer: FinbertAnalyzerLike,
    chains: AnalysisChains,
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
                    logger.warning("Could not load full content for analysis: %s", exc)

            finbert_result: FinbertResultLike | None = None
            finbert_summary: JSONObject | None = None
            if finbert_analyzer.is_available():
                finbert_result = await asyncio.to_thread(
                    finbert_analyzer.analyze, content_to_analyze
                )
                if finbert_result:
                    item["finbert_analysis"] = finbert_result.to_dict()
                    finbert_summary = {
                        "label": finbert_result.label,
                        "confidence": f"{finbert_result.score:.1%}",
                        "has_numbers": finbert_result.has_numbers,
                    }

            chain_payload = build_analysis_chain_payload(
                ticker=ticker_value,
                item=item,
                content_to_analyze=content_to_analyze,
                finbert_summary=finbert_summary,
            )
            analysis_payload, _used_degraded_path = run_analysis_with_resilience(
                chains=chains,
                chain_payload=chain_payload,
                prefer_finbert_chain=finbert_result is not None,
            )
            item["analysis"] = analysis_payload
            item["analysis"]["source"] = "llm"
        except Exception as exc:
            logger.error(
                "--- [News Research] ❌ Analysis FAILED for article %s: %s ---",
                index + 1,
                exc,
                exc_info=True,
            )
            article_errors.append(
                f"Analysis failed for {item.get('title', 'Unknown')}: {exc}"
            )

    return AnalystExecutionResult(news_items=news_items, article_errors=article_errors)
