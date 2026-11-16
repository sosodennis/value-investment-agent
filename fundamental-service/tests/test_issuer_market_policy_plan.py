from fundamental_service.classification_crosswalk import (
    ClassificationCrosswalkPolicyV1,
    apply_industry_crosswalk,
)
from fundamental_service.issuer_classification import reproduce_issuer_classification
from fundamental_service.issuer_country_crosswalk import (
    CountryCrosswalkPolicyV1,
    apply_country_crosswalk,
)
from fundamental_service.issuer_market_policy_plan import (
    IssuerMarketReferencePlanPolicyV1,
    build_issuer_market_reference_plan,
)
from fundamental_service.sec_classification_source import (
    SecSubmissionClassificationProvider,
)
from fundamental_service.sec_sic_damodaran_crosswalk import (
    DAMODARAN_US_INDUSTRY_TAXONOMY,
    SEC_SIC_DAMODARAN_VERSION,
    SecSicDamodaranIndustryCrosswalk,
)
from fundamental_service.sec_state_country_crosswalk import (
    DAMODARAN_COUNTRY_TAXONOMY,
    SEC_STATE_COUNTRY_SCHEME,
    SecStateCountryCrosswalk,
)
from test_issuer_classification import request, sec_submission


def _classification(*, state: str = "CA", sic: str = "3571"):
    source = sec_submission(
        state=state,
        sic=f"ELECTRONIC COMPUTERS [{sic}]",
    )
    return reproduce_issuer_classification(
        SecSubmissionClassificationProvider(),
        request=request(),
        sources=(source,),
    )


def _mapped(classification):
    country_provider = SecStateCountryCrosswalk()
    industry_provider = SecSicDamodaranIndustryCrosswalk()
    country = apply_country_crosswalk(
        classification,
        policy=CountryCrosswalkPolicyV1(
            provider_id=country_provider.provider_id,
            mapping_version=country_provider.mapping_version,
            mapping_digest=country_provider.mapping_digest,
            source_scheme=SEC_STATE_COUNTRY_SCHEME,
            target_taxonomy=DAMODARAN_COUNTRY_TAXONOMY,
        ),
        provider=country_provider,
    )
    industry = apply_industry_crosswalk(
        classification,
        policy=ClassificationCrosswalkPolicyV1(
            provider_id=industry_provider.provider_id,
            mapping_version=SEC_SIC_DAMODARAN_VERSION,
            mapping_digest=industry_provider.mapping_digest,
            source_scheme="sec-sic-v1",
            target_taxonomy=DAMODARAN_US_INDUSTRY_TAXONOMY,
        ),
        provider=industry_provider,
    )
    return country, industry


def test_plan_builder_joins_provider_neutral_mappings_to_reference_subjects():
    classification = _classification()
    country, industry = _mapped(classification)

    result = build_issuer_market_reference_plan(
        classification,
        country_mapping=country,
        industry_mapping=industry,
        policy=IssuerMarketReferencePlanPolicyV1(),
        policy_id="fcff_dcf-us-gaap-public-v3",
    )

    assert result.status == "planned"
    assert result.issue_codes == ()
    assert result.plan is not None
    assert result.plan.issuer_id == classification.request.issuer_id
    assert result.plan.valuation_at == classification.request.valuation_at
    assert tuple(item.metric for item in result.plan.selections) == (
        "country.equity_risk_premium",
        "industry.debt_weight",
        "industry.equity_beta",
        "industry.equity_weight",
        "industry.pre_tax_cost_of_debt",
    )
    assert result.plan.selections[0].subject == "United States"
    assert all(
        item.subject == "Computers/Peripherals" for item in result.plan.selections[1:]
    )


def test_plan_builder_replays_without_changing_digests():
    classification = _classification()
    country, industry = _mapped(classification)
    policy = IssuerMarketReferencePlanPolicyV1()
    first = build_issuer_market_reference_plan(
        classification,
        country_mapping=country,
        industry_mapping=industry,
        policy=policy,
        policy_id="fcff_dcf-us-gaap-public-v3",
    )
    repeated = build_issuer_market_reference_plan(
        classification,
        country_mapping=country,
        industry_mapping=industry,
        policy=policy,
        policy_id="fcff_dcf-us-gaap-public-v3",
        expected=first,
    )

    assert repeated == first
    assert repeated.output_digest == first.output_digest


def test_plan_builder_preserves_unmapped_country_as_refusal():
    classification = _classification(state="A1")
    country, industry = _mapped(classification)

    result = build_issuer_market_reference_plan(
        classification,
        country_mapping=country,
        industry_mapping=industry,
        policy=IssuerMarketReferencePlanPolicyV1(),
        policy_id="fcff_dcf-us-gaap-public-v3",
    )

    assert result.status == "refused"
    assert result.plan is None
    assert result.issue_codes == (
        "ISSUER_COUNTRY_CROSSWALK_REFUSED",
        "ISSUER_JURISDICTION_CROSSWALK_UNMAPPED",
    )
