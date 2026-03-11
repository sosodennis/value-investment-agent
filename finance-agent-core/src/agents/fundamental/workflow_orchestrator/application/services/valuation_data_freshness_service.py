from __future__ import annotations

from collections.abc import Mapping

from src.shared.kernel.types import JSONObject


def build_data_freshness(
    *,
    reports_raw: list[JSONObject],
    build_metadata: JSONObject | None,
) -> JSONObject | None:
    payload: JSONObject = {}

    statement = _extract_latest_statement_freshness(reports_raw)
    if statement is not None:
        payload["financial_statement"] = statement

    metadata_freshness = None
    if isinstance(build_metadata, Mapping):
        metadata_freshness_raw = build_metadata.get("data_freshness")
        if isinstance(metadata_freshness_raw, Mapping):
            metadata_freshness = dict(metadata_freshness_raw)

    if isinstance(metadata_freshness, dict):
        financial_statement_raw = metadata_freshness.get("financial_statement")
        if isinstance(financial_statement_raw, Mapping):
            financial_statement = (
                dict(payload.get("financial_statement"))
                if isinstance(payload.get("financial_statement"), Mapping)
                else {}
            )
            fiscal_year = financial_statement_raw.get("fiscal_year")
            period_end_date = financial_statement_raw.get("period_end_date")
            filing_raw = financial_statement_raw.get("filing")
            if isinstance(fiscal_year, int):
                financial_statement["fiscal_year"] = fiscal_year
            if isinstance(period_end_date, str) and period_end_date:
                financial_statement["period_end_date"] = period_end_date
            if isinstance(filing_raw, Mapping):
                filing: JSONObject = {}
                for field in (
                    "form",
                    "accession_number",
                    "filing_date",
                    "accepted_datetime",
                    "period_of_report",
                    "selection_mode",
                ):
                    value = filing_raw.get(field)
                    if isinstance(value, str) and value:
                        filing[field] = value
                for field in ("requested_fiscal_year", "matched_fiscal_year"):
                    value = filing_raw.get(field)
                    if isinstance(value, int):
                        filing[field] = value
                if filing:
                    financial_statement["filing"] = filing
            if financial_statement:
                payload["financial_statement"] = financial_statement

        market_data_raw = metadata_freshness.get("market_data")
        if isinstance(market_data_raw, Mapping):
            market_data: JSONObject = {}
            provider = market_data_raw.get("provider")
            as_of = market_data_raw.get("as_of")
            missing_fields = market_data_raw.get("missing_fields")
            quality_flags = market_data_raw.get("quality_flags")
            license_note = market_data_raw.get("license_note")
            market_datums_raw = market_data_raw.get("market_datums")
            if isinstance(provider, str) and provider:
                market_data["provider"] = provider
            if isinstance(as_of, str) and as_of:
                market_data["as_of"] = as_of
            if isinstance(missing_fields, list):
                normalized_missing_fields = [
                    item for item in missing_fields if isinstance(item, str) and item
                ]
                if normalized_missing_fields:
                    market_data["missing_fields"] = normalized_missing_fields
            if isinstance(quality_flags, list):
                normalized_quality_flags = [
                    item for item in quality_flags if isinstance(item, str) and item
                ]
                if normalized_quality_flags:
                    market_data["quality_flags"] = normalized_quality_flags
            if isinstance(license_note, str) and license_note:
                market_data["license_note"] = license_note
            if isinstance(market_datums_raw, Mapping):
                market_datums: JSONObject = {}
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
                    if isinstance(quality_raw, list):
                        datum_quality = [
                            item
                            for item in quality_raw
                            if isinstance(item, str) and item
                        ]
                        if datum_quality:
                            datum_payload["quality_flags"] = datum_quality
                    if isinstance(staleness_raw, Mapping):
                        staleness: JSONObject = {}
                        days_raw = staleness_raw.get("days")
                        is_stale_raw = staleness_raw.get("is_stale")
                        max_days_raw = staleness_raw.get("max_days")
                        if isinstance(days_raw, int):
                            staleness["days"] = days_raw
                        if isinstance(is_stale_raw, bool):
                            staleness["is_stale"] = is_stale_raw
                        if isinstance(max_days_raw, int):
                            staleness["max_days"] = max_days_raw
                        if staleness:
                            datum_payload["staleness"] = staleness
                    if isinstance(fallback_reason_raw, str) and fallback_reason_raw:
                        datum_payload["fallback_reason"] = fallback_reason_raw
                    if isinstance(license_raw, str) and license_raw:
                        datum_payload["license_note"] = license_raw
                    if datum_payload:
                        market_datums[field] = datum_payload
                if market_datums:
                    market_data["market_datums"] = market_datums
            if market_data:
                payload["market_data"] = market_data

        shares_source = metadata_freshness.get("shares_outstanding_source")
        if isinstance(shares_source, str) and shares_source:
            payload["shares_outstanding_source"] = shares_source

        time_alignment_raw = metadata_freshness.get("time_alignment")
        if isinstance(time_alignment_raw, Mapping):
            time_alignment: JSONObject = {}
            status = time_alignment_raw.get("status")
            policy = time_alignment_raw.get("policy")
            lag_days = time_alignment_raw.get("lag_days")
            threshold_days = time_alignment_raw.get("threshold_days")
            market_as_of = time_alignment_raw.get("market_as_of")
            filing_period_end = time_alignment_raw.get("filing_period_end")
            if isinstance(status, str) and status:
                time_alignment["status"] = status
            if isinstance(policy, str) and policy:
                time_alignment["policy"] = policy
            if isinstance(lag_days, int):
                time_alignment["lag_days"] = lag_days
            if isinstance(threshold_days, int):
                time_alignment["threshold_days"] = threshold_days
            if isinstance(market_as_of, str) and market_as_of:
                time_alignment["market_as_of"] = market_as_of
            if isinstance(filing_period_end, str) and filing_period_end:
                time_alignment["filing_period_end"] = filing_period_end
            if time_alignment:
                payload["time_alignment"] = time_alignment

    if not payload:
        return None
    return payload


def extract_time_alignment_status(
    build_metadata: Mapping[str, object] | None,
) -> str | None:
    if not isinstance(build_metadata, Mapping):
        return None
    data_freshness = build_metadata.get("data_freshness")
    if not isinstance(data_freshness, Mapping):
        return None
    time_alignment = data_freshness.get("time_alignment")
    if not isinstance(time_alignment, Mapping):
        return None
    status = time_alignment.get("status")
    if isinstance(status, str) and status:
        return status
    return None


def _extract_latest_statement_freshness(
    reports_raw: list[JSONObject],
) -> JSONObject | None:
    latest_fiscal_year: int | None = None
    latest_period_end: str | None = None

    for report in reports_raw:
        if not isinstance(report, Mapping):
            continue
        base_raw = report.get("base")
        if not isinstance(base_raw, Mapping):
            continue

        fiscal_year_value = _extract_traceable_scalar(base_raw.get("fiscal_year"))
        period_end_value = _extract_traceable_scalar(base_raw.get("period_end_date"))

        fiscal_year = _coerce_int(fiscal_year_value)
        period_end = (
            str(period_end_value)
            if isinstance(period_end_value, str | int | float)
            else None
        )
        if fiscal_year is None and period_end is None:
            continue

        if latest_fiscal_year is None or (
            fiscal_year is not None and fiscal_year > latest_fiscal_year
        ):
            latest_fiscal_year = fiscal_year
            latest_period_end = period_end
            continue

        if (
            latest_fiscal_year is not None
            and fiscal_year == latest_fiscal_year
            and latest_period_end is None
            and period_end is not None
        ):
            latest_period_end = period_end

    if latest_fiscal_year is None and latest_period_end is None:
        return None

    output: JSONObject = {}
    if latest_fiscal_year is not None:
        output["fiscal_year"] = latest_fiscal_year
    if latest_period_end is not None:
        output["period_end_date"] = latest_period_end
    return output


def _extract_traceable_scalar(value: object) -> object | None:
    if isinstance(value, Mapping):
        return value.get("value")
    return value


def _coerce_int(value: object) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(float(value))
        except ValueError:
            return None
    return None
