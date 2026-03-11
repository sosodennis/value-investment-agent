from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

from src.agents.fundamental.shared.contracts.traceable import TraceableField

from .extractor import SearchConfig, SearchType, SECReportExtractor
from .report_contracts import FinancialServicesExtension

T = TypeVar("T")


def build_financial_services_extension(
    *,
    extractor: SECReportExtractor,
    resolve_configs_fn: Callable[..., list[SearchConfig]],
    extract_field_fn: Callable[
        [SECReportExtractor, list[SearchConfig], str, type[T]], TraceableField[T]
    ],
    bs_statement_tokens: list[str],
    is_statement_tokens: list[str],
    usd_units: list[str],
    ratio_units: list[str],
) -> FinancialServicesExtension:
    def C(
        regex: str,
        statement_types: list[str] | None = None,
        period_type: str | None = None,
        unit_whitelist: list[str] | None = None,
    ) -> SearchConfig:
        return SearchType.CONSOLIDATED(
            regex,
            statement_types=statement_types,
            period_type=period_type,
            unit_whitelist=unit_whitelist,
        )

    def R(field_key: str) -> list[SearchConfig]:
        return resolve_configs_fn(
            field_key=field_key,
            industry="Financial Services",
            issuer=extractor.ticker,
        )

    tf_loans = extract_field_fn(
        extractor,
        R("loans_and_leases")
        or [
            C(
                "us-gaap:LoansAndLeasesReceivableNetReportedAmount",
                bs_statement_tokens,
                "instant",
                usd_units,
            )
        ],
        "Loans and Leases",
        float,
    )

    tf_deposits = extract_field_fn(
        extractor,
        R("deposits")
        or [C("us-gaap:Deposits", bs_statement_tokens, "instant", usd_units)],
        "Deposits",
        float,
    )

    tf_allowance = extract_field_fn(
        extractor,
        R("allowance_for_credit_losses")
        or [
            C(
                "us-gaap:FinancingReceivableAllowanceForCreditLosses",
                bs_statement_tokens,
                "instant",
                usd_units,
            ),
            C(
                "us-gaap:AllowanceForLoanAndLeaseLosses",
                bs_statement_tokens,
                "instant",
                usd_units,
            ),
        ],
        "Allowance for Credit Losses",
        float,
    )

    tf_int_income = extract_field_fn(
        extractor,
        R("interest_income")
        or [C("us-gaap:InterestIncome", is_statement_tokens, "duration", usd_units)],
        "Interest Income",
        float,
    )

    tf_int_expense = extract_field_fn(
        extractor,
        R("interest_expense_financial")
        or [C("us-gaap:InterestExpense", is_statement_tokens, "duration", usd_units)],
        "Interest Expense",
        float,
    )

    tf_provision = extract_field_fn(
        extractor,
        R("provision_for_loan_losses")
        or [
            C(
                "us-gaap:ProvisionForCreditLosses",
                is_statement_tokens,
                "duration",
                usd_units,
            ),
            C(
                "us-gaap:ProvisionForLoanLeaseAndOtherLosses",
                is_statement_tokens,
                "duration",
                usd_units,
            ),
        ],
        "Provision for Loan Losses",
        float,
    )

    tf_rwa = extract_field_fn(
        extractor,
        R("risk_weighted_assets")
        or [C("us-gaap:RiskWeightedAssets", None, "instant", usd_units)],
        "Risk-Weighted Assets",
        float,
    )

    tf_tier1 = extract_field_fn(
        extractor,
        R("tier1_capital_ratio")
        or [
            C("us-gaap:Tier1CapitalRatio", None, "instant", ratio_units),
            C("us-gaap:Tier1RiskBasedCapitalRatio", None, "instant", ratio_units),
            C(
                "us-gaap:TierOneRiskBasedCapitalToRiskWeightedAssets",
                None,
                "instant",
                ratio_units,
            ),
        ],
        "Tier 1 Capital Ratio",
        float,
    )

    return FinancialServicesExtension(
        loans_and_leases=tf_loans,
        deposits=tf_deposits,
        allowance_for_credit_losses=tf_allowance,
        interest_income=tf_int_income,
        interest_expense=tf_int_expense,
        provision_for_loan_losses=tf_provision,
        risk_weighted_assets=tf_rwa,
        tier1_capital_ratio=tf_tier1,
    )
