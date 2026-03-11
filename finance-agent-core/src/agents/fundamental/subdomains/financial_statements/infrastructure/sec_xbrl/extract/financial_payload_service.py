import logging
import os
import time
import traceback
from collections.abc import Mapping, Sequence
from datetime import date

from src.agents.fundamental.domain.shared.contracts.traceable import (
    ComputedProvenance,
    ManualProvenance,
    TraceableField,
)
from src.agents.fundamental.subdomains.forward_signals.infrastructure.sec_xbrl.forward_signals import (
    extract_forward_signals_from_xbrl_reports,
)
from src.agents.fundamental.subdomains.forward_signals.infrastructure.sec_xbrl.forward_signals_text import (
    extract_forward_signals_from_sec_text,
)
from src.interface.artifacts.artifact_model_shared import to_json
from src.shared.kernel.tools.logger import get_logger, log_event
from src.shared.kernel.types import JSONObject

from ..cache.filing_cache_service import (
    FilingCacheCoordinates,
    FilingCacheLookupResult,
    FilingCacheService,
    build_arelle_taxonomy_cache_token,
    build_default_filing_cache_service,
)
from ..fetch.filing_fetcher import call_with_sec_retry
from ..quality.dqc_efm_gate_service import (
    evaluate_xbrl_quality_gates,
    normalize_dqc_efm_issue,
)
from .factory import FinancialReportFactory
from .report_contracts import (
    FinancialReport,
    IndustrialExtension,
)

logger = get_logger(__name__)
_XBRL_DIAGNOSTICS_ENABLED = os.getenv("FUNDAMENTAL_XBRL_DIAG", "0").strip().lower() in {
    "1",
    "true",
    "yes",
}
_FINANCIAL_PAYLOAD_CACHE_FIELD_KEY = "financial_payload_v1"
_filing_cache_service = build_default_filing_cache_service()


def fetch_financial_data(ticker: str, years: int = 5) -> list[FinancialReport]:
    """
    Fetch financial data using the SECReportExtractor via FinancialReportFactory.
    Returns a list of FinancialReport objects containing Base and Extension models.
    """
    reports: list[FinancialReport] = []
    log_event(
        logger,
        event="fundamental_xbrl_fetch_started",
        message="xbrl financial data fetch started",
        fields={"ticker": ticker, "years": years},
    )

    fetched_years: set[int] = set()
    anchor_year: int | None = None

    try:
        log_event(
            logger,
            event="fundamental_xbrl_latest_attempt",
            message="xbrl latest filing fetch attempt",
            fields={"ticker": ticker},
        )
        latest_report = call_with_sec_retry(
            operation="create_report_latest",
            ticker=ticker,
            execute=lambda: FinancialReportFactory.create_latest_report(ticker),
        )
        latest_year = _report_year(latest_report)
        if latest_year is not None:
            fetched_years.add(latest_year)
            anchor_year = latest_year
        reports.append(latest_report)
        log_event(
            logger,
            event="fundamental_xbrl_latest_success",
            message="xbrl latest filing fetched",
            fields={
                "ticker": ticker,
                "actual_year": latest_year,
                "filing_metadata": latest_report.filing_metadata,
            },
        )
    except ValueError as exc:
        log_event(
            logger,
            event="fundamental_xbrl_latest_not_found",
            message="xbrl latest filing not found; fallback to fiscal year probing",
            level=logging.WARNING,
            error_code="FUNDAMENTAL_XBRL_LATEST_NOT_FOUND",
            fields={
                "ticker": ticker,
                "exception_type": type(exc).__name__,
                "exception": str(exc),
            },
        )
    except Exception as exc:
        fields: dict[str, object] = {
            "ticker": ticker,
            "exception_type": type(exc).__name__,
            "exception": str(exc),
        }
        if _XBRL_DIAGNOSTICS_ENABLED:
            fields["traceback"] = traceback.format_exc(limit=25)
        log_event(
            logger,
            event="fundamental_xbrl_latest_failed",
            message="xbrl latest filing fetch failed; fallback to fiscal year probing",
            level=logging.ERROR,
            error_code="FUNDAMENTAL_XBRL_LATEST_FETCH_FAILED",
            fields=fields,
        )

    current_year = date.today().year
    start_year = (anchor_year - 1) if anchor_year is not None else (current_year - 1)
    attempt_year = start_year
    while len(reports) < years and attempt_year > (start_year - years - 5):
        current_attempt_year = attempt_year
        try:
            log_event(
                logger,
                event="fundamental_xbrl_year_attempt",
                message="xbrl yearly report fetch attempt",
                fields={"ticker": ticker, "attempt_year": current_attempt_year},
            )
            report = call_with_sec_retry(
                operation=f"create_report_{current_attempt_year}",
                ticker=ticker,
                execute=lambda year=current_attempt_year: FinancialReportFactory.create_report(
                    ticker, year
                ),
            )

            actual_year = _report_year(report)
            if actual_year is None:
                log_event(
                    logger,
                    event="fundamental_xbrl_year_unknown",
                    message="xbrl report fetched but fiscal year missing; skipping",
                    level=logging.WARNING,
                    error_code="FUNDAMENTAL_XBRL_YEAR_UNKNOWN",
                    fields={
                        "ticker": ticker,
                        "attempt_year": current_attempt_year,
                    },
                )
            elif actual_year in fetched_years:
                log_event(
                    logger,
                    event="fundamental_xbrl_duplicate_skipped",
                    message="duplicate xbrl report skipped",
                    level=logging.WARNING,
                    error_code="FUNDAMENTAL_XBRL_DUPLICATE",
                    fields={
                        "ticker": ticker,
                        "actual_year": actual_year,
                        "attempt_year": current_attempt_year,
                    },
                )
            else:
                reports.append(report)
                fetched_years.add(actual_year)
                log_event(
                    logger,
                    event="fundamental_xbrl_year_success",
                    message="xbrl yearly report fetched",
                    fields={
                        "ticker": ticker,
                        "actual_year": actual_year,
                        "attempt_year": current_attempt_year,
                    },
                )
        except ValueError as exc:
            log_event(
                logger,
                event="fundamental_xbrl_year_not_found",
                message="xbrl yearly report not found",
                level=logging.WARNING,
                error_code="FUNDAMENTAL_XBRL_NOT_FOUND",
                fields={
                    "ticker": ticker,
                    "attempt_year": current_attempt_year,
                    "exception_type": type(exc).__name__,
                    "exception": str(exc),
                },
            )
        except Exception as exc:
            fields: dict[str, object] = {
                "ticker": ticker,
                "attempt_year": current_attempt_year,
                "exception_type": type(exc).__name__,
                "exception": str(exc),
            }
            if _XBRL_DIAGNOSTICS_ENABLED:
                fields["traceback"] = traceback.format_exc(limit=25)
            log_event(
                logger,
                event="fundamental_xbrl_year_failed",
                message="xbrl yearly report fetch failed",
                level=logging.ERROR,
                error_code="FUNDAMENTAL_XBRL_FETCH_FAILED",
                fields=fields,
            )

        attempt_year -= 1

    reports.sort(key=lambda report: _report_year(report) or -1, reverse=True)
    _apply_cross_period_derivatives(reports)

    return reports


def fetch_financial_payload(ticker: str, years: int = 5) -> dict[str, object]:
    started = time.perf_counter()
    cache_lookup = _filing_cache_service.lookup_payload(
        ticker=ticker,
        years=years,
        field_key=_FINANCIAL_PAYLOAD_CACHE_FIELD_KEY,
    )
    if cache_lookup.hit and isinstance(cache_lookup.payload, dict):
        payload = dict(cache_lookup.payload)
        payload["diagnostics"] = _merge_arelle_validation_diagnostics(
            diagnostics=payload.get("diagnostics"),
            reports_raw=payload.get("financial_reports"),
        )
        payload["diagnostics"] = _merge_arelle_runtime_diagnostics(
            diagnostics=payload.get("diagnostics"),
            reports_raw=payload.get("financial_reports"),
        )
        if payload.get("quality_gates") is None:
            payload["quality_gates"] = evaluate_xbrl_quality_gates(
                reports_raw=payload.get("financial_reports"),
                diagnostics=payload.get("diagnostics")
                if isinstance(payload.get("diagnostics"), Mapping)
                else None,
            )
        diagnostics = _merge_cache_diagnostics(
            diagnostics=payload.get("diagnostics"),
            lookup=cache_lookup,
            total_latency_ms=(time.perf_counter() - started) * 1000.0,
            payload_key_override=cache_lookup.payload_key,
        )
        payload["diagnostics"] = diagnostics
        payload.setdefault("quality_gates", None)
        log_event(
            logger,
            event="fundamental_xbrl_payload_cache_hit",
            message="financial payload cache hit",
            fields={
                "ticker": ticker,
                "years": years,
                "layer": cache_lookup.layer,
                "alias_layer": cache_lookup.alias_layer,
                "payload_key": cache_lookup.payload_key,
                "lookup_ms": round(cache_lookup.lookup_ms, 3),
            },
        )
        return payload

    log_event(
        logger,
        event="fundamental_xbrl_payload_cache_miss",
        message="financial payload cache miss",
        fields={
            "ticker": ticker,
            "years": years,
            "alias_layer": cache_lookup.alias_layer,
            "lookup_ms": round(cache_lookup.lookup_ms, 3),
        },
    )

    reports = fetch_financial_data(ticker, years=years)
    rules_sector = _infer_rules_sector_from_reports(reports)
    forward_signals: list[dict[str, object]] = []
    try:
        xbrl_signals = extract_forward_signals_from_xbrl_reports(
            ticker=ticker,
            reports=reports,
        )
        if xbrl_signals:
            forward_signals.extend(xbrl_signals)
    except Exception as exc:
        log_event(
            logger,
            event="fundamental_forward_signal_producer_failed",
            message="forward signal producer failed; proceeding without signals",
            level=logging.WARNING,
            error_code="FUNDAMENTAL_FORWARD_SIGNAL_PRODUCER_FAILED",
            fields={"ticker": ticker, "exception": str(exc)},
        )

    try:
        text_signals = extract_forward_signals_from_sec_text(
            ticker=ticker,
            rules_sector=rules_sector,
        )
        if text_signals:
            forward_signals.extend(text_signals)
    except Exception as exc:
        log_event(
            logger,
            event="fundamental_forward_signal_text_producer_failed",
            message="forward signal text producer failed; proceeding without text signals",
            level=logging.WARNING,
            error_code="FUNDAMENTAL_FORWARD_SIGNAL_TEXT_PRODUCER_FAILED",
            fields={"ticker": ticker, "exception": str(exc)},
        )

    payload: dict[str, object] = {
        "financial_reports": reports,
        "forward_signals": forward_signals,
        "diagnostics": _merge_cache_diagnostics(
            diagnostics=_merge_arelle_runtime_diagnostics(
                diagnostics=_merge_arelle_validation_diagnostics(
                    diagnostics=None,
                    reports_raw=reports,
                ),
                reports_raw=reports,
            ),
            lookup=cache_lookup,
            total_latency_ms=(time.perf_counter() - started) * 1000.0,
            payload_key_override=None,
        ),
        "quality_gates": None,
    }
    payload["quality_gates"] = evaluate_xbrl_quality_gates(
        reports_raw=reports,
        diagnostics=payload.get("diagnostics")
        if isinstance(payload.get("diagnostics"), Mapping)
        else None,
    )
    coordinates = _resolve_filing_cache_coordinates(reports)
    payload_key: str | None = None
    try:
        cache_payload = _to_cache_json_payload(payload)
        payload_key = _filing_cache_service.store_payload(
            ticker=ticker,
            years=years,
            field_key=_FINANCIAL_PAYLOAD_CACHE_FIELD_KEY,
            coordinates=coordinates,
            payload=cache_payload,
        )
    except Exception as exc:
        log_event(
            logger,
            event="fundamental_xbrl_payload_cache_store_failed",
            message="financial payload cache store failed",
            level=logging.WARNING,
            error_code="FUNDAMENTAL_XBRL_CACHE_STORE_FAILED",
            fields={
                "ticker": ticker,
                "years": years,
                "exception_type": type(exc).__name__,
                "exception": str(exc),
            },
        )

    payload["diagnostics"] = _merge_cache_diagnostics(
        diagnostics=payload.get("diagnostics"),
        lookup=cache_lookup,
        total_latency_ms=(time.perf_counter() - started) * 1000.0,
        payload_key_override=payload_key,
    )
    if payload_key is not None:
        log_event(
            logger,
            event="fundamental_xbrl_payload_cache_stored",
            message="financial payload cached",
            fields={
                "ticker": ticker,
                "years": years,
                "payload_key": payload_key,
                "cik": coordinates.cik,
                "accession": coordinates.accession,
                "taxonomy_version": coordinates.taxonomy_version,
            },
        )
    return payload


def set_filing_cache_service_for_tests(cache_service: FilingCacheService) -> None:
    global _filing_cache_service
    _filing_cache_service = cache_service


def reset_filing_cache_service_for_tests() -> None:
    global _filing_cache_service
    _filing_cache_service = build_default_filing_cache_service()


def _resolve_filing_cache_coordinates(
    reports: list[FinancialReport],
) -> FilingCacheCoordinates:
    if not reports:
        return FilingCacheCoordinates.unknown()
    report = reports[0]
    cik = _cache_token(report.base.cik.value)

    filing_metadata = (
        report.filing_metadata if isinstance(report.filing_metadata, dict) else {}
    )
    accession = _cache_token(filing_metadata.get("accession_number"))
    taxonomy_version = build_arelle_taxonomy_cache_token(
        taxonomy_version=filing_metadata.get("taxonomy_version"),
        validation_mode=filing_metadata.get("arelle_validation_mode"),
        disclosure_system=filing_metadata.get("arelle_disclosure_system"),
        plugins=_cache_sequence(filing_metadata.get("arelle_plugins")),
        packages=_cache_sequence(filing_metadata.get("arelle_packages")),
        arelle_version=filing_metadata.get("arelle_version"),
    )
    return FilingCacheCoordinates(
        cik=cik,
        accession=accession,
        taxonomy_version=taxonomy_version,
    )


def _cache_token(value: object) -> str:
    if not isinstance(value, str):
        return "unknown"
    normalized = value.strip()
    return normalized if normalized else "unknown"


def _cache_sequence(value: object) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        return ()
    normalized: list[str] = []
    for item in value:
        if not isinstance(item, str):
            continue
        token = item.strip()
        if token:
            normalized.append(token)
    return tuple(normalized)


def _to_cache_json_payload(payload: dict[str, object]) -> JSONObject:
    parsed = to_json(payload, "sec_xbrl.financial_payload_cache")
    if not isinstance(parsed, dict):
        raise TypeError("sec_xbrl.financial_payload_cache must serialize to object")
    normalized: JSONObject = {}
    for key, value in parsed.items():
        if not isinstance(key, str):
            raise TypeError("sec_xbrl.financial_payload_cache has non-string key")
        normalized[key] = value
    return normalized


def _merge_cache_diagnostics(
    *,
    diagnostics: object,
    lookup: FilingCacheLookupResult,
    total_latency_ms: float,
    payload_key_override: str | None,
) -> dict[str, object]:
    merged: dict[str, object] = (
        dict(diagnostics) if isinstance(diagnostics, dict) else {}
    )
    stats = _filing_cache_service.stats_snapshot()
    merged["cache"] = {
        "cache_hit": lookup.hit,
        "cache_layer": lookup.layer or "MISS",
        "cache_alias_layer": lookup.alias_layer or "MISS",
        "cache_lookup_ms": round(lookup.lookup_ms, 3),
        "total_latency_ms": round(total_latency_ms, 3),
        "alias_cache_key": lookup.alias_key,
        "payload_cache_key": payload_key_override or lookup.payload_key,
        "l1_hits": stats.get("l1_hits", 0),
        "l1_misses": stats.get("l1_misses", 0),
        "l2_hits": stats.get("l2_hits", 0),
        "l2_misses": stats.get("l2_misses", 0),
        "l3_hits": stats.get("l3_hits", 0),
        "l3_misses": stats.get("l3_misses", 0),
    }
    return merged


def _merge_arelle_validation_diagnostics(
    *,
    diagnostics: object,
    reports_raw: object,
) -> dict[str, object]:
    merged: dict[str, object] = (
        dict(diagnostics) if isinstance(diagnostics, dict) else {}
    )
    existing_raw = merged.get("dqc_efm_issues")
    existing_issues = _normalize_quality_issue_list(existing_raw)
    report_issues = _extract_quality_issues_from_reports(reports_raw)
    combined = _dedupe_quality_issues(existing_issues + report_issues)
    if combined:
        merged["dqc_efm_issues"] = combined
        merged["dqc_efm_issue_count"] = len(combined)
    else:
        merged.setdefault("dqc_efm_issues", [])
        merged["dqc_efm_issue_count"] = 0
    return merged


def _merge_arelle_runtime_diagnostics(
    *,
    diagnostics: object,
    reports_raw: object,
) -> dict[str, object]:
    merged: dict[str, object] = (
        dict(diagnostics) if isinstance(diagnostics, dict) else {}
    )
    runtime_entries = _extract_arelle_runtime_entries_from_reports(reports_raw)
    if not runtime_entries:
        return merged

    parse_latencies = [
        value
        for value in (
            _as_float(entry.get("parse_latency_ms")) for entry in runtime_entries
        )
        if value is not None
    ]
    lock_waits = [
        value
        for value in (_as_float(entry.get("lock_wait_ms")) for entry in runtime_entries)
        if value is not None
    ]
    isolation_modes = sorted(
        {
            mode
            for mode in (
                _normalize_string(entry.get("isolation_mode"))
                for entry in runtime_entries
            )
            if mode is not None
        }
    )
    validation_modes = sorted(
        {
            mode
            for mode in (
                _normalize_string(entry.get("validation_mode"))
                for entry in runtime_entries
            )
            if mode is not None
        }
    )

    runtime_summary: dict[str, object] = {
        "report_count": len(runtime_entries),
        "parse_latency_ms_avg": _round_or_none(_average(parse_latencies)),
        "parse_latency_ms_max": _round_or_none(max(parse_latencies, default=None)),
        "runtime_lock_wait_ms_avg": _round_or_none(_average(lock_waits)),
        "runtime_lock_wait_ms_max": _round_or_none(max(lock_waits, default=None)),
        "isolation_modes": isolation_modes,
        "validation_modes": validation_modes,
    }
    merged["arelle_runtime"] = runtime_summary
    return merged


def _extract_arelle_runtime_entries_from_reports(
    reports_raw: object,
) -> list[dict[str, object]]:
    if not isinstance(reports_raw, Sequence) or isinstance(reports_raw, str | bytes):
        return []
    entries: list[dict[str, object]] = []
    for report in reports_raw:
        filing_metadata = _extract_filing_metadata(report)
        if not isinstance(filing_metadata, Mapping):
            continue
        parse_latency = _as_float(filing_metadata.get("arelle_parse_latency_ms"))
        lock_wait = _as_float(filing_metadata.get("arelle_runtime_lock_wait_ms"))
        isolation_mode = _normalize_string(
            filing_metadata.get("arelle_runtime_isolation_mode")
        )
        validation_mode = _normalize_string(
            filing_metadata.get("arelle_validation_mode")
        )
        if (
            parse_latency is None
            and lock_wait is None
            and isolation_mode is None
            and validation_mode is None
        ):
            continue
        entries.append(
            {
                "parse_latency_ms": parse_latency,
                "lock_wait_ms": lock_wait,
                "isolation_mode": isolation_mode,
                "validation_mode": validation_mode,
            }
        )
    return entries


def _extract_quality_issues_from_reports(
    reports_raw: object,
) -> list[dict[str, object]]:
    if not isinstance(reports_raw, Sequence) or isinstance(reports_raw, str | bytes):
        return []

    issues: list[dict[str, object]] = []
    for report in reports_raw:
        filing_metadata = _extract_filing_metadata(report)
        if not isinstance(filing_metadata, Mapping):
            continue
        raw_issues = filing_metadata.get("arelle_validation_issues")
        issues.extend(_normalize_quality_issue_list(raw_issues))
    return issues


def _extract_filing_metadata(report: object) -> Mapping[str, object] | None:
    if isinstance(report, FinancialReport):
        filing_metadata = report.filing_metadata
        return filing_metadata if isinstance(filing_metadata, Mapping) else None
    if isinstance(report, Mapping):
        filing_metadata = report.get("filing_metadata")
        if isinstance(filing_metadata, Mapping):
            normalized: dict[str, object] = {}
            for key, value in filing_metadata.items():
                if isinstance(key, str):
                    normalized[key] = value
            return normalized
    return None


def _normalize_quality_issue_list(raw_issues: object) -> list[dict[str, object]]:
    if not isinstance(raw_issues, Sequence) or isinstance(raw_issues, str | bytes):
        return []

    normalized: list[dict[str, object]] = []
    for raw_issue in raw_issues:
        if not isinstance(raw_issue, Mapping):
            continue
        normalized_issue = _normalize_quality_issue(raw_issue)
        if normalized_issue is None:
            continue
        normalized.append(normalized_issue)
    return normalized


def _normalize_quality_issue(
    raw_issue: Mapping[str, object],
) -> dict[str, object] | None:
    normalized = normalize_dqc_efm_issue(raw_issue)
    if not isinstance(normalized, dict):
        return None
    return dict(normalized)


def _dedupe_quality_issues(
    issues: list[dict[str, object]],
) -> list[dict[str, object]]:
    deduped: list[dict[str, object]] = []
    seen: set[tuple[str, str, str, str, str]] = set()
    for issue in issues:
        key = (
            _normalize_string(issue.get("code")) or "ARELLE_VALIDATION_ISSUE",
            _normalize_string(issue.get("source")) or "ARELLE",
            _normalize_string(issue.get("severity")) or "error",
            _normalize_string(issue.get("message")) or "ARELLE_VALIDATION_ISSUE",
            _normalize_string(issue.get("field_key")) or "",
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(issue)
    return deduped


def _normalize_string(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    token = value.strip()
    return token or None


def _as_float(value: object) -> float | None:
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        token = value.strip()
        if not token:
            return None
        try:
            return float(token)
        except ValueError:
            return None
    return None


def _average(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / float(len(values))


def _round_or_none(value: float | None) -> float | None:
    if value is None:
        return None
    return round(value, 3)


def _infer_rules_sector_from_reports(reports: list[FinancialReport]) -> str | None:
    for report in reports:
        normalized_type = str(report.industry_type or "").strip().lower()
        if not normalized_type:
            continue
        if "financial" in normalized_type:
            return "financials"
    return None


def _report_year(report: FinancialReport) -> int | None:
    raw = report.base.fiscal_year.value
    if raw is None:
        return None
    if isinstance(raw, int):
        return raw
    if isinstance(raw, float):
        return int(raw)
    if isinstance(raw, str):
        try:
            return int(float(raw))
        except ValueError:
            return None
    return None


def _apply_cross_period_derivatives(reports: list[FinancialReport]) -> None:
    if len(reports) < 2:
        return

    def report_year(report: FinancialReport) -> int:
        value = report.base.fiscal_year.value
        if value is None:
            return -1
        try:
            return int(value)
        except (TypeError, ValueError):
            return -1

    def calc_delta(
        current: TraceableField[float],
        previous: TraceableField[float],
        name: str,
        expression: str,
    ) -> TraceableField[float]:
        if current.value is None or previous.value is None:
            return TraceableField(
                name=name,
                value=None,
                provenance=ManualProvenance(
                    description=f"Missing inputs for {expression}"
                ),
            )
        value = float(current.value) - float(previous.value)
        return TraceableField(
            name=name,
            value=value,
            provenance=ComputedProvenance(
                op_code="SUB",
                expression=expression,
                inputs={
                    "Current": current,
                    "Previous": previous,
                },
            ),
        )

    def calc_reinvestment_rate(
        capex: TraceableField[float] | None,
        da: TraceableField[float],
        wc_delta: TraceableField[float],
        nopat: TraceableField[float],
    ) -> TraceableField[float]:
        if capex is None:
            return TraceableField(
                name="Reinvestment Rate",
                value=None,
                provenance=ManualProvenance(
                    description="Missing CapEx for reinvestment rate"
                ),
            )
        if (
            capex.value is None
            or da.value is None
            or wc_delta.value is None
            or nopat.value in (None, 0)
        ):
            return TraceableField(
                name="Reinvestment Rate",
                value=None,
                provenance=ManualProvenance(
                    description="Missing inputs for reinvestment rate"
                ),
            )
        value = (float(capex.value) - float(da.value) + float(wc_delta.value)) / float(
            nopat.value
        )
        return TraceableField(
            name="Reinvestment Rate",
            value=value,
            provenance=ComputedProvenance(
                op_code="REINVESTMENT_RATE",
                expression="(CapEx - D&A + delta WC) / NOPAT",
                inputs={
                    "CapEx": capex,
                    "Depreciation & Amortization": da,
                    "Working Capital Delta": wc_delta,
                    "NOPAT": nopat,
                },
            ),
        )

    reports_sorted = sorted(reports, key=report_year, reverse=True)
    for idx, report in enumerate(reports_sorted):
        if idx + 1 >= len(reports_sorted):
            continue
        prev = reports_sorted[idx + 1]

        wc_delta = calc_delta(
            report.base.working_capital,
            prev.base.working_capital,
            "Working Capital Delta",
            "WorkingCapital(Current) - WorkingCapital(Previous)",
        )
        report.base.working_capital_delta = wc_delta

        capex_tf = None
        if isinstance(report.extension, IndustrialExtension):
            capex_tf = report.extension.capex

        reinvestment_rate = calc_reinvestment_rate(
            capex_tf,
            report.base.depreciation_and_amortization,
            wc_delta,
            report.base.nopat,
        )
        report.base.reinvestment_rate = reinvestment_rate
