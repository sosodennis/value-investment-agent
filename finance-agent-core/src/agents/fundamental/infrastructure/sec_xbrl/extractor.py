from __future__ import annotations

import logging
import os

import pandas as pd
from edgar import Company
from edgar.xbrl.xbrl import XBRL
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
_LINKBASE_ROLE_BY_DOCUMENT_TYPE = {
    "EX-101.SCH": "schema",
    "EX-101.LAB": "label",
    "EX-101.PRE": "presentation",
    "EX-101.CAL": "calculation",
    "EX-101.DEF": "definition",
}

__all__ = [
    "SearchConfig",
    "SearchType",
    "SECExtractResult",
    "SECReportExtractor",
]


class SECReportExtractor:
    def __init__(self, ticker: str, fiscal_year: int):
        self.ticker = ticker
        self.fiscal_year = fiscal_year
        self.standard_industrial_classification_code: int | None = None
        self.df: pd.DataFrame | None = None
        self.actual_date: str | None = None
        self.real_dim_cols: list[str] = []
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
        filings = call_with_sec_retry(
            operation=f"get_filings_10-K_{self.fiscal_year}",
            ticker=self.ticker,
            execute=lambda: company.get_filings(
                form="10-K",
                year=[self.fiscal_year, self.fiscal_year + 1],
                amendments=False,
            ),
        )

        target_filing = next(
            (
                filing
                for filing in filings
                if pd.to_datetime(filing.period_of_report).year == self.fiscal_year
            ),
            None,
        )
        if not target_filing:
            target_filing = filings.latest()
        if not target_filing:
            raise ValueError(f"找不到 {self.ticker} 報告。")

        xb = call_with_sec_retry(
            operation=f"filing_xbrl_{self.fiscal_year}",
            ticker=self.ticker,
            execute=target_filing.xbrl,
        )
        if not xb:
            raise ValueError(f"No XBRL data found for {self.ticker}")

        self.df = _resolve_xbrl_facts_dataframe(
            primary_df=xb.facts.to_dataframe(),
            filing=target_filing,
            ticker=self.ticker,
            fiscal_year=self.fiscal_year,
        )
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
    fiscal_year: int,
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
    fiscal_year: int,
) -> pd.DataFrame:
    missing_columns = [
        column for column in _REQUIRED_XBRL_COLUMNS if column not in primary_df.columns
    ]
    if not missing_columns and len(primary_df) > 0:
        return primary_df

    log_event(
        logger,
        event="fundamental_xbrl_instance_fallback_started",
        message="xbrl facts dataframe invalid; attempting forced instance fallback",
        level=logging.WARNING,
        error_code="FUNDAMENTAL_XBRL_INSTANCE_FALLBACK",
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
        return primary_df

    fallback_df, instance_document = fallback_result
    log_event(
        logger,
        event="fundamental_xbrl_instance_fallback_succeeded",
        message="forced instance fallback produced usable facts dataframe",
        level=logging.INFO,
        fields={
            "ticker": ticker,
            "fiscal_year": fiscal_year,
            "instance_document": instance_document,
            "row_count": len(fallback_df),
            "column_count": len(fallback_df.columns),
        },
    )
    return fallback_df


def _build_dataframe_from_filing_attachments(
    *,
    filing: object,
    ticker: str,
    fiscal_year: int,
) -> tuple[pd.DataFrame, str] | None:
    data_files = _get_filing_data_files(filing)
    if not data_files:
        log_event(
            logger,
            event="fundamental_xbrl_instance_fallback_no_data_files",
            message="forced instance fallback skipped; filing has no data files",
            level=logging.WARNING,
            error_code="FUNDAMENTAL_XBRL_INSTANCE_FALLBACK_NO_DATA_FILES",
            fields={"ticker": ticker, "fiscal_year": fiscal_year},
        )
        return None

    instance_candidates = _select_instance_candidates(data_files)
    if not instance_candidates:
        log_event(
            logger,
            event="fundamental_xbrl_instance_fallback_no_candidates",
            message="forced instance fallback skipped; no instance candidates found",
            level=logging.WARNING,
            error_code="FUNDAMENTAL_XBRL_INSTANCE_FALLBACK_NO_CANDIDATES",
            fields={"ticker": ticker, "fiscal_year": fiscal_year},
        )
        return None

    linkbase_contents = _collect_linkbase_contents(data_files)
    for candidate in instance_candidates:
        content = _attachment_content_text(candidate)
        if not content:
            continue

        candidate_document = str(getattr(candidate, "document", "unknown"))
        candidate_type = str(getattr(candidate, "document_type", ""))
        try:
            xbrl = XBRL()
            _apply_linkbase_contents(xbrl=xbrl, linkbase_contents=linkbase_contents)
            xbrl.parser.parse_instance_content(content)
            dataframe = xbrl.facts.to_dataframe()
        except Exception as exc:
            log_event(
                logger,
                event="fundamental_xbrl_instance_candidate_failed",
                message="forced instance candidate parse failed",
                level=logging.WARNING,
                error_code="FUNDAMENTAL_XBRL_INSTANCE_CANDIDATE_FAILED",
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

        missing_columns = [
            column
            for column in _REQUIRED_XBRL_COLUMNS
            if column not in dataframe.columns
        ]
        if missing_columns or len(dataframe) == 0:
            log_event(
                logger,
                event="fundamental_xbrl_instance_candidate_invalid",
                message="forced instance candidate produced invalid facts dataframe",
                level=logging.WARNING,
                error_code="FUNDAMENTAL_XBRL_INSTANCE_CANDIDATE_INVALID",
                fields={
                    "ticker": ticker,
                    "fiscal_year": fiscal_year,
                    "instance_document": candidate_document,
                    "instance_document_type": candidate_type,
                    "row_count": len(dataframe),
                    "column_count": len(dataframe.columns),
                    "missing_columns": missing_columns,
                },
            )
            continue

        return dataframe, candidate_document

    return None


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


def _collect_linkbase_contents(data_files: list[object]) -> dict[str, str]:
    linkbase_contents: dict[str, str] = {}
    for attachment in data_files:
        doc_type = str(getattr(attachment, "document_type", "")).upper()
        role = _LINKBASE_ROLE_BY_DOCUMENT_TYPE.get(doc_type)
        if role is None:
            continue
        content = _attachment_content_text(attachment)
        if content:
            linkbase_contents[role] = content
    return linkbase_contents


def _apply_linkbase_contents(*, xbrl: XBRL, linkbase_contents: dict[str, str]) -> None:
    schema = linkbase_contents.get("schema")
    if schema:
        xbrl.parser.parse_schema_content(schema)
    label = linkbase_contents.get("label")
    if label:
        xbrl.parser.parse_labels_content(label)
    presentation = linkbase_contents.get("presentation")
    if presentation:
        xbrl.parser.parse_presentation_content(presentation)
    calculation = linkbase_contents.get("calculation")
    if calculation:
        xbrl.parser.parse_calculation_content(calculation)
    definition = linkbase_contents.get("definition")
    if definition:
        xbrl.parser.parse_definition_content(definition)


def _attachment_content_text(attachment: object) -> str | None:
    content = getattr(attachment, "content", None)
    if isinstance(content, bytes):
        return content.decode("utf-8", errors="replace")
    if isinstance(content, str):
        return content
    return None
