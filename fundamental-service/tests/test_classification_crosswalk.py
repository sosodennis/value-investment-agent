import pytest

from fundamental_service.classification_crosswalk import (
    ClassificationCrosswalkPolicyV1,
    IndustryCrosswalkRuleV1,
    apply_industry_crosswalk,
)
from fundamental_service.issuer_classification import reproduce_issuer_classification
from fundamental_service.sec_sic_damodaran_crosswalk import (
    DAMODARAN_US_INDUSTRY_TAXONOMY,
    SEC_SIC_DAMODARAN_PROVIDER,
    SEC_SIC_DAMODARAN_VERSION,
    SecSicDamodaranIndustryCrosswalk,
)
from fundamental_service.sec_classification_source import (
    SecSubmissionClassificationProvider,
)
from fundamental_service.snapshots import SnapshotError
from test_issuer_classification import request, sec_submission


def _classification(*, sic: str = "3571"):
    source = sec_submission(sic=f"ELECTRONIC COMPUTERS [{sic}]")
    return reproduce_issuer_classification(
        SecSubmissionClassificationProvider(),
        request=request(),
        sources=(source,),
    )


def _policy() -> ClassificationCrosswalkPolicyV1:
    provider = SecSicDamodaranIndustryCrosswalk()
    return ClassificationCrosswalkPolicyV1(
        provider_id=provider.provider_id,
        mapping_version=provider.mapping_version,
        mapping_digest=provider.mapping_digest,
        source_scheme="sec-sic-v1",
        target_taxonomy=DAMODARAN_US_INDUSTRY_TAXONOMY,
    )


def test_exact_sic_mapping_keeps_original_and_mapping_digests():
    classification = _classification()
    policy = _policy()
    provider = SecSicDamodaranIndustryCrosswalk()
    result = apply_industry_crosswalk(classification, policy=policy, provider=provider)
    repeated = apply_industry_crosswalk(
        classification, policy=policy, provider=provider, expected=result
    )

    assert result.status == "mapped"
    assert repeated == result
    assert result.issue_codes == ()
    assert result.source_scheme == "sec-sic-v1"
    assert result.source_code == "3571"
    assert result.target_subject == "Computers/Peripherals"
    assert result.target_population == "us-companies"
    assert result.rule_id == "sic-3571-computers-peripherals-v1"
    assert result.classification_digest == _classification().output_digest
    assert result.mapping_digest == SecSicDamodaranIndustryCrosswalk().mapping_digest


@pytest.mark.parametrize("sic", ["9999", "0001"])
def test_unknown_sic_is_retained_as_an_unmapped_refusal(sic):
    result = apply_industry_crosswalk(
        _classification(sic=sic),
        policy=_policy(),
        provider=SecSicDamodaranIndustryCrosswalk(),
    )

    assert result.status == "refused"
    assert result.rule_id is None
    assert result.target_subject is None
    assert result.issue_codes == ("ISSUER_CLASSIFICATION_CROSSWALK_UNMAPPED",)
    assert result.source_code == sic


class AmbiguousCrosswalk:
    provider_id = SEC_SIC_DAMODARAN_PROVIDER
    mapping_version = SEC_SIC_DAMODARAN_VERSION
    target_taxonomy = DAMODARAN_US_INDUSTRY_TAXONOMY
    mapping_digest = "a" * 64

    def candidates(self, *, source_scheme, source_code, target_taxonomy):
        return (
            IndustryCrosswalkRuleV1(
                rule_id="ambiguous-a",
                source_scheme=source_scheme,
                source_code=source_code,
                target_taxonomy=target_taxonomy,
                target_population="us-companies",
                target_subject="Computers/Peripherals",
                basis="test",
            ),
            IndustryCrosswalkRuleV1(
                rule_id="ambiguous-b",
                source_scheme=source_scheme,
                source_code=source_code,
                target_taxonomy=target_taxonomy,
                target_population="us-companies",
                target_subject="Computer Services",
                basis="test",
            ),
        )


class AlternateCrosswalk:
    provider_id = "alternate-industry-crosswalk"
    mapping_version = "alternate-v1"
    target_taxonomy = DAMODARAN_US_INDUSTRY_TAXONOMY
    mapping_digest = "b" * 64

    def candidates(self, *, source_scheme, source_code, target_taxonomy):
        return (
            IndustryCrosswalkRuleV1(
                rule_id="alternate-computer-hardware-v1",
                source_scheme=source_scheme,
                source_code=source_code,
                target_taxonomy=target_taxonomy,
                target_population="us-companies",
                target_subject="Computers/Peripherals",
                basis="alternate provider fixture",
            ),
        )


def test_alternate_crosswalk_provider_uses_the_same_mapping_contract():
    provider = AlternateCrosswalk()
    policy = ClassificationCrosswalkPolicyV1(
        provider_id=provider.provider_id,
        mapping_version=provider.mapping_version,
        mapping_digest=provider.mapping_digest,
        source_scheme="sec-sic-v1",
        target_taxonomy=provider.target_taxonomy,
    )
    result = apply_industry_crosswalk(
        _classification(), policy=policy, provider=provider
    )

    assert result.status == "mapped"
    assert result.provider_id == provider.provider_id
    assert result.mapping_version == provider.mapping_version
    assert result.mapping_digest == provider.mapping_digest
    assert result.rule_id == "alternate-computer-hardware-v1"


def test_ambiguous_crosswalk_never_picks_a_subject():
    policy = _policy().model_copy(update={"mapping_digest": "a" * 64})
    result = apply_industry_crosswalk(
        _classification(), policy=policy, provider=AmbiguousCrosswalk()
    )

    assert result.status == "refused"
    assert result.issue_codes == ("ISSUER_CLASSIFICATION_CROSSWALK_AMBIGUOUS",)
    assert result.candidate_rule_ids == ("ambiguous-a", "ambiguous-b")
    assert result.target_subject is None


def test_changed_classification_bytes_fail_replay():
    provider = SecSicDamodaranIndustryCrosswalk()
    classification = _classification()
    first = apply_industry_crosswalk(
        classification, policy=_policy(), provider=provider
    )
    changed = _classification(sic="3572")
    with pytest.raises(SnapshotError) as error:
        apply_industry_crosswalk(
            changed, policy=_policy(), provider=provider, expected=first
        )
    assert error.value.code == "ISSUER_CLASSIFICATION_CROSSWALK_REPLAY_MISMATCH"


def test_wrong_policy_provider_is_retained_as_refusal():
    policy = _policy().model_copy(update={"mapping_version": "other-v1"})
    result = apply_industry_crosswalk(
        _classification(), policy=policy, provider=SecSicDamodaranIndustryCrosswalk()
    )
    assert result.status == "refused"
    assert result.issue_codes == ("ISSUER_CLASSIFICATION_CROSSWALK_PROVIDER_MISMATCH",)


def test_changed_mapping_manifest_digest_is_refused_without_version_change():
    policy = _policy().model_copy(update={"mapping_digest": "c" * 64})
    result = apply_industry_crosswalk(
        _classification(),
        policy=policy,
        provider=SecSicDamodaranIndustryCrosswalk(),
    )

    assert result.status == "refused"
    assert result.issue_codes == ("ISSUER_CLASSIFICATION_CROSSWALK_PROVIDER_MISMATCH",)
