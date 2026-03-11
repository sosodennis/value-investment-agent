from __future__ import annotations

import logging

from src.agents.fundamental.financial_statements.infrastructure.sec_xbrl.fetch.extractor_search_processing_service import (
    normalize_unit,
    period_sort_key,
)
from src.agents.fundamental.financial_statements.infrastructure.sec_xbrl.map.anchor.extension_anchor_service import (
    ANCHOR_RULE_NOT_FOUND,
    build_default_extension_anchor_service,
)
from src.agents.fundamental.financial_statements.infrastructure.sec_xbrl.map.base_model_mapping_resolver_service import (
    resolve_configs,
)
from src.agents.fundamental.financial_statements.infrastructure.sec_xbrl.map.mapping import (
    FIELD_MAPPING_NOT_FOUND,
    FieldSpec,
    XbrlMappingRegistry,
    get_mapping_registry,
)


def test_normalize_unit_handles_u_prefix() -> None:
    assert normalize_unit("U_USD") == "usd"
    assert normalize_unit("iso4217:USD") == "usd"


def test_period_sort_key_prefers_latest_end_date() -> None:
    latest = period_sort_key("duration_2024-01-01_2024-12-31")
    older = period_sort_key("instant_2023-12-31")
    assert latest > older


def test_interest_expense_mapping_includes_operating_nonoperating_tags() -> None:
    spec = get_mapping_registry().get("interest_expense")
    assert spec is not None
    concepts = [cfg.concept_regex for cfg in spec.configs]
    assert "us-gaap:InterestExpenseOperating" in concepts
    assert "us-gaap:InterestExpenseNonoperating" in concepts


def test_capex_mapping_includes_productive_assets_tag() -> None:
    spec = get_mapping_registry().get("capex")
    assert spec is not None
    concepts = [cfg.concept_regex for cfg in spec.configs]
    assert "us-gaap:PaymentsToAcquireProductiveAssets" in concepts


def test_shares_outstanding_mapping_relaxes_anchor_date() -> None:
    spec = get_mapping_registry().get("shares_outstanding")
    assert spec is not None
    assert all(cfg.respect_anchor_date is False for cfg in spec.configs)


def test_debt_long_mapping_includes_notes_payable() -> None:
    spec = get_mapping_registry().get("debt_long")
    assert spec is not None
    concepts = [cfg.concept_regex for cfg in spec.configs]
    assert "us-gaap:NotesPayable" in concepts


def test_debt_short_mapping_includes_loans_payable() -> None:
    spec = get_mapping_registry().get("debt_short")
    assert spec is not None
    concepts = [cfg.concept_regex for cfg in spec.configs]
    assert "us-gaap:LoansPayable" in concepts


def test_real_estate_dep_amort_mapping_includes_dep_depletion() -> None:
    spec = get_mapping_registry().get("real_estate_dep_amort")
    assert spec is not None
    concepts = [cfg.concept_regex for cfg in spec.configs]
    assert "us-gaap:DepreciationDepletionAndAmortization" in concepts


def test_total_revenue_mapping_includes_bank_net_revenue_tags() -> None:
    spec = get_mapping_registry().get("total_revenue")
    assert spec is not None
    concepts = [cfg.concept_regex for cfg in spec.configs]
    assert "us-gaap:RevenuesNetOfInterestExpense" in concepts


def test_income_before_tax_mapping_includes_extended_us_gaap_aliases() -> None:
    spec = get_mapping_registry().get("income_before_tax")
    assert spec is not None
    concepts = [cfg.concept_regex for cfg in spec.configs]
    assert "us-gaap:IncomeBeforeIncomeTaxes" in concepts
    assert "us-gaap:IncomeLossBeforeIncomeTaxesMinorityInterest" in concepts
    assert (
        "us-gaap:IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments"
        in concepts
    )


def test_total_debt_including_leases_mapping_includes_current_maturities_tag() -> None:
    spec = get_mapping_registry().get("total_debt_including_finance_leases_combined")
    assert spec is not None
    concepts = [cfg.concept_regex for cfg in spec.configs]
    assert (
        "us-gaap:LongTermDebtAndCapitalLeaseObligationsIncludingCurrentMaturities"
        in concepts
    )


def test_tier1_capital_ratio_mapping_accepts_number_unit() -> None:
    spec = get_mapping_registry().get("tier1_capital_ratio")
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
    allowance_spec = get_mapping_registry().get("allowance_for_credit_losses")
    assert allowance_spec is not None
    allowance_concepts = [cfg.concept_regex for cfg in allowance_spec.configs]
    assert (
        "us-gaap:FinancingReceivableAllowanceForCreditLossExcludingAccruedInterest"
        in allowance_concepts
    )

    income_spec = get_mapping_registry().get("interest_income")
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


def test_extension_anchor_service_prefers_issuer_then_industry_then_global() -> None:
    service = build_default_extension_anchor_service()

    issuer_resolution = service.resolve(
        field_key="income_before_tax",
        industry="Financial Services",
        issuer="AMZN",
    )
    assert issuer_resolution.source == "issuer_anchor"
    assert issuer_resolution.unresolved_reason is None

    industry_resolution = service.resolve(
        field_key="income_before_tax",
        industry="Financial Services",
        issuer="JPM",
    )
    assert industry_resolution.source == "industry_anchor"
    assert industry_resolution.unresolved_reason is None

    global_resolution = service.resolve(
        field_key="income_before_tax",
        industry="Industrial",
        issuer="MSFT",
    )
    assert global_resolution.source == "global_anchor"
    assert global_resolution.unresolved_reason is None

    missing_resolution = service.resolve(
        field_key="unknown_field",
        industry="Industrial",
        issuer="MSFT",
    )
    assert missing_resolution.source is None
    assert missing_resolution.unresolved_reason == ANCHOR_RULE_NOT_FOUND


def test_registry_resolve_applies_anchor_configs_for_amzn_income_before_tax() -> None:
    resolved = get_mapping_registry().resolve(
        "income_before_tax",
        industry="Industrial",
        issuer="AMZN",
    )
    assert resolved is not None
    assert resolved.anchor_source == "issuer_anchor"
    assert resolved.anchor_rule_count >= 1
    concepts = [cfg.concept_regex for cfg in resolved.spec.configs[:3]]
    assert "amzn:IncomeBeforeIncomeTaxes" in concepts


def test_registry_resolve_with_reason_reports_machine_readable_unresolved_code() -> (
    None
):
    result = get_mapping_registry().resolve_with_reason(
        "field_not_registered",
        industry="Industrial",
        issuer="AMZN",
    )
    assert result.resolved is None
    assert result.unresolved_reason == FIELD_MAPPING_NOT_FOUND


def test_resolve_configs_enriches_ranking_metadata_for_anchor_mappings() -> None:
    configs = resolve_configs(
        field_key="income_before_tax",
        industry="Industrial",
        issuer="AMZN",
        registry=get_mapping_registry(),
        logger_=logging.getLogger(__name__),
    )
    assert configs
    assert all(config.mapping_source is not None for config in configs)
    assert all(config.anchor_confidence is not None for config in configs)
    assert configs[0].concept_priority >= configs[-1].concept_priority
