from __future__ import annotations

import logging
import os

import pandas as pd
from edgar import Company
from tabulate import tabulate

from src.shared.kernel.tools.logger import get_logger, log_event

from .extractor_models import (
    SearchConfig,
    SearchStats,
    SearchType,
    SECExtractResult,
)
from .extractor_search_processing_service import (
    apply_search_type_mask,
    build_base_mask,
    filter_and_format_results,
    identify_dimension_columns,
    period_sort_key,
)
from .filing_fetcher import call_with_sec_retry
from .providers.arelle_engine import (
    ArelleEngineParseError,
    ArelleEngineUnavailableError,
    ArelleXbrlEngine,
)
from .providers.engine_contracts import (
    ArelleParseResult,
    XbrlAttachment,
    XbrlAttachmentBundle,
)
from .sec_identity_service import ensure_sec_identity

logger = get_logger(__name__)
_XBRL_DIAGNOSTICS_ENABLED = os.getenv("FUNDAMENTAL_XBRL_DIAG", "0").strip().lower() in {
    "1",
    "true",
    "yes",
}
_REQUIRED_XBRL_COLUMNS = ("concept", "value", "period_key")
_XBRL_INSTANCE_DESCRIPTIONS = {
    "XBRL INSTANCE DOCUMENT",
    "XBRL INSTANCE FILE",
    "EXTRACTED XBRL INSTANCE DOCUMENT",
}

__all__ = [
    "SearchConfig",
    "SearchType",
    "SECExtractResult",
    "SECReportExtractor",
]


class SECReportExtractor:
    def __init__(self, ticker: str, fiscal_year: int | None):
        self.ticker = ticker
        self.fiscal_year = fiscal_year
        self.standard_industrial_classification_code: int | None = None
        self.df: pd.DataFrame | None = None
        self.actual_date: str | None = None
        self.real_dim_cols: list[str] = []
        self.selected_filing_metadata: dict[str, object] | None = None
        self._load_report_data()

    def _load_report_data(self) -> None:
        log_event(
            logger,
            event="fundamental_xbrl_report_load_started",
            message="xbrl report data initialization started",
            fields={"ticker": self.ticker, "fiscal_year": self.fiscal_year},
        )

        ensure_sec_identity()

        company = call_with_sec_retry(
            operation="company_init",
            ticker=self.ticker,
            execute=lambda: Company(self.ticker),
        )
        self.standard_industrial_classification_code = call_with_sec_retry(
            operation="company_sic",
            ticker=self.ticker,
            execute=lambda: company.sic,
        )
        filings = _fetch_annual_filings(
            company=company,
            ticker=self.ticker,
            fiscal_year=self.fiscal_year,
        )

        target_filing, selection_mode = _select_target_filing(
            filings=filings,
            requested_fiscal_year=self.fiscal_year,
        )
        if not target_filing:
            raise ValueError(f"找不到 {self.ticker} 報告。")
        self.selected_filing_metadata = _build_selected_filing_metadata(
            filing=target_filing,
            requested_fiscal_year=self.fiscal_year,
            selection_mode=selection_mode,
        )
        log_event(
            logger,
            event="fundamental_xbrl_report_filing_selected",
            message="xbrl filing selected for report extraction",
            fields={
                "ticker": self.ticker,
                "requested_fiscal_year": self.fiscal_year,
                "selection_mode": selection_mode,
                "selected_filing": self.selected_filing_metadata,
            },
        )

        xb = call_with_sec_retry(
            operation=f"filing_xbrl_{self.fiscal_year or 'latest'}",
            ticker=self.ticker,
            execute=target_filing.xbrl,
        )
        if not xb:
            raise ValueError(f"No XBRL data found for {self.ticker}")

        self.df, parse_metadata = _resolve_xbrl_facts_dataframe(
            primary_df=xb.facts.to_dataframe(),
            filing=target_filing,
            ticker=self.ticker,
            fiscal_year=self.fiscal_year,
        )
        if isinstance(parse_metadata, dict) and isinstance(
            self.selected_filing_metadata, dict
        ):
            self.selected_filing_metadata.update(parse_metadata)
        _validate_xbrl_dataframe_schema(
            df=self.df,
            ticker=self.ticker,
            fiscal_year=self.fiscal_year,
        )

        dei_mask = self.df["concept"].str.contains(
            "DocumentPeriodEndDate", case=False, na=False
        )
        if dei_mask.any():
            self.actual_date = str(self.df[dei_mask].iloc[0]["value"])[:10]
            log_event(
                logger,
                event="fundamental_xbrl_report_anchor_date_locked",
                message="xbrl report anchor date locked",
                fields={"ticker": self.ticker, "actual_date": self.actual_date},
            )

        self.real_dim_cols = identify_dimension_columns(list(self.df.columns))

    def get_selected_filing_metadata(self) -> dict[str, object] | None:
        if not isinstance(self.selected_filing_metadata, dict):
            return None
        return dict(self.selected_filing_metadata)

    def search(self, config: SearchConfig) -> list[SECExtractResult]:
        if self.df is None:
            return []

        mask = build_base_mask(df=self.df, actual_date=self.actual_date, config=config)
        mask = apply_search_type_mask(
            df=self.df,
            real_dim_cols=self.real_dim_cols,
            base_mask=mask,
            config=config,
        )

        matches = self.df[mask].copy()
        if matches.empty:
            log_event(
                logger,
                event="fundamental_xbrl_search_no_matches",
                message="xbrl search returned no matches",
                level=logging.DEBUG,
                fields={
                    "ticker": self.ticker,
                    "concept_regex": config.concept_regex,
                    "search_type": config.type_name,
                },
            )
            return []

        stats = SearchStats()
        final_rows = filter_and_format_results(
            matches=matches,
            config=config,
            real_dim_cols=self.real_dim_cols,
            stats=stats,
        )
        stats.log(logger)
        final_rows.sort(key=lambda row: period_sort_key(row.period_key), reverse=True)
        return final_rows

    def sic_code(self) -> int | None:
        return self.standard_industrial_classification_code

    def debug_asset_issue(self, tag: str) -> None:
        if self.df is None:
            return

        processed_regex = tag if ":" in tag else f".*:{tag}$"
        mask = self.df["concept"].str.contains(
            processed_regex, flags=0, na=False, case=False
        )
        matches = self.df[mask].copy()

        if matches.empty:
            log_event(
                logger,
                event="fundamental_xbrl_asset_debug_no_rows",
                message="asset debug query returned no rows; tag may differ",
                level=logging.WARNING,
                error_code="FUNDAMENTAL_XBRL_ASSET_DEBUG_EMPTY",
                fields={"ticker": self.ticker, "tag": tag},
            )
            return

        active_dim_cols = (
            matches[self.real_dim_cols].dropna(axis=1, how="all").columns.tolist()
            if self.real_dim_cols
            else []
        )

        log_event(
            logger,
            event="fundamental_xbrl_asset_debug_summary",
            message="asset debug summary generated",
            fields={
                "ticker": self.ticker,
                "rows": len(matches),
                "active_dimensions": active_dim_cols,
            },
        )

        display_cols = ["period_end", "value"] + active_dim_cols
        log_event(
            logger,
            event="fundamental_xbrl_asset_debug_table",
            message="asset debug table generated",
            fields={
                "ticker": self.ticker,
                "table": tabulate(
                    matches[display_cols], headers="keys", tablefmt="fancy_grid"
                ),
            },
        )


def _validate_xbrl_dataframe_schema(
    *,
    df: pd.DataFrame,
    ticker: str,
    fiscal_year: int | None,
) -> None:
    missing_columns = [
        column for column in _REQUIRED_XBRL_COLUMNS if column not in df.columns
    ]
    has_rows = len(df) > 0
    if not missing_columns and has_rows:
        if _XBRL_DIAGNOSTICS_ENABLED:
            log_event(
                logger,
                event="fundamental_xbrl_dataframe_schema_ok",
                message="xbrl dataframe schema validated",
                level=logging.DEBUG,
                fields={
                    "ticker": ticker,
                    "fiscal_year": fiscal_year,
                    "row_count": len(df),
                    "column_count": len(df.columns),
                    "columns_sample": list(df.columns[:30]),
                },
            )
        return

    fields: dict[str, object] = {
        "ticker": ticker,
        "fiscal_year": fiscal_year,
        "missing_columns": missing_columns,
        "row_count": len(df),
        "column_count": len(df.columns),
    }
    if not has_rows:
        fields["empty_dataframe"] = True
    if _XBRL_DIAGNOSTICS_ENABLED:
        fields["available_columns"] = list(df.columns)
        if len(df) > 0:
            first_row = df.iloc[0].to_dict()
            fields["first_row_preview"] = {
                str(key): str(value)[:120] for key, value in first_row.items()
            }

    log_event(
        logger,
        event="fundamental_xbrl_dataframe_schema_invalid",
        message="xbrl dataframe missing required columns",
        level=logging.ERROR,
        error_code="FUNDAMENTAL_XBRL_SCHEMA_INVALID",
        fields=fields,
    )
    if missing_columns:
        raise ValueError(
            "XBRL dataframe missing required columns: " + ", ".join(missing_columns)
        )
    raise ValueError("XBRL dataframe contains zero rows")


def _resolve_xbrl_facts_dataframe(
    *,
    primary_df: pd.DataFrame,
    filing: object,
    ticker: str,
    fiscal_year: int | None,
) -> tuple[pd.DataFrame, dict[str, object] | None]:
    missing_columns = [
        column for column in _REQUIRED_XBRL_COLUMNS if column not in primary_df.columns
    ]
    if not missing_columns and len(primary_df) > 0:
        return primary_df, None

    log_event(
        logger,
        event="fundamental_xbrl_arelle_candidate_resolution_started",
        message="xbrl facts dataframe invalid; attempting arelle candidate resolution",
        level=logging.WARNING,
        error_code="FUNDAMENTAL_XBRL_ARELLE_CANDIDATE_RESOLUTION",
        fields={
            "ticker": ticker,
            "fiscal_year": fiscal_year,
            "primary_row_count": len(primary_df),
            "primary_column_count": len(primary_df.columns),
            "primary_missing_columns": missing_columns,
        },
    )

    fallback_result = _build_dataframe_from_filing_attachments(
        filing=filing,
        ticker=ticker,
        fiscal_year=fiscal_year,
    )
    if fallback_result is None:
        return primary_df, None

    fallback_df, instance_document, arelle_metadata = fallback_result
    log_event(
        logger,
        event="fundamental_xbrl_arelle_candidate_resolution_succeeded",
        message="arelle candidate resolution produced usable facts dataframe",
        level=logging.INFO,
        fields={
            "ticker": ticker,
            "fiscal_year": fiscal_year,
            "instance_document": instance_document,
            "row_count": len(fallback_df),
            "column_count": len(fallback_df.columns),
        },
    )
    return fallback_df, arelle_metadata


def _build_dataframe_from_filing_attachments(
    *,
    filing: object,
    ticker: str,
    fiscal_year: int | None,
) -> tuple[pd.DataFrame, str, dict[str, object]] | None:
    data_files = _get_filing_data_files(filing)
    if not data_files:
        log_event(
            logger,
            event="fundamental_xbrl_arelle_candidate_no_data_files",
            message="arelle candidate resolution skipped; filing has no data files",
            level=logging.WARNING,
            error_code="FUNDAMENTAL_XBRL_ARELLE_NO_DATA_FILES",
            fields={"ticker": ticker, "fiscal_year": fiscal_year},
        )
        return None

    instance_candidates = _select_instance_candidates(data_files)
    if not instance_candidates:
        log_event(
            logger,
            event="fundamental_xbrl_arelle_candidate_no_candidates",
            message="arelle candidate resolution skipped; no instance candidates found",
            level=logging.WARNING,
            error_code="FUNDAMENTAL_XBRL_ARELLE_NO_CANDIDATES",
            fields={"ticker": ticker, "fiscal_year": fiscal_year},
        )
        return None

    arelle_engine = ArelleXbrlEngine()
    for candidate in instance_candidates:
        content = _attachment_content_text(candidate)
        if not content:
            continue

        candidate_document = str(getattr(candidate, "document", "unknown"))
        candidate_type = str(getattr(candidate, "document_type", ""))
        arelle_bundle = _build_arelle_attachment_bundle(
            data_files=data_files,
            candidate_instance_document=candidate_document,
            ticker=ticker,
            fiscal_year=fiscal_year,
        )
        if arelle_bundle is None:
            continue

        try:
            arelle_result = arelle_engine.parse_attachment_bundle(bundle=arelle_bundle)
        except ArelleEngineUnavailableError as exc:
            log_event(
                logger,
                event="fundamental_xbrl_arelle_required_unavailable",
                message="arelle runtime unavailable; hard-failing because legacy fallback is disabled",
                level=logging.ERROR,
                error_code="FUNDAMENTAL_XBRL_ARELLE_REQUIRED_UNAVAILABLE",
                fields={
                    "ticker": ticker,
                    "fiscal_year": fiscal_year,
                    "exception_type": type(exc).__name__,
                    "exception": str(exc),
                },
            )
            raise
        except ArelleEngineParseError as exc:
            log_event(
                logger,
                event="fundamental_xbrl_arelle_candidate_failed",
                message="arelle candidate parse failed; trying next arelle candidate",
                level=logging.WARNING,
                error_code="FUNDAMENTAL_XBRL_ARELLE_CANDIDATE_FAILED",
                fields={
                    "ticker": ticker,
                    "fiscal_year": fiscal_year,
                    "instance_document": candidate_document,
                    "instance_document_type": candidate_type,
                    "exception_type": type(exc).__name__,
                    "exception": str(exc),
                },
            )
            continue

        arelle_df = arelle_result.facts_dataframe
        missing_columns = [
            column
            for column in _REQUIRED_XBRL_COLUMNS
            if column not in arelle_df.columns
        ]
        if not missing_columns and len(arelle_df) > 0:
            arelle_metadata = _build_arelle_filing_metadata(arelle_result)
            log_event(
                logger,
                event="fundamental_xbrl_arelle_candidate_succeeded",
                message="arelle candidate produced usable facts dataframe",
                level=logging.INFO,
                fields={
                    "ticker": ticker,
                    "fiscal_year": fiscal_year,
                    "instance_document": candidate_document,
                    "row_count": len(arelle_df),
                    "column_count": len(arelle_df.columns),
                    "loaded_attachment_count": arelle_result.loaded_attachment_count,
                    "schema_loaded": arelle_result.schema_loaded,
                    "label_loaded": arelle_result.label_loaded,
                    "presentation_loaded": arelle_result.presentation_loaded,
                    "calculation_loaded": arelle_result.calculation_loaded,
                    "definition_loaded": arelle_result.definition_loaded,
                    "validation_issue_count": len(arelle_result.validation_issues),
                    "parse_latency_ms": (
                        round(arelle_result.parse_latency_ms, 3)
                        if isinstance(arelle_result.parse_latency_ms, float)
                        else None
                    ),
                    "validation_enabled": (
                        arelle_result.runtime_metadata.validation_enabled
                        if arelle_result.runtime_metadata is not None
                        else None
                    ),
                    "validation_mode": (
                        arelle_result.runtime_metadata.mode
                        if arelle_result.runtime_metadata is not None
                        else None
                    ),
                    "arelle_version": (
                        arelle_result.runtime_metadata.arelle_version
                        if arelle_result.runtime_metadata is not None
                        else None
                    ),
                },
            )
            return arelle_df, candidate_document, arelle_metadata

        log_event(
            logger,
            event="fundamental_xbrl_arelle_candidate_invalid",
            message="arelle candidate produced invalid facts dataframe",
            level=logging.WARNING,
            error_code="FUNDAMENTAL_XBRL_ARELLE_CANDIDATE_INVALID",
            fields={
                "ticker": ticker,
                "fiscal_year": fiscal_year,
                "instance_document": candidate_document,
                "instance_document_type": candidate_type,
                "row_count": len(arelle_df),
                "column_count": len(arelle_df.columns),
                "missing_columns": missing_columns,
            },
        )

    return None


def _build_arelle_filing_metadata(
    arelle_result: ArelleParseResult,
) -> dict[str, object]:
    metadata: dict[str, object] = {
        "arelle_validation_issue_count": len(arelle_result.validation_issues),
        "arelle_validation_issues": [
            _build_arelle_issue_payload(issue)
            for issue in arelle_result.validation_issues
        ],
    }
    if isinstance(arelle_result.parse_latency_ms, float):
        metadata["arelle_parse_latency_ms"] = round(arelle_result.parse_latency_ms, 3)
    runtime_metadata = arelle_result.runtime_metadata
    if runtime_metadata is None:
        return metadata
    metadata["arelle_validation_mode"] = runtime_metadata.mode
    metadata["arelle_validation_enabled"] = runtime_metadata.validation_enabled
    metadata["arelle_disclosure_system"] = runtime_metadata.disclosure_system
    metadata["arelle_plugins"] = list(runtime_metadata.plugins)
    metadata["arelle_packages"] = list(runtime_metadata.packages)
    metadata["arelle_version"] = runtime_metadata.arelle_version
    metadata["arelle_runtime_isolation_mode"] = runtime_metadata.runtime_isolation_mode
    if isinstance(runtime_metadata.runtime_lock_wait_ms, float):
        metadata["arelle_runtime_lock_wait_ms"] = round(
            runtime_metadata.runtime_lock_wait_ms, 3
        )
    return metadata


def _build_arelle_issue_payload(issue: object) -> dict[str, object]:
    code = str(getattr(issue, "code", "") or "").strip() or "ARELLE_VALIDATION_ISSUE"
    source = str(getattr(issue, "source", "") or "").strip() or "ARELLE"
    severity = str(getattr(issue, "severity", "") or "").strip() or "error"
    message = str(getattr(issue, "message", "") or "").strip() or code
    payload: dict[str, object] = {
        "code": code,
        "source": source,
        "severity": severity,
        "message": message,
    }
    blocking = getattr(issue, "blocking", None)
    if isinstance(blocking, bool):
        payload["blocking"] = blocking
    field_key = getattr(issue, "field_key", None)
    if isinstance(field_key, str) and field_key.strip():
        payload["field_key"] = field_key.strip()
    concept = getattr(issue, "concept", None)
    if isinstance(concept, str) and concept.strip():
        payload["concept"] = concept.strip()
    context_id = getattr(issue, "context_id", None)
    if isinstance(context_id, str) and context_id.strip():
        payload["context_id"] = context_id.strip()
    return payload


def _build_arelle_attachment_bundle(
    *,
    data_files: list[object],
    candidate_instance_document: str,
    ticker: str,
    fiscal_year: int | None,
) -> XbrlAttachmentBundle | None:
    attachments: list[XbrlAttachment] = []
    has_instance_document = False
    for data_file in data_files:
        content = _attachment_content_text(data_file)
        if content is None:
            continue
        document = str(getattr(data_file, "document", "") or "").strip()
        if not document:
            continue
        document_type = str(getattr(data_file, "document_type", "") or "")
        description_raw = getattr(data_file, "description", None)
        description = (
            str(description_raw).strip()
            if isinstance(description_raw, str) and description_raw.strip()
            else None
        )
        attachments.append(
            XbrlAttachment(
                document=document,
                document_type=document_type,
                description=description,
                content=content,
            )
        )
        if document == candidate_instance_document:
            has_instance_document = True

    if not attachments or not has_instance_document:
        log_event(
            logger,
            event="fundamental_xbrl_arelle_bundle_skipped",
            message="arelle attachment bundle unavailable for candidate",
            level=logging.WARNING,
            error_code="FUNDAMENTAL_XBRL_ARELLE_BUNDLE_MISSING",
            fields={
                "ticker": ticker,
                "fiscal_year": fiscal_year,
                "candidate_instance_document": candidate_instance_document,
                "attachment_count": len(attachments),
                "has_instance_document": has_instance_document,
            },
        )
        return None

    return XbrlAttachmentBundle(
        ticker=ticker,
        fiscal_year=fiscal_year,
        instance_document=candidate_instance_document,
        attachments=tuple(attachments),
    )


def _get_filing_data_files(filing: object) -> list[object]:
    attachments = getattr(filing, "attachments", None)
    if attachments is None:
        return []
    data_files = getattr(attachments, "data_files", None)
    if not isinstance(data_files, list):
        return []
    return [item for item in data_files if item is not None]


def _select_instance_candidates(data_files: list[object]) -> list[object]:
    candidates: list[tuple[int, object]] = []
    for attachment in data_files:
        document = str(getattr(attachment, "document", ""))
        description = str(getattr(attachment, "description", "")).upper()
        doc_type = str(getattr(attachment, "document_type", "")).upper()
        extension = str(getattr(attachment, "extension", "")).lower()
        if extension not in {".xml", ".xbrl"}:
            continue

        looks_like_instance = (
            doc_type == "EX-101.INS"
            or description in _XBRL_INSTANCE_DESCRIPTIONS
            or "instance" in description.lower()
            or document.lower().endswith("_htm.xml")
        )
        if not looks_like_instance:
            continue

        priority = 4
        if description in _XBRL_INSTANCE_DESCRIPTIONS:
            priority = 0
        elif doc_type == "EX-101.INS":
            priority = 1
        elif document.lower().endswith("_htm.xml"):
            priority = 2
        candidates.append((priority, attachment))

    candidates.sort(key=lambda item: item[0])
    return [attachment for _priority, attachment in candidates]


def _attachment_content_text(attachment: object) -> str | None:
    content = getattr(attachment, "content", None)
    if isinstance(content, bytes):
        return content.decode("utf-8", errors="replace")
    if isinstance(content, str):
        return content
    return None


def _fetch_annual_filings(*, company: Company, ticker: str, fiscal_year: int | None):
    if fiscal_year is None:
        return call_with_sec_retry(
            operation="get_filings_10-K_latest",
            ticker=ticker,
            execute=lambda: company.get_filings(
                form="10-K",
                amendments=False,
            ),
        )
    return call_with_sec_retry(
        operation=f"get_filings_10-K_{fiscal_year}",
        ticker=ticker,
        execute=lambda: company.get_filings(
            form="10-K",
            year=[fiscal_year, fiscal_year + 1],
            amendments=False,
        ),
    )


def _select_target_filing(
    *,
    filings: object,
    requested_fiscal_year: int | None,
) -> tuple[object | None, str]:
    filing_items = _collect_filing_items(filings)
    if requested_fiscal_year is not None:
        matched_fiscal_year = [
            filing
            for filing in filing_items
            if _coerce_year(getattr(filing, "period_of_report", None))
            == requested_fiscal_year
        ]
        if matched_fiscal_year:
            selected = _latest_filing(matched_fiscal_year)
            if selected is not None:
                return selected, "fiscal_year_match"

    selected_latest = _latest_filing(filing_items)
    if selected_latest is not None:
        return selected_latest, "latest_available"

    latest_fn = getattr(filings, "latest", None)
    if callable(latest_fn):
        fallback = latest_fn()
        if fallback is not None:
            return fallback, "latest_fallback"

    return None, "missing"


def _collect_filing_items(filings: object) -> list[object]:
    try:
        return [item for item in filings if item is not None]
    except TypeError:
        return []


def _latest_filing(filings: list[object]) -> object | None:
    if not filings:
        return None
    return max(
        filings,
        key=lambda filing: (
            _timestamp_score(getattr(filing, "accepted_datetime", None)),
            _timestamp_score(getattr(filing, "filing_date", None)),
            _timestamp_score(getattr(filing, "period_of_report", None)),
            str(getattr(filing, "accession_number", "") or ""),
        ),
    )


def _timestamp_score(value: object) -> int:
    parsed = pd.to_datetime(value, errors="coerce", utc=True)
    if pd.isna(parsed):
        return -1
    return int(parsed.value)


def _coerce_year(value: object) -> int | None:
    parsed = pd.to_datetime(value, errors="coerce", utc=True)
    if pd.isna(parsed):
        return None
    return int(parsed.year)


def _normalize_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized if normalized else None


def _build_selected_filing_metadata(
    *,
    filing: object,
    requested_fiscal_year: int | None,
    selection_mode: str,
) -> dict[str, object]:
    period_of_report = _normalize_text(getattr(filing, "period_of_report", None))
    matched_fiscal_year = _coerce_year(period_of_report)
    return {
        "form": _normalize_text(getattr(filing, "form", None)),
        "accession_number": _normalize_text(getattr(filing, "accession_number", None)),
        "filing_date": _normalize_text(getattr(filing, "filing_date", None)),
        "accepted_datetime": _normalize_text(
            getattr(filing, "accepted_datetime", None)
        ),
        "period_of_report": period_of_report,
        "requested_fiscal_year": requested_fiscal_year,
        "matched_fiscal_year": matched_fiscal_year,
        "selection_mode": selection_mode,
    }
