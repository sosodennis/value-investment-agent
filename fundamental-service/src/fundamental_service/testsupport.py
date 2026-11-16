"""Small fixture constructors shared by service contract tests."""

from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from typing import Mapping

from src.shared.internal_services import InternalPrincipal, build_internal_context

from .contracts import (
    AssumptionsV1,
    CapitalBridgeAssumptionsV1,
    ForecastAssumptionsV1,
    IdentityV1,
    ProvenanceInputV1,
    QualityInputV1,
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
        identity=IdentityV1(
            issuer_id="CIK1",
            issuer_name="Example Corp",
            domicile="US",
            reporting_basis="us-gaap",
            security_id="COMMON",
            share_class="common",
            currency="USD",
        ),
        valuation_context=ValuationContextV1(
            valuation_timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
            data_snapshot_id="snapshot-1",
            source_selection_policy="pit-v1",
            coverage_profile="us-gaap-public-v1",
        ),
        historical_facts=("revenue",),
        assumptions=AssumptionsV1(
            forecast=ForecastAssumptionsV1(
                base_revenue=Decimal("100"),
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
                non_operating_assets=Decimal("0"),
                debt=Decimal("5"),
                preferred_stock=Decimal("0"),
                lease_liabilities=Decimal("0"),
                non_controlling_interest=Decimal("0"),
                diluted_shares=Decimal("100"),
            ),
            trace=TraceV1(description="fixture assumptions"),
        ),
        uncertainty=UncertaintyV1(mode="none"),
        quality=QualityInputV1(status=QualityStatus.VERIFIED),
        provenance=ProvenanceInputV1(
            snapshot_id="snapshot-1",
            mapping_version="mapping-v1",
            parser_version="parser-v1",
            taxonomy_version="taxonomy-v1",
        ),
        model_id="fcff_dcf",
        model_version="fcff_dcf-v2",
    )


TEST_SERVICE_TOKEN = "test-service-token"


def make_internal_envelope(
    input_payload: Mapping[str, object],
    *,
    correlation_id: str = "correlation-test",
    deadline_at: datetime | None = None,
    issued_at: datetime | None = None,
    audience: str = "fundamental-service",
    organization_id: str | None = "organization-test",
    membership_id: str | None = "membership-test",
) -> dict[str, object]:
    context = build_internal_context(
        principal=InternalPrincipal(
            subject_id="subject-test",
            organization_id=organization_id,
            membership_id=membership_id,
        ),
        correlation_id=correlation_id,
        deadline_at=deadline_at or datetime.now(UTC) + timedelta(seconds=30),
        audience=audience,
        signing_key=TEST_SERVICE_TOKEN,
        issued_at=issued_at,
    )
    return {"context": context.model_dump(mode="json"), "input": dict(input_payload)}


def auth_headers(*, organization_id: str = "organization-test") -> dict[str, str]:
    return {
        "Authorization": f"Bearer {TEST_SERVICE_TOKEN}",
        "X-Organization-ID": organization_id,
    }
