from __future__ import annotations

from collections.abc import Mapping

from src.shared.kernel.types import JSONObject


def compress_financial_data(financial_reports: list[JSONObject]) -> list[JSONObject]:
    compressed: list[JSONObject] = []
    for report in financial_reports:
        base = _mapping_or_empty(report.get("base"))
        extension = _mapping_or_empty(report.get("extension"))
        fiscal_year = _string_or(
            _extract_value(base.get("fiscal_year")),
            default="Unknown",
        )

        metrics: JSONObject = {}
        for field in _MAIN_METRIC_FIELDS:
            value = _extract_value(base.get(field))
            if value is not None:
                metrics[field] = value

        for field in _EXTENSION_METRIC_FIELDS:
            value = _extract_value(extension.get(field))
            if value is not None:
                metrics[field] = value

        compressed.append(
            {
                "fiscal_year": fiscal_year,
                "metrics": metrics,
                "industry": _string_or(report.get("industry_type"), default="Unknown"),
            }
        )

    return compressed


def compress_news_data(news_items: list[JSONObject]) -> list[JSONObject]:
    compressed: list[JSONObject] = []
    for item in news_items:
        analysis = _mapping_or_empty(item.get("analysis"))
        source = _mapping_or_empty(item.get("source"))

        key_facts: list[object] = []
        key_facts_raw = analysis.get("key_facts")
        if isinstance(key_facts_raw, list):
            key_facts = key_facts_raw

        compressed.append(
            {
                "date": _published_date(item.get("published_at")),
                "title": _string_or(item.get("title"), default=""),
                "source": _string_or(source.get("name"), default="Unknown"),
                "summary": _string_or(analysis.get("summary"), default=""),
                "sentiment": _string_or(analysis.get("sentiment"), default=""),
                "impact": _string_or(analysis.get("impact_level"), default=""),
                "key_facts": [
                    _string_or(
                        fact.get("content") if isinstance(fact, Mapping) else fact,
                        default="",
                    )
                    for fact in key_facts
                    if _string_or(
                        fact.get("content") if isinstance(fact, Mapping) else fact,
                        default="",
                    )
                ],
            }
        )

    return compressed


def compress_ta_data(ta_output: JSONObject | None) -> JSONObject | None:
    if not ta_output:
        return None

    signal_state = _mapping_or_empty(ta_output.get("signal_state"))
    frac_diff = _mapping_or_empty(ta_output.get("frac_diff_metrics"))
    semantic_tags = ta_output.get("semantic_tags")

    return {
        "ticker": _string_or(ta_output.get("ticker"), default=""),
        "timestamp": _string_or(ta_output.get("timestamp"), default=""),
        "signal_summary": {
            "z_score": signal_state.get("z_score"),
            "direction": _string_or(signal_state.get("direction"), default=""),
            "risk_level": _string_or(signal_state.get("risk_level"), default=""),
            "statistical_state": _string_or(
                signal_state.get("statistical_state"),
                default="",
            ),
        },
        "memory_metrics": {
            "optimal_d": frac_diff.get("optimal_d"),
            "memory_strength": _string_or(frac_diff.get("memory_strength"), default=""),
        },
        "semantic_tags": semantic_tags if isinstance(semantic_tags, list) else [],
        "interpretation": _string_or(ta_output.get("llm_interpretation"), default=""),
    }


def _extract_value(raw: object) -> object | None:
    if isinstance(raw, Mapping):
        return raw.get("value")
    return raw


def _mapping_or_empty(value: object) -> Mapping[str, object]:
    if isinstance(value, Mapping):
        return value
    return {}


def _string_or(value: object, *, default: str) -> str:
    if isinstance(value, str):
        return value
    return default


def _published_date(value: object) -> str:
    if isinstance(value, str):
        return value[:10]
    return "N/A"


_MAIN_METRIC_FIELDS = (
    "total_revenue",
    "net_income",
    "operating_cash_flow",
    "total_assets",
    "total_liabilities",
    "total_equity",
    "cash_and_equivalents",
    "shares_outstanding",
)

_EXTENSION_METRIC_FIELDS = (
    "inventory",
    "accounts_receivable",
    "cogs",
    "rd_expense",
    "sga_expense",
    "capex",
)
