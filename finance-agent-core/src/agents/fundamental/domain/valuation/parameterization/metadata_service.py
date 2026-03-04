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
            horizon_raw = datum_raw.get("horizon")
            source_detail_raw = datum_raw.get("source_detail")
            quality_raw = datum_raw.get("quality_flags")
            staleness_raw = datum_raw.get("staleness")
            fallback_reason_raw = datum_raw.get("fallback_reason")
            license_raw = datum_raw.get("license_note")
            if isinstance(source_raw, str) and source_raw:
                datum_payload["source"] = source_raw
            if isinstance(as_of_raw, str) and as_of_raw:
                datum_payload["as_of"] = as_of_raw
            if isinstance(horizon_raw, str) and horizon_raw:
                datum_payload["horizon"] = horizon_raw
            if isinstance(source_detail_raw, str) and source_detail_raw:
                datum_payload["source_detail"] = source_detail_raw
            if isinstance(quality_raw, list | tuple):
                datum_quality = [
                    item for item in quality_raw if isinstance(item, str) and item
                ]
                if datum_quality:
                    datum_payload["quality_flags"] = datum_quality
            if isinstance(staleness_raw, Mapping):
                staleness_payload: JSONObject = {}
                days_raw = staleness_raw.get("days")
                is_stale_raw = staleness_raw.get("is_stale")
                max_days_raw = staleness_raw.get("max_days")
                if isinstance(days_raw, int):
                    staleness_payload["days"] = days_raw
                if isinstance(is_stale_raw, bool):
                    staleness_payload["is_stale"] = is_stale_raw
                if isinstance(max_days_raw, int):
                    staleness_payload["max_days"] = max_days_raw
                if staleness_payload:
                    datum_payload["staleness"] = staleness_payload
            if isinstance(fallback_reason_raw, str) and fallback_reason_raw:
                datum_payload["fallback_reason"] = fallback_reason_raw
            if isinstance(license_raw, str) and license_raw:
                datum_payload["license_note"] = license_raw
            if datum_payload:
                market_datums[field] = datum_payload

    financial_statement: JSONObject = {}
    if fiscal_year is not None:
        financial_statement["fiscal_year"] = fiscal_year
    if period_end is not None:
        financial_statement["period_end_date"] = period_end
    filing_metadata = latest.filing_metadata
    if filing_metadata is not None:
        filing_payload: JSONObject = {}
        if filing_metadata.form is not None:
            filing_payload["form"] = filing_metadata.form
        if filing_metadata.accession_number is not None:
            filing_payload["accession_number"] = filing_metadata.accession_number
        if filing_metadata.filing_date is not None:
            filing_payload["filing_date"] = filing_metadata.filing_date
        if filing_metadata.accepted_datetime is not None:
            filing_payload["accepted_datetime"] = filing_metadata.accepted_datetime
        if filing_metadata.period_of_report is not None:
            filing_payload["period_of_report"] = filing_metadata.period_of_report
        if filing_metadata.requested_fiscal_year is not None:
            filing_payload["requested_fiscal_year"] = (
                filing_metadata.requested_fiscal_year
            )
        if filing_metadata.matched_fiscal_year is not None:
            filing_payload["matched_fiscal_year"] = filing_metadata.matched_fiscal_year
        if filing_metadata.selection_mode is not None:
            filing_payload["selection_mode"] = filing_metadata.selection_mode
        if filing_payload:
            financial_statement["filing"] = filing_payload

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

    result: JSONObject = {}
    if data_freshness:
        result["data_freshness"] = data_freshness
    parameter_source_summary = _build_parameter_source_summary(
        financial_statement=financial_statement,
        market_data=market_data,
        market_datums=market_datums,
        shares_source=shares_source,
    )
    if parameter_source_summary:
        result["parameter_source_summary"] = parameter_source_summary
    return result


def _build_parameter_source_summary(
    *,
    financial_statement: JSONObject,
    market_data: JSONObject,
    market_datums: JSONObject,
    shares_source: str | None,
) -> JSONObject | None:
    summary: JSONObject = {}
    if financial_statement:
        summary["financial_statement_anchor"] = dict(financial_statement)

    market_anchor: JSONObject = {}
    provider_raw = market_data.get("provider")
    as_of_raw = market_data.get("as_of")
    if isinstance(provider_raw, str) and provider_raw:
        market_anchor["provider"] = provider_raw
    if isinstance(as_of_raw, str) and as_of_raw:
        market_anchor["as_of"] = as_of_raw
    if market_anchor:
        summary["market_data_anchor"] = market_anchor

    parameters: JSONObject = {}
    for field, datum_raw in market_datums.items():
        if isinstance(field, str) and isinstance(datum_raw, Mapping):
            parameters[field] = dict(datum_raw)
    if parameters:
        summary["parameters"] = parameters

    shares_summary = _build_shares_source_summary(
        shares_source=shares_source,
        market_datums=market_datums,
    )
    if shares_summary:
        summary["shares_outstanding"] = shares_summary

    return summary or None


def _build_shares_source_summary(
    *,
    shares_source: str | None,
    market_datums: JSONObject,
) -> JSONObject | None:
    summary: JSONObject = {}
    if isinstance(shares_source, str) and shares_source:
        summary["selected_source"] = shares_source
        if shares_source.endswith("_market_stale_fallback"):
            summary["fallback_reason"] = "market_stale"
        elif shares_source != "market_data":
            summary["fallback_reason"] = "market_unavailable_or_policy"

    shares_datum_raw = market_datums.get("shares_outstanding")
    if isinstance(shares_datum_raw, Mapping):
        staleness_raw = shares_datum_raw.get("staleness")
        if isinstance(staleness_raw, Mapping):
            is_stale_raw = staleness_raw.get("is_stale")
            days_raw = staleness_raw.get("days")
            max_days_raw = staleness_raw.get("max_days")
            if isinstance(is_stale_raw, bool):
                summary["market_is_stale"] = is_stale_raw
            if isinstance(days_raw, int):
                summary["market_staleness_days"] = days_raw
            if isinstance(max_days_raw, int):
                summary["market_stale_max_days"] = max_days_raw

    return summary or None
