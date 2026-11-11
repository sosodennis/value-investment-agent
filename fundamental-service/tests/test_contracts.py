from datetime import datetime, timezone
from decimal import Decimal

import pytest
from fundamental_service.contracts import (
    AssumptionsV1,
    CallerApprovalEnvelopeV1,
    CapitalBridgeAssumptionsV1,
    ForecastAssumptionsV1,
    IdentityV1,
    QualityStatus,
    SecFilingSelectorV1,
    SecIngestionRequestV1,
    SecMappingReferenceV1,
    TraceV1,
    UncertaintyV1,
    ValuationContextV1,
    ValuationInputV1,
    WaccAssumptionsV1,
)
from pydantic import ValidationError


def assumptions() -> AssumptionsV1:
    return AssumptionsV1(
        forecast=ForecastAssumptionsV1(
            revenue_growth=(Decimal("0.05"),),
            operating_margin=(Decimal("0.15"),),
            reinvestment_rate=(Decimal("0.2"),),
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
        trace=TraceV1(description="caller supplied assumptions"),
    )


def valuation() -> ValuationInputV1:
    return ValuationInputV1(
        contract_version="fundamental.v1",
        identity=IdentityV1(
            issuer_id="CIK0000000001",
            issuer_name="Example Corp",
            domicile="US",
            reporting_basis="us-gaap",
            security_id="EXAMPLE-COMMON",
            share_class="common",
            currency="USD",
        ),
        valuation_context=ValuationContextV1(
            valuation_timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
            data_snapshot_id="snapshot-1",
            source_selection_policy="pit-v1",
            coverage_profile="us-gaap-public-v1",
        ),
        historical_facts=("fact-revenue",),
        assumptions=assumptions(),
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


def test_digest_is_stable_and_approval_binds_to_exact_input():
    request = valuation().with_digest()
    assert request.input_digest == request.with_digest().input_digest
    approved = request.model_copy(
        update={
            "caller_approval": CallerApprovalEnvelopeV1(
                input_digest=request.input_digest,
                decision="approved",
                caller_id="caller",
                decided_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            )
        }
    )
    assert approved.caller_approval is not None


def test_preparation_version_is_bound_to_input_digest_and_roundtrips():
    caller_input = valuation().with_digest()
    assert "preparation_version" not in caller_input.provenance.model_dump()
    prepared = caller_input.model_copy(
        update={
            "provenance": caller_input.provenance.model_copy(
                update={"preparation_version": "fcff-forecast-composer-v2"}
            )
        }
    ).with_digest()
    assert prepared.input_digest != caller_input.input_digest
    restored = ValuationInputV1.model_validate_json(prepared.model_dump_json())
    assert restored.input_digest == prepared.input_digest
    assert restored.provenance.preparation_version == "fcff-forecast-composer-v2"


def test_unknown_fields_and_invalid_digest_are_rejected():
    with pytest.raises(ValidationError):
        ValuationInputV1(**{**valuation().model_dump(), "unexpected": True})
    with pytest.raises(ValidationError):
        ValuationInputV1(**{**valuation().model_dump(), "input_digest": "0" * 64})


def test_valuation_context_rejects_naive_timestamp():
    with pytest.raises(ValidationError, match="valuation_timestamp"):
        ValuationContextV1(
            valuation_timestamp=datetime(2026, 1, 1),
            data_snapshot_id="snapshot-1",
            source_selection_policy="pit-v1",
            coverage_profile="us-gaap-public-v1",
        )


def test_sec_ingestion_accepts_transition_fcff_evidence_set():
    required_fields = tuple(f"field-{index}" for index in range(33))
    request = SecIngestionRequestV1(
        contract_version="fundamental.v1",
        identity=IdentityV1(
            issuer_id="0000000001",
            issuer_name="Example Corp",
            domicile="US",
            reporting_basis="us-gaap",
            security_id="EXAMPLE",
            share_class="common",
            currency="USD",
        ),
        cik="0000000001",
        ticker="EXAMPLE",
        valuation_timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
        required_fields=required_fields,
        mappings=tuple(
            SecMappingReferenceV1(
                decision_id=f"mapping-{index}",
                mapping_version="sec-us-gaap-v1",
                normalized_field=field,
            )
            for index, field in enumerate(required_fields)
        ),
        source_selection_policy="sec-pit-v1",
        coverage_profile="us-gaap-public-v1",
        legal_use_profile="sec-public-us-v1",
        filing=SecFilingSelectorV1(forms=("10-K", "10-Q")),
        parser_version="2.47.4",
        validation_profile_id="sec-efm-us-dqc-v31.0.3",
        taxonomy_manifest_id="sec-us-gaap-2023-2024-public-bundle",
        taxonomy_version="us-gaap-2023-2024",
        policy_version="sec-public-pit-v1",
    )

    assert len(request.required_fields) == 33
    assert len(request.mappings) == 33
