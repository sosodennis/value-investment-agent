from __future__ import annotations

from src.agents.fundamental.data.clients.sec_xbrl.extractor import SECReportExtractor
from src.agents.fundamental.data.clients.sec_xbrl.mapping import (
    REGISTRY,
    FieldSpec,
    XbrlMappingRegistry,
)


def test_normalize_unit_handles_u_prefix() -> None:
    assert SECReportExtractor._normalize_unit("U_USD") == "usd"
    assert SECReportExtractor._normalize_unit("iso4217:USD") == "usd"


def test_period_sort_key_prefers_latest_end_date() -> None:
    latest = SECReportExtractor._period_sort_key("duration_2024-01-01_2024-12-31")
    older = SECReportExtractor._period_sort_key("instant_2023-12-31")
    assert latest > older


def test_interest_expense_mapping_includes_operating_nonoperating_tags() -> None:
    spec = REGISTRY.get("interest_expense")
    assert spec is not None
    concepts = [cfg.concept_regex for cfg in spec.configs]
    assert "us-gaap:InterestExpenseOperating" in concepts
    assert "us-gaap:InterestExpenseNonoperating" in concepts


def test_capex_mapping_includes_productive_assets_tag() -> None:
    spec = REGISTRY.get("capex")
    assert spec is not None
    concepts = [cfg.concept_regex for cfg in spec.configs]
    assert "us-gaap:PaymentsToAcquireProductiveAssets" in concepts


def test_shares_outstanding_mapping_relaxes_anchor_date() -> None:
    spec = REGISTRY.get("shares_outstanding")
    assert spec is not None
    assert all(cfg.respect_anchor_date is False for cfg in spec.configs)


def test_debt_long_mapping_includes_notes_payable() -> None:
    spec = REGISTRY.get("debt_long")
    assert spec is not None
    concepts = [cfg.concept_regex for cfg in spec.configs]
    assert "us-gaap:NotesPayable" in concepts


def test_debt_short_mapping_includes_loans_payable() -> None:
    spec = REGISTRY.get("debt_short")
    assert spec is not None
    concepts = [cfg.concept_regex for cfg in spec.configs]
    assert "us-gaap:LoansPayable" in concepts


def test_real_estate_dep_amort_mapping_includes_dep_depletion() -> None:
    spec = REGISTRY.get("real_estate_dep_amort")
    assert spec is not None
    concepts = [cfg.concept_regex for cfg in spec.configs]
    assert "us-gaap:DepreciationDepletionAndAmortization" in concepts


def test_total_revenue_mapping_includes_bank_net_revenue_tags() -> None:
    spec = REGISTRY.get("total_revenue")
    assert spec is not None
    concepts = [cfg.concept_regex for cfg in spec.configs]
    assert "us-gaap:RevenuesNetOfInterestExpense" in concepts


def test_total_debt_including_leases_mapping_includes_current_maturities_tag() -> None:
    spec = REGISTRY.get("total_debt_including_finance_leases_combined")
    assert spec is not None
    concepts = [cfg.concept_regex for cfg in spec.configs]
    assert (
        "us-gaap:LongTermDebtAndCapitalLeaseObligationsIncludingCurrentMaturities"
        in concepts
    )


def test_tier1_capital_ratio_mapping_accepts_number_unit() -> None:
    spec = REGISTRY.get("tier1_capital_ratio")
    assert spec is not None
    concepts = [cfg.concept_regex for cfg in spec.configs]
    assert "us-gaap:TierOneRiskBasedCapitalToRiskWeightedAssets" in concepts
    assert any(
        cfg.unit_whitelist is not None and "number" in cfg.unit_whitelist
        for cfg in spec.configs
    )


def test_financial_extension_mapping_includes_credit_loss_and_interest_operating() -> (
    None
):
    allowance_spec = REGISTRY.get("allowance_for_credit_losses")
    assert allowance_spec is not None
    allowance_concepts = [cfg.concept_regex for cfg in allowance_spec.configs]
    assert (
        "us-gaap:FinancingReceivableAllowanceForCreditLossExcludingAccruedInterest"
        in allowance_concepts
    )

    income_spec = REGISTRY.get("interest_income")
    assert income_spec is not None
    income_concepts = [cfg.concept_regex for cfg in income_spec.configs]
    assert "us-gaap:InterestIncomeOperating" in income_concepts


def test_registry_resolve_prefers_issuer_over_industry_then_base() -> None:
    registry = XbrlMappingRegistry()
    base_spec = FieldSpec(name="f", configs=[])
    industry_spec = FieldSpec(name="f_industry", configs=[])
    issuer_spec = FieldSpec(name="f_issuer", configs=[])

    registry.register("field_x", base_spec)
    registry.register_industry_override("Industrial", "field_x", industry_spec)
    registry.register_issuer_override("AAPL", "field_x", issuer_spec)

    resolved = registry.resolve("field_x", industry="Industrial", issuer="AAPL")
    assert resolved is not None
    assert resolved.source == "issuer_override"
    assert resolved.spec is issuer_spec

    resolved_industry = registry.resolve(
        "field_x", industry="Industrial", issuer="MSFT"
    )
    assert resolved_industry is not None
    assert resolved_industry.source == "industry_override"
    assert resolved_industry.spec is industry_spec

    resolved_base = registry.resolve("field_x", industry="General", issuer="MSFT")
    assert resolved_base is not None
    assert resolved_base.source == "base"
    assert resolved_base.spec is base_spec


def test_registry_resolve_normalizes_issuer_key() -> None:
    registry = XbrlMappingRegistry()
    issuer_spec = FieldSpec(name="issuer", configs=[])
    registry.register("field_y", FieldSpec(name="base", configs=[]))
    registry.register_issuer_override("jPm", "field_y", issuer_spec)

    resolved = registry.resolve("field_y", industry="Financial Services", issuer="JPM")
    assert resolved is not None
    assert resolved.source == "issuer_override"
    assert resolved.issuer == "JPM"
    assert resolved.spec is issuer_spec
