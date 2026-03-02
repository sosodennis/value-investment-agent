from __future__ import annotations

from collections.abc import Mapping

from src.shared.kernel.types import JSONObject

from ..report_contract import FinancialReport
from .snapshot_service import (
    market_mapping,
    market_text,
    market_text_list,
    to_int,
)


def build_result_metadata(
    *,
    latest: FinancialReport,
    market_snapshot: Mapping[str, object] | None,
    shares_source: str | None = None,
) -> JSONObject:
    fiscal_year = to_int(latest.base.fiscal_year.value)
    period_end_raw = latest.base.period_end_date.value
    period_end = (
        str(period_end_raw)
        if isinstance(period_end_raw, str | int | float) and period_end_raw is not None
        else None
    )
    provider = market_text(market_snapshot, "provider")
    as_of = market_text(market_snapshot, "as_of")
    missing_fields = market_text_list(market_snapshot, "missing_fields")
    quality_flags = market_text_list(market_snapshot, "quality_flags")
    license_note = market_text(market_snapshot, "license_note")
    market_datums_raw = market_mapping(market_snapshot, "market_datums")
    market_datums: JSONObject = {}
    if market_datums_raw is not None:
        for field, datum_raw in market_datums_raw.items():
            if not isinstance(field, str) or not isinstance(datum_raw, Mapping):
                continue
            datum_payload: JSONObject = {}
            value_raw = datum_raw.get("value")
            if isinstance(value_raw, int | float):
                datum_payload["value"] = float(value_raw)
            elif value_raw is None:
                datum_payload["value"] = None

            source_raw = datum_raw.get("source")
            as_of_raw = datum_raw.get("as_of")
            quality_raw = datum_raw.get("quality_flags")
            license_raw = datum_raw.get("license_note")
            if isinstance(source_raw, str) and source_raw:
                datum_payload["source"] = source_raw
            if isinstance(as_of_raw, str) and as_of_raw:
                datum_payload["as_of"] = as_of_raw
            if isinstance(quality_raw, list | tuple):
                datum_quality = [
                    item for item in quality_raw if isinstance(item, str) and item
                ]
                if datum_quality:
                    datum_payload["quality_flags"] = datum_quality
            if isinstance(license_raw, str) and license_raw:
                datum_payload["license_note"] = license_raw
            if datum_payload:
                market_datums[field] = datum_payload

    financial_statement: JSONObject = {}
    if fiscal_year is not None:
        financial_statement["fiscal_year"] = fiscal_year
    if period_end is not None:
        financial_statement["period_end_date"] = period_end

    market_data: JSONObject = {}
    if provider is not None:
        market_data["provider"] = provider
    if as_of is not None:
        market_data["as_of"] = as_of
    if missing_fields:
        market_data["missing_fields"] = missing_fields
    if quality_flags:
        market_data["quality_flags"] = quality_flags
    if license_note is not None:
        market_data["license_note"] = license_note
    if market_datums:
        market_data["market_datums"] = market_datums

    data_freshness: JSONObject = {}
    if financial_statement:
        data_freshness["financial_statement"] = financial_statement
    if market_data:
        data_freshness["market_data"] = market_data
    if shares_source is not None:
        data_freshness["shares_outstanding_source"] = shares_source

    if not data_freshness:
        return {}
    return {"data_freshness": data_freshness}
