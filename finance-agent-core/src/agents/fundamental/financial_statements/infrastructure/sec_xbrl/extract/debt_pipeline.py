from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

from src.agents.fundamental.shared.contracts.traceable import TraceableField
from src.shared.kernel.tools.logger import log_event

from .extractor import SearchConfig, SECReportExtractor

BuildConfigFn = Callable[
    [str, list[str] | None, str | None, list[str] | None], SearchConfig
]
ResolveConfigsFn = Callable[[str], list[SearchConfig]]
RelaxStatementFiltersFn = Callable[[list[SearchConfig]], list[SearchConfig]]
ExtractFieldFn = Callable[
    [SECReportExtractor, list[SearchConfig], str, type[float]],
    TraceableField[float],
]
ResolveTotalDebtPolicyFn = Callable[[], str]
BuildTotalDebtWithPolicyFn = Callable[
    [
        TraceableField[float],
        TraceableField[float],
        TraceableField[float],
        TraceableField[float],
        TraceableField[float],
        TraceableField[float],
        TraceableField[float],
        str,
    ],
    tuple[TraceableField[float], dict[str, TraceableField[float]], str],
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
LogTotalDebtDiagnosticsFn = Callable[
    [str, str, TraceableField[float], dict[str, TraceableField[float]]],
    None,
]


@dataclass(frozen=True)
class DebtConfigBundle:
    debt_combined: list[SearchConfig]
    debt_combined_with_leases: list[SearchConfig]
    debt_short: list[SearchConfig]
    debt_long: list[SearchConfig]
    notes_payable: list[SearchConfig]
    notes_payable_current: list[SearchConfig]
    notes_payable_noncurrent: list[SearchConfig]
    loans_payable: list[SearchConfig]
    loans_payable_current: list[SearchConfig]
    commercial_paper: list[SearchConfig]
    finance_lease_combined: list[SearchConfig]
    finance_lease_current: list[SearchConfig]
    finance_lease_noncurrent: list[SearchConfig]


def build_debt_config_bundle(
    *,
    resolve_configs: ResolveConfigsFn,
    build_config: BuildConfigFn,
    bs_statement_tokens: list[str],
    usd_units: list[str],
) -> DebtConfigBundle:
    debt_combined = resolve_configs("total_debt_combined") or [
        build_config(
            "us-gaap:DebtLongTermAndShortTermCombinedAmount",
            bs_statement_tokens,
            "instant",
            usd_units,
        ),
        build_config("us-gaap:Debt", bs_statement_tokens, "instant", usd_units),
        build_config(
            "us-gaap:LongTermDebtAndNotesPayable",
            bs_statement_tokens,
            "instant",
            usd_units,
        ),
    ]

    debt_combined_with_leases = resolve_configs(
        "total_debt_including_finance_leases_combined"
    ) or [
        build_config(
            "us-gaap:LongTermDebtAndCapitalLeaseObligations",
            bs_statement_tokens,
            "instant",
            usd_units,
        ),
        build_config(
            "us-gaap:LongTermDebtAndCapitalLeaseObligationsIncludingCurrentMaturities",
            bs_statement_tokens,
            "instant",
            usd_units,
        ),
        build_config(
            "us-gaap:LongTermDebtAndFinanceLeaseLiabilities",
            bs_statement_tokens,
            "instant",
            usd_units,
        ),
        build_config(
            "us-gaap:DebtAndFinanceLeaseLiabilities",
            bs_statement_tokens,
            "instant",
            usd_units,
        ),
    ]

    debt_short = resolve_configs("debt_short") or [
        build_config(
            "us-gaap:ShortTermBorrowings",
            bs_statement_tokens,
            "instant",
            usd_units,
        ),
        build_config("us-gaap:DebtCurrent", bs_statement_tokens, "instant", usd_units),
        build_config(
            "us-gaap:LongTermDebtCurrent",
            bs_statement_tokens,
            "instant",
            usd_units,
        ),
        build_config(
            "us-gaap:NotesPayableCurrent",
            bs_statement_tokens,
            "instant",
            usd_units,
        ),
        build_config(
            "us-gaap:CommercialPaper",
            bs_statement_tokens,
            "instant",
            usd_units,
        ),
        build_config(
            "us-gaap:ShortTermBankLoansAndNotesPayable",
            bs_statement_tokens,
            "instant",
            usd_units,
        ),
    ]

    debt_long = resolve_configs("debt_long") or [
        build_config(
            "us-gaap:LongTermDebtNoncurrent",
            bs_statement_tokens,
            "instant",
            usd_units,
        ),
        build_config("us-gaap:LongTermDebt", bs_statement_tokens, "instant", usd_units),
        build_config(
            "us-gaap:LongTermDebtAndNotesPayable",
            bs_statement_tokens,
            "instant",
            usd_units,
        ),
        build_config(
            "us-gaap:NotesPayableNoncurrent",
            bs_statement_tokens,
            "instant",
            usd_units,
        ),
        build_config("us-gaap:NotesPayable", bs_statement_tokens, "instant", usd_units),
    ]

    notes_payable = resolve_configs("notes_payable") or [
        build_config("us-gaap:NotesPayable", bs_statement_tokens, "instant", usd_units)
    ]
    notes_payable_current = resolve_configs("notes_payable_current") or [
        build_config(
            "us-gaap:NotesPayableCurrent", bs_statement_tokens, "instant", usd_units
        )
    ]
    notes_payable_noncurrent = resolve_configs("notes_payable_noncurrent") or [
        build_config(
            "us-gaap:NotesPayableNoncurrent",
            bs_statement_tokens,
            "instant",
            usd_units,
        )
    ]
    loans_payable = resolve_configs("loans_payable") or [
        build_config("us-gaap:LoansPayable", bs_statement_tokens, "instant", usd_units)
    ]
    loans_payable_current = resolve_configs("loans_payable_current") or [
        build_config(
            "us-gaap:LoansPayableCurrent", bs_statement_tokens, "instant", usd_units
        )
    ]
    commercial_paper = resolve_configs("commercial_paper") or [
        build_config(
            "us-gaap:CommercialPaper", bs_statement_tokens, "instant", usd_units
        )
    ]

    finance_lease_combined = resolve_configs("finance_lease_liabilities_combined") or [
        build_config(
            "us-gaap:FinanceLeaseLiability", bs_statement_tokens, "instant", usd_units
        ),
        build_config(
            "us-gaap:CapitalLeaseObligations",
            bs_statement_tokens,
            "instant",
            usd_units,
        ),
    ]
    finance_lease_current = resolve_configs("finance_lease_liabilities_current") or [
        build_config(
            "us-gaap:FinanceLeaseLiabilityCurrent",
            bs_statement_tokens,
            "instant",
            usd_units,
        ),
        build_config(
            "us-gaap:CapitalLeaseObligationsCurrent",
            bs_statement_tokens,
            "instant",
            usd_units,
        ),
    ]
    finance_lease_noncurrent = resolve_configs(
        "finance_lease_liabilities_noncurrent"
    ) or [
        build_config(
            "us-gaap:FinanceLeaseLiabilityNoncurrent",
            bs_statement_tokens,
            "instant",
            usd_units,
        ),
        build_config(
            "us-gaap:CapitalLeaseObligationsNoncurrent",
            bs_statement_tokens,
            "instant",
            usd_units,
        ),
    ]

    return DebtConfigBundle(
        debt_combined=debt_combined,
        debt_combined_with_leases=debt_combined_with_leases,
        debt_short=debt_short,
        debt_long=debt_long,
        notes_payable=notes_payable,
        notes_payable_current=notes_payable_current,
        notes_payable_noncurrent=notes_payable_noncurrent,
        loans_payable=loans_payable,
        loans_payable_current=loans_payable_current,
        commercial_paper=commercial_paper,
        finance_lease_combined=finance_lease_combined,
        finance_lease_current=finance_lease_current,
        finance_lease_noncurrent=finance_lease_noncurrent,
    )


def relax_debt_config_bundle(
    bundle: DebtConfigBundle,
    relax_statement_filters_fn: RelaxStatementFiltersFn,
) -> DebtConfigBundle:
    return DebtConfigBundle(
        debt_combined=relax_statement_filters_fn(bundle.debt_combined),
        debt_combined_with_leases=relax_statement_filters_fn(
            bundle.debt_combined_with_leases
        ),
        debt_short=relax_statement_filters_fn(bundle.debt_short),
        debt_long=relax_statement_filters_fn(bundle.debt_long),
        notes_payable=relax_statement_filters_fn(bundle.notes_payable),
        notes_payable_current=relax_statement_filters_fn(bundle.notes_payable_current),
        notes_payable_noncurrent=relax_statement_filters_fn(
            bundle.notes_payable_noncurrent
        ),
        loans_payable=relax_statement_filters_fn(bundle.loans_payable),
        loans_payable_current=relax_statement_filters_fn(bundle.loans_payable_current),
        commercial_paper=relax_statement_filters_fn(bundle.commercial_paper),
        finance_lease_combined=relax_statement_filters_fn(
            bundle.finance_lease_combined
        ),
        finance_lease_current=relax_statement_filters_fn(bundle.finance_lease_current),
        finance_lease_noncurrent=relax_statement_filters_fn(
            bundle.finance_lease_noncurrent
        ),
    )


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
            "total_debt_combined_ex_leases": field_source_label_fn(
                total_debt_combined_ex_leases
            ),
            "notes_payable": field_source_label_fn(notes_payable),
            "notes_payable_current": field_source_label_fn(notes_payable_current),
            "notes_payable_noncurrent": field_source_label_fn(notes_payable_noncurrent),
            "loans_payable": field_source_label_fn(loans_payable),
            "loans_payable_current": field_source_label_fn(loans_payable_current),
            "commercial_paper": field_source_label_fn(commercial_paper),
        },
    )


@dataclass(frozen=True)
class DebtBuilderOps:
    extract_field_fn: ExtractFieldFn
    resolve_total_debt_policy_fn: ResolveTotalDebtPolicyFn
    relax_statement_filters_fn: RelaxStatementFiltersFn
    build_total_debt_with_policy_fn: BuildTotalDebtWithPolicyFn
    build_real_estate_debt_combined_ex_leases_fn: BuildRealEstateDebtCombinedFn
    field_source_label_fn: FieldSourceLabelFn
    log_total_debt_diagnostics_fn: LogTotalDebtDiagnosticsFn


def build_total_debt_field(
    *,
    extractor: SECReportExtractor,
    industry_type: str | None,
    resolve_configs: ResolveConfigsFn,
    build_config: BuildConfigFn,
    ops: DebtBuilderOps,
    logger_: logging.Logger,
    bs_statement_tokens: list[str],
    usd_units: list[str],
) -> TraceableField[float]:
    config_bundle = build_debt_config_bundle(
        resolve_configs=resolve_configs,
        build_config=build_config,
        bs_statement_tokens=bs_statement_tokens,
        usd_units=usd_units,
    )

    strict_components = extract_debt_component_fields(
        extractor=extractor,
        industry_type=industry_type,
        config_bundle=config_bundle,
        extract_field_fn=ops.extract_field_fn,
        build_real_estate_debt_combined_ex_leases_fn=ops.build_real_estate_debt_combined_ex_leases_fn,
        field_source_label_fn=ops.field_source_label_fn,
        logger_=logger_,
        relaxed=False,
    )

    debt_policy = ops.resolve_total_debt_policy_fn()
    tf_total_debt, total_debt_components, total_debt_resolution_source = (
        _resolve_total_debt_with_policy(
            ops=ops,
            components=strict_components,
            policy=debt_policy,
        )
    )

    if tf_total_debt.value is None:
        log_event(
            logger_,
            event="fundamental_total_debt_relaxed_search_started",
            message="retrying total debt extraction without statement_type filter",
            level=logging.WARNING,
            fields={"policy": debt_policy},
        )

        relaxed_components = extract_debt_component_fields(
            extractor=extractor,
            industry_type=industry_type,
            config_bundle=relax_debt_config_bundle(
                config_bundle,
                ops.relax_statement_filters_fn,
            ),
            extract_field_fn=ops.extract_field_fn,
            build_real_estate_debt_combined_ex_leases_fn=ops.build_real_estate_debt_combined_ex_leases_fn,
            field_source_label_fn=ops.field_source_label_fn,
            logger_=logger_,
            relaxed=True,
        )

        tf_total_debt_relaxed, total_debt_components_relaxed, relaxed_source = (
            _resolve_total_debt_with_policy(
                ops=ops,
                components=relaxed_components,
                policy=debt_policy,
            )
        )

        log_event(
            logger_,
            event="fundamental_total_debt_relaxed_search_completed",
            message="completed relaxed total debt extraction retry",
            level=logging.WARNING,
            fields={
                "resolved": tf_total_debt_relaxed.value is not None,
                "resolution_source": relaxed_source,
                "total_debt": tf_total_debt_relaxed.value,
            },
        )

        if tf_total_debt_relaxed.value is not None:
            tf_total_debt = tf_total_debt_relaxed
            total_debt_components = total_debt_components_relaxed
            total_debt_resolution_source = f"{relaxed_source}_relaxed_statement_filter"

    ops.log_total_debt_diagnostics_fn(
        policy=debt_policy,
        resolution_source=total_debt_resolution_source,
        total_debt=tf_total_debt,
        components=total_debt_components,
    )
    return tf_total_debt


def _resolve_total_debt_with_policy(
    *,
    ops: DebtBuilderOps,
    components: DebtComponentFields,
    policy: str,
) -> tuple[TraceableField[float], dict[str, TraceableField[float]], str]:
    return ops.build_total_debt_with_policy_fn(
        debt_combined_ex_leases=components.debt_combined_ex_leases,
        debt_short=components.debt_short,
        debt_long=components.debt_long,
        debt_combined_with_leases=components.debt_combined_with_leases,
        finance_lease_combined=components.finance_lease_combined,
        finance_lease_current=components.finance_lease_current,
        finance_lease_noncurrent=components.finance_lease_noncurrent,
        policy=policy,
    )
