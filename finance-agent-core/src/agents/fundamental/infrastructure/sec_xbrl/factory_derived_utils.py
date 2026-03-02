from __future__ import annotations

from collections.abc import Callable
from typing import Literal

from src.shared.kernel.traceable import (
    ComputedProvenance,
    ManualProvenance,
    TraceableField,
    XBRLProvenance,
)

from .extractor import SearchConfig

TotalDebtPolicy = Literal["include_finance_leases", "exclude_finance_leases"]


def calc_ratio(
    name: str,
    numerator: TraceableField[float],
    denominator: TraceableField[float],
    expression: str,
) -> TraceableField[float]:
    if numerator.value is None or denominator.value in (None, 0):
        return TraceableField(
            name=name,
            value=None,
            provenance=ManualProvenance(
                description=f"Missing or invalid denominator for {expression}"
            ),
        )
    return TraceableField(
        name=name,
        value=float(numerator.value) / float(denominator.value),
        provenance=ComputedProvenance(
            op_code="DIV",
            expression=expression,
            inputs={numerator.name: numerator, denominator.name: denominator},
        ),
    )


def calc_subtract(
    name: str,
    left: TraceableField[float],
    right: TraceableField[float],
    expression: str,
) -> TraceableField[float]:
    if left.value is None or right.value is None:
        return TraceableField(
            name=name,
            value=None,
            provenance=ManualProvenance(description=f"Missing inputs for {expression}"),
        )
    return TraceableField(
        name=name,
        value=float(left.value) - float(right.value),
        provenance=ComputedProvenance(
            op_code="SUB",
            expression=expression,
            inputs={left.name: left, right.name: right},
        ),
    )


def calc_invested_capital(
    total_equity: TraceableField[float],
    total_debt: TraceableField[float],
    cash: TraceableField[float],
) -> TraceableField[float]:
    if total_equity.value is None or total_debt.value is None or cash.value is None:
        return TraceableField(
            name="Invested Capital",
            value=None,
            provenance=ManualProvenance(
                description="Missing equity, debt, or cash for invested capital"
            ),
        )
    value = float(total_equity.value) + float(total_debt.value) - float(cash.value)
    return TraceableField(
        name="Invested Capital",
        value=value,
        provenance=ComputedProvenance(
            op_code="INVESTED_CAPITAL",
            expression="TotalEquity + TotalDebt - Cash",
            inputs={
                "Total Equity": total_equity,
                "Total Debt": total_debt,
                "Cash": cash,
            },
        ),
    )


def calc_nopat(
    operating_income: TraceableField[float],
    effective_tax_rate: TraceableField[float],
) -> TraceableField[float]:
    if operating_income.value is None or effective_tax_rate.value is None:
        return TraceableField(
            name="NOPAT",
            value=None,
            provenance=ManualProvenance(
                description="Missing operating income or tax rate for NOPAT"
            ),
        )
    value = float(operating_income.value) * (1.0 - float(effective_tax_rate.value))
    return TraceableField(
        name="NOPAT",
        value=value,
        provenance=ComputedProvenance(
            op_code="NOPAT",
            expression="OperatingIncome * (1 - EffectiveTaxRate)",
            inputs={
                "Operating Income": operating_income,
                "Effective Tax Rate": effective_tax_rate,
            },
        ),
    )


def relax_statement_filters(configs: list[SearchConfig]) -> list[SearchConfig]:
    relaxed: list[SearchConfig] = []
    for cfg in configs:
        relaxed.append(
            SearchConfig(
                concept_regex=cfg.concept_regex,
                type_name=cfg.type_name,
                dimension_regex=cfg.dimension_regex,
                statement_types=None,
                period_type=cfg.period_type,
                unit_whitelist=cfg.unit_whitelist,
                unit_blacklist=cfg.unit_blacklist,
                respect_anchor_date=cfg.respect_anchor_date,
            )
        )
    return relaxed


def rename_field(
    field: TraceableField[float],
    name: str,
) -> TraceableField[float]:
    return TraceableField(name=name, value=field.value, provenance=field.provenance)


def field_source_label(field: TraceableField[float]) -> str:
    provenance = field.provenance
    if isinstance(provenance, XBRLProvenance):
        return provenance.concept
    if isinstance(provenance, ComputedProvenance):
        return provenance.expression
    if isinstance(provenance, ManualProvenance):
        return provenance.description
    return "unknown"


def build_total_debt_with_policy(
    *,
    debt_combined_ex_leases: TraceableField[float],
    debt_short: TraceableField[float],
    debt_long: TraceableField[float],
    debt_combined_with_leases: TraceableField[float],
    finance_lease_combined: TraceableField[float],
    finance_lease_current: TraceableField[float],
    finance_lease_noncurrent: TraceableField[float],
    policy: TotalDebtPolicy,
    sum_fields_fn: Callable[[str, list[TraceableField[float]]], TraceableField[float]],
) -> tuple[
    TraceableField[float],
    dict[str, TraceableField[float]],
    str,
]:
    debt_ex_leases = (
        rename_field(debt_combined_ex_leases, "Debt (Excluding Finance Leases)")
        if debt_combined_ex_leases.value is not None
        else sum_fields_fn("Debt (Excluding Finance Leases)", [debt_short, debt_long])
    )

    finance_lease_total = (
        rename_field(finance_lease_combined, "Finance Lease Liabilities")
        if finance_lease_combined.value is not None
        else sum_fields_fn(
            "Finance Lease Liabilities",
            [finance_lease_current, finance_lease_noncurrent],
        )
    )

    debt_with_leases = rename_field(
        debt_combined_with_leases, "Debt (Including Finance Leases)"
    )

    if policy == "include_finance_leases":
        if debt_with_leases.value is not None:
            total_debt = rename_field(debt_with_leases, "Total Debt")
            source = "combined_debt_including_finance_leases"
        elif debt_ex_leases.value is not None and finance_lease_total.value is not None:
            total_debt = sum_fields_fn(
                "Total Debt", [debt_ex_leases, finance_lease_total]
            )
            source = "debt_excluding_finance_leases_plus_finance_lease"
        elif debt_ex_leases.value is not None:
            total_debt = rename_field(debt_ex_leases, "Total Debt")
            source = "debt_excluding_finance_leases_only"
        elif finance_lease_total.value is not None:
            total_debt = rename_field(finance_lease_total, "Total Debt")
            source = "finance_lease_only"
        else:
            total_debt = TraceableField(
                name="Total Debt",
                value=None,
                provenance=ManualProvenance(
                    description="Missing debt and finance lease liabilities after policy resolution"
                ),
            )
            source = "missing"
    else:
        if debt_ex_leases.value is not None:
            total_debt = rename_field(debt_ex_leases, "Total Debt")
            source = "debt_excluding_finance_leases"
        else:
            total_debt = TraceableField(
                name="Total Debt",
                value=None,
                provenance=ManualProvenance(
                    description="Missing debt (excluding finance leases) after policy resolution"
                ),
            )
            source = "missing"

    components: dict[str, TraceableField[float]] = {
        "debt_combined_excluding_finance_leases": debt_combined_ex_leases,
        "debt_short": debt_short,
        "debt_long": debt_long,
        "debt_excluding_finance_leases": debt_ex_leases,
        "debt_combined_including_finance_leases": debt_with_leases,
        "finance_lease_combined": finance_lease_combined,
        "finance_lease_current": finance_lease_current,
        "finance_lease_noncurrent": finance_lease_noncurrent,
        "finance_lease_total": finance_lease_total,
    }
    return total_debt, components, source


def build_real_estate_debt_combined_ex_leases(
    *,
    notes_payable: TraceableField[float],
    notes_payable_current: TraceableField[float],
    notes_payable_noncurrent: TraceableField[float],
    loans_payable: TraceableField[float],
    loans_payable_current: TraceableField[float],
    commercial_paper: TraceableField[float],
    sum_fields_fn: Callable[[str, list[TraceableField[float]]], TraceableField[float]],
) -> TraceableField[float]:
    note_parts: list[TraceableField[float]] = []
    if notes_payable_current.value is not None:
        note_parts.append(
            rename_field(notes_payable_current, "Notes Payable (Current)")
        )
    if notes_payable_noncurrent.value is not None:
        note_parts.append(
            rename_field(notes_payable_noncurrent, "Notes Payable (Noncurrent)")
        )

    if note_parts:
        notes_total = (
            note_parts[0]
            if len(note_parts) == 1
            else sum_fields_fn("Notes Payable", note_parts)
        )
    elif notes_payable.value is not None:
        notes_total = rename_field(notes_payable, "Notes Payable")
    else:
        notes_total = TraceableField(
            name="Notes Payable",
            value=None,
            provenance=ManualProvenance(description="Missing notes payable components"),
        )

    if loans_payable_current.value is not None:
        loans_total = rename_field(loans_payable_current, "Loans Payable")
    elif loans_payable.value is not None:
        loans_total = rename_field(loans_payable, "Loans Payable")
    else:
        loans_total = TraceableField(
            name="Loans Payable",
            value=None,
            provenance=ManualProvenance(description="Missing loans payable components"),
        )

    cp_total = rename_field(commercial_paper, "Commercial Paper")
    candidates = [notes_total, loans_total, cp_total]
    unique_components: list[TraceableField[float]] = []
    seen: set[tuple[str | None, str | None, float | None]] = set()
    for field in candidates:
        if field.value is None:
            continue
        provenance = field.provenance
        concept = provenance.concept if isinstance(provenance, XBRLProvenance) else None
        period = provenance.period if isinstance(provenance, XBRLProvenance) else None
        key = (concept, period, field.value)
        if key in seen:
            continue
        seen.add(key)
        unique_components.append(field)

    if not unique_components:
        return TraceableField(
            name="Total Debt (Combined, Excluding Finance Leases)",
            value=None,
            provenance=ManualProvenance(
                description="Missing real-estate debt components (notes/loans/commercial paper)"
            ),
        )

    if len(unique_components) == 1:
        return rename_field(
            unique_components[0], "Total Debt (Combined, Excluding Finance Leases)"
        )

    return sum_fields_fn(
        "Total Debt (Combined, Excluding Finance Leases)", unique_components
    )
