import pytest
from fundamental_service.valuation_requirements import (
    UnsupportedValuationModel,
    ValuationRequirementsProfileV1,
    valuation_requirements_profile,
)
from pydantic import ValidationError


def test_released_fcff_profiles_share_sec_evidence_and_keep_history_provisional() -> (
    None
):
    fcff = valuation_requirements_profile("fcff_dcf")
    transition = valuation_requirements_profile("transition_fcff_dcf")

    assert fcff.annual_duration_fields == transition.annual_duration_fields
    assert fcff.annual_instant_fields == transition.annual_instant_fields
    assert "revenue" in fcff.annual_duration_fields
    assert "income_tax_expense" in fcff.annual_duration_fields
    assert "capital_expenditure" in fcff.annual_duration_fields
    assert "inventory" in fcff.annual_instant_fields
    assert "cash_and_equivalents" in fcff.point_in_time_fact_fields
    assert "marginal_cost_of_debt" in fcff.market_policy_input_roles
    assert fcff.supported_history_threshold is None
    assert transition.supported_history_threshold is None
    assert not fcff.transition_filing_evidence_required
    assert transition.transition_filing_evidence_required
    assert fcff.digest != transition.digest


def test_profile_rejects_duplicate_fields_and_history_outside_window() -> None:
    with pytest.raises(ValidationError, match="fields must be unique"):
        ValuationRequirementsProfileV1(
            profile_id="invalid",
            profile_version="v1",
            model_id="fcff_dcf",
            annual_duration_fields=("revenue", "revenue"),
            annual_instant_fields=("inventory",),
        )

    with pytest.raises(ValidationError, match="cannot exceed"):
        ValuationRequirementsProfileV1(
            profile_id="invalid",
            profile_version="v1",
            model_id="fcff_dcf",
            annual_duration_fields=("revenue",),
            annual_instant_fields=("inventory",),
            history_window_years=2,
            candidate_minimum_complete_years=3,
        )


def test_unreleased_model_has_no_requirements_profile() -> None:
    with pytest.raises(UnsupportedValuationModel):
        valuation_requirements_profile("bank_excess_return")
