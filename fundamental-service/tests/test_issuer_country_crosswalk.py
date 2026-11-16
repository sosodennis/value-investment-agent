from fundamental_service.issuer_classification import reproduce_issuer_classification
from fundamental_service.issuer_country_crosswalk import (
    CountryCrosswalkPolicyV1,
    apply_country_crosswalk,
)
from fundamental_service.sec_classification_source import (
    SecSubmissionClassificationProvider,
)
from fundamental_service.sec_state_country_crosswalk import (
    DAMODARAN_COUNTRY_TAXONOMY,
    SEC_STATE_COUNTRY_PROVIDER,
    SEC_STATE_COUNTRY_SCHEME,
    SEC_STATE_COUNTRY_VERSION,
    SecStateCountryCrosswalk,
)
from test_issuer_classification import request, sec_submission


def _classification(*, jurisdiction: str = "CA"):
    source = sec_submission(state=jurisdiction)
    return reproduce_issuer_classification(
        SecSubmissionClassificationProvider(),
        request=request(),
        sources=(source,),
    )


def _policy() -> CountryCrosswalkPolicyV1:
    provider = SecStateCountryCrosswalk()
    return CountryCrosswalkPolicyV1(
        provider_id=SEC_STATE_COUNTRY_PROVIDER,
        mapping_version=SEC_STATE_COUNTRY_VERSION,
        mapping_digest=provider.mapping_digest,
        source_scheme=SEC_STATE_COUNTRY_SCHEME,
        target_taxonomy=DAMODARAN_COUNTRY_TAXONOMY,
    )


def test_sec_state_maps_to_country_and_replays_exact_digests():
    classification = _classification()
    policy = _policy()
    provider = SecStateCountryCrosswalk()
    first = apply_country_crosswalk(classification, policy=policy, provider=provider)
    repeated = apply_country_crosswalk(
        classification, policy=policy, provider=provider, expected=first
    )

    assert first == repeated
    assert first.status == "mapped"
    assert first.source_code == "CA"
    assert first.target_country_code == "US"
    assert first.target_population == "countries"
    assert first.target_subject == "United States"
    assert first.rule_id == "sec-us-jurisdiction-CA-country-v1"


def test_foreign_jurisdiction_is_not_guessed_from_a_short_code():
    result = apply_country_crosswalk(
        _classification(jurisdiction="A1"),
        policy=_policy(),
        provider=SecStateCountryCrosswalk(),
    )

    assert result.status == "refused"
    assert result.target_subject is None
    assert result.issue_codes == ("ISSUER_JURISDICTION_CROSSWALK_UNMAPPED",)
    assert result.source_value == "A1"


def test_changed_country_crosswalk_manifest_digest_is_refused():
    policy = _policy().model_copy(update={"mapping_digest": "a" * 64})
    result = apply_country_crosswalk(
        _classification(), policy=policy, provider=SecStateCountryCrosswalk()
    )

    assert result.status == "refused"
    assert result.issue_codes == ("ISSUER_COUNTRY_CROSSWALK_PROVIDER_MISMATCH",)
