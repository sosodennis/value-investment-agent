"""Small fixture constructors shared by service contract tests."""

from datetime import datetime, timezone
from decimal import Decimal

from .contracts import (
    AssumptionsV1,
    CapitalBridgeAssumptionsV1,
    ForecastAssumptionsV1,
    QualityStatus,
    TraceV1,
    UncertaintyV1,
    ValuationContextV1,
    ValuationInputV1,
    WaccAssumptionsV1,
)


def make_valuation() -> ValuationInputV1:
    return ValuationInputV1(
        contract_version="fundamental.v1",
        identity={
            "issuer_id": "CIK1",
            "issuer_name": "Example Corp",
            "domicile": "US",
            "reporting_basis": "us-gaap",
            "security_id": "COMMON",
            "share_class": "common",
            "currency": "USD",
        },
        valuation_context=ValuationContextV1(
            valuation_timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
            data_snapshot_id="snapshot-1",
            source_selection_policy="pit-v1",
            coverage_profile="us-gaap-public-v1",
        ),
        historical_facts=("revenue",),
        assumptions=AssumptionsV1(
            forecast=ForecastAssumptionsV1(
                revenue_growth=(Decimal("0.05"),),
                operating_margin=(Decimal("0.15"),),
                reinvestment_rate=(Decimal("0.20"),),
            ),
            wacc=WaccAssumptionsV1(
                risk_free_rate=Decimal("0.04"),
                beta=Decimal("1.1"),
                equity_risk_premium=Decimal("0.05"),
                pre_tax_cost_of_debt=Decimal("0.05"),
                tax_rate=Decimal("0.21"),
                debt_weight=Decimal("0.2"),
                equity_weight=Decimal("0.8"),
            ),
            terminal_growth=Decimal("0.02"),
            capital_bridge=CapitalBridgeAssumptionsV1(
                cash=Decimal("10"),
                debt=Decimal("5"),
                preferred_stock=Decimal("0"),
                lease_liabilities=Decimal("0"),
                non_controlling_interest=Decimal("0"),
                diluted_shares=Decimal("100"),
            ),
            trace=TraceV1(description="fixture assumptions"),
        ),
        uncertainty=UncertaintyV1(mode="none"),
        quality={"status": QualityStatus.VERIFIED},
        provenance={
            "snapshot_id": "snapshot-1",
            "mapping_version": "mapping-v1",
            "parser_version": "parser-v1",
            "taxonomy_version": "taxonomy-v1",
        },
        model_id="fcff_dcf",
        model_version="fcff_dcf-v1",
    )
