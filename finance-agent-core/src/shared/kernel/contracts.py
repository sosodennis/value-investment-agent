from __future__ import annotations

from typing import Final, Literal, TypeAlias

CONTRACT_VERSION_V1: Final = "v1"
ARTIFACT_CONTRACT_VERSION: Final = CONTRACT_VERSION_V1
AGENT_OUTPUT_VERSION: Final = CONTRACT_VERSION_V1

OUTPUT_KIND_INTENT_EXTRACTION: Final = "intent_extraction.output"
OUTPUT_KIND_FUNDAMENTAL_ANALYSIS: Final = "fundamental_analysis.output"
OUTPUT_KIND_FINANCIAL_NEWS_RESEARCH: Final = "financial_news_research.output"
OUTPUT_KIND_DEBATE: Final = "debate.output"
OUTPUT_KIND_TECHNICAL_ANALYSIS: Final = "technical_analysis.output"
OUTPUT_KIND_GENERIC: Final = "generic.output"

AGENT_OUTPUT_KINDS: Final[tuple[str, ...]] = (
    OUTPUT_KIND_INTENT_EXTRACTION,
    OUTPUT_KIND_FUNDAMENTAL_ANALYSIS,
    OUTPUT_KIND_FINANCIAL_NEWS_RESEARCH,
    OUTPUT_KIND_DEBATE,
    OUTPUT_KIND_TECHNICAL_ANALYSIS,
    OUTPUT_KIND_GENERIC,
)

AgentOutputKind: TypeAlias = Literal[
    "intent_extraction.output",
    "fundamental_analysis.output",
    "financial_news_research.output",
    "debate.output",
    "technical_analysis.output",
    "generic.output",
]

ARTIFACT_KIND_FINANCIAL_REPORTS: Final = "financial_reports"
ARTIFACT_KIND_PRICE_SERIES: Final = "price_series"
ARTIFACT_KIND_TA_CHART_DATA: Final = "ta_chart_data"
ARTIFACT_KIND_TA_FULL_REPORT: Final = "ta_full_report"
ARTIFACT_KIND_SEARCH_RESULTS: Final = "search_results"
ARTIFACT_KIND_NEWS_SELECTION: Final = "news_selection"
ARTIFACT_KIND_NEWS_ARTICLE: Final = "news_article"
ARTIFACT_KIND_NEWS_ITEMS_LIST: Final = "news_items_list"
ARTIFACT_KIND_NEWS_ANALYSIS_REPORT: Final = "news_analysis_report"
ARTIFACT_KIND_DEBATE_FACTS: Final = "debate_facts"
ARTIFACT_KIND_DEBATE_FINAL_REPORT: Final = "debate_final_report"
