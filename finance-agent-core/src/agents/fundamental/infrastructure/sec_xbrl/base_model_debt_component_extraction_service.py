from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

from src.shared.kernel.tools.logger import log_event
from src.shared.kernel.traceable import TraceableField

from .base_model_debt_config_service import DebtConfigBundle
from .extractor import SearchConfig, SECReportExtractor

ExtractFieldFn = Callable[
    [SECReportExtractor, list[SearchConfig], str, type[float]],
    TraceableField[float],
]
BuildRealEstateDebtCombinedFn = Callable[
    [
        TraceableField[float],
        TraceableField[float],
        TraceableField[float],
        TraceableField[float],
        TraceableField[float],
        TraceableField[float],
    ],
    TraceableField[float],
]
FieldSourceLabelFn = Callable[[TraceableField[float]], str]


@dataclass(frozen=True)
class DebtComponentFields:
    debt_combined_ex_leases: TraceableField[float]
    debt_combined_with_leases: TraceableField[float]
    debt_short: TraceableField[float]
    debt_long: TraceableField[float]
    finance_lease_combined: TraceableField[float]
    finance_lease_current: TraceableField[float]
    finance_lease_noncurrent: TraceableField[float]


def extract_debt_component_fields(
    *,
    extractor: SECReportExtractor,
    industry_type: str | None,
    config_bundle: DebtConfigBundle,
    extract_field_fn: ExtractFieldFn,
    build_real_estate_debt_combined_ex_leases_fn: BuildRealEstateDebtCombinedFn,
    field_source_label_fn: FieldSourceLabelFn,
    logger_: logging.Logger,
    relaxed: bool = False,
) -> DebtComponentFields:
    suffix = " (Relaxed)" if relaxed else ""

    tf_debt_combined = extract_field_fn(
        extractor,
        config_bundle.debt_combined,
        f"Total Debt (Combined, Excluding Finance Leases{', Relaxed' if relaxed else ''})",
        target_type=float,
    )
    tf_debt_combined_with_leases = extract_field_fn(
        extractor,
        config_bundle.debt_combined_with_leases,
        f"Total Debt (Combined, Including Finance Leases{', Relaxed' if relaxed else ''})",
        target_type=float,
    )
    tf_debt_short = extract_field_fn(
        extractor,
        config_bundle.debt_short,
        f"Short-Term Debt{suffix}",
        target_type=float,
    )
    tf_debt_long = extract_field_fn(
        extractor,
        config_bundle.debt_long,
        f"Long-Term Debt{suffix}",
        target_type=float,
    )

    if industry_type == "Real Estate":
        tf_notes_payable = extract_field_fn(
            extractor,
            config_bundle.notes_payable,
            f"Notes Payable{suffix}",
            target_type=float,
        )
        tf_notes_payable_current = extract_field_fn(
            extractor,
            config_bundle.notes_payable_current,
            f"Notes Payable (Current{', Relaxed' if relaxed else ''})",
            target_type=float,
        )
        tf_notes_payable_noncurrent = extract_field_fn(
            extractor,
            config_bundle.notes_payable_noncurrent,
            f"Notes Payable (Noncurrent{', Relaxed' if relaxed else ''})",
            target_type=float,
        )
        tf_loans_payable = extract_field_fn(
            extractor,
            config_bundle.loans_payable,
            f"Loans Payable{suffix}",
            target_type=float,
        )
        tf_loans_payable_current = extract_field_fn(
            extractor,
            config_bundle.loans_payable_current,
            f"Loans Payable (Current{', Relaxed' if relaxed else ''})",
            target_type=float,
        )
        tf_commercial_paper = extract_field_fn(
            extractor,
            config_bundle.commercial_paper,
            f"Commercial Paper{suffix}",
            target_type=float,
        )

        tf_debt_combined_reit = build_real_estate_debt_combined_ex_leases_fn(
            notes_payable=tf_notes_payable,
            notes_payable_current=tf_notes_payable_current,
            notes_payable_noncurrent=tf_notes_payable_noncurrent,
            loans_payable=tf_loans_payable,
            loans_payable_current=tf_loans_payable_current,
            commercial_paper=tf_commercial_paper,
        )
        if tf_debt_combined_reit.value is not None:
            tf_debt_combined = tf_debt_combined_reit
            _log_real_estate_components(
                logger_=logger_,
                event=(
                    "fundamental_real_estate_debt_components_relaxed_applied"
                    if relaxed
                    else "fundamental_real_estate_debt_components_applied"
                ),
                message=(
                    "applied relaxed real-estate debt component aggregation"
                    if relaxed
                    else "applied real-estate debt component aggregation"
                ),
                ticker=extractor.ticker,
                total_debt_combined_ex_leases=tf_debt_combined,
                notes_payable=tf_notes_payable,
                notes_payable_current=tf_notes_payable_current,
                notes_payable_noncurrent=tf_notes_payable_noncurrent,
                loans_payable=tf_loans_payable,
                loans_payable_current=tf_loans_payable_current,
                commercial_paper=tf_commercial_paper,
                field_source_label_fn=field_source_label_fn,
            )

    tf_finance_lease_combined = extract_field_fn(
        extractor,
        config_bundle.finance_lease_combined,
        f"Finance Lease Liabilities (Combined{', Relaxed' if relaxed else ''})",
        target_type=float,
    )
    tf_finance_lease_current = extract_field_fn(
        extractor,
        config_bundle.finance_lease_current,
        f"Finance Lease Liabilities (Current{', Relaxed' if relaxed else ''})",
        target_type=float,
    )
    tf_finance_lease_noncurrent = extract_field_fn(
        extractor,
        config_bundle.finance_lease_noncurrent,
        f"Finance Lease Liabilities (Noncurrent{', Relaxed' if relaxed else ''})",
        target_type=float,
    )

    return DebtComponentFields(
        debt_combined_ex_leases=tf_debt_combined,
        debt_combined_with_leases=tf_debt_combined_with_leases,
        debt_short=tf_debt_short,
        debt_long=tf_debt_long,
        finance_lease_combined=tf_finance_lease_combined,
        finance_lease_current=tf_finance_lease_current,
        finance_lease_noncurrent=tf_finance_lease_noncurrent,
    )


def _log_real_estate_components(
    *,
    logger_: logging.Logger,
    event: str,
    message: str,
    ticker: str,
    total_debt_combined_ex_leases: TraceableField[float],
    notes_payable: TraceableField[float],
    notes_payable_current: TraceableField[float],
    notes_payable_noncurrent: TraceableField[float],
    loans_payable: TraceableField[float],
    loans_payable_current: TraceableField[float],
    commercial_paper: TraceableField[float],
    field_source_label_fn: FieldSourceLabelFn,
) -> None:
    log_event(
        logger_,
        event=event,
        message=message,
        fields={
            "ticker": ticker,
            "total_debt_combined_ex_leases": total_debt_combined_ex_leases.value,
            "notes_payable": notes_payable.value,
            "notes_payable_source": field_source_label_fn(notes_payable),
            "notes_payable_current": notes_payable_current.value,
            "notes_payable_current_source": field_source_label_fn(
                notes_payable_current
            ),
            "notes_payable_noncurrent": notes_payable_noncurrent.value,
            "notes_payable_noncurrent_source": field_source_label_fn(
                notes_payable_noncurrent
            ),
            "loans_payable": loans_payable.value,
            "loans_payable_source": field_source_label_fn(loans_payable),
            "loans_payable_current": loans_payable_current.value,
            "loans_payable_current_source": field_source_label_fn(
                loans_payable_current
            ),
            "commercial_paper": commercial_paper.value,
            "commercial_paper_source": field_source_label_fn(commercial_paper),
        },
    )
