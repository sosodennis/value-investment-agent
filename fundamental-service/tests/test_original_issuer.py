"""An original issuer claim has no security, release or approval authority."""

from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from fundamental_service.annual_history import resolve_annual_history
from fundamental_service.arelle_parser import (
    ArelleFindingV1,
    ArelleParseReportV1,
    ArelleValidationProfileV1,
    ParsedXbrlFactV1,
)
from fundamental_service.contracts import IdentityV1, QualityStatus, SourceSnapshotV1
from fundamental_service.original_issuer import (
    IssuerOperatingSourceV1,
    OriginalIssuerEvidenceV1,
    OriginalIssuerIdentityV1,
    OriginalOperatingSourceV1,
    compose_issuer_operating_source,
    evaluate_original_issuer,
)
from fundamental_service.serialization import canonical_bytes, sha256_digest
from fundamental_service.valuation_requirements import valuation_requirements_profile
from test_operating_forecast import operating_facts, prepare
from fundamental_service.valuation_preparation import prepare_automatic_valuation

ACCEPTED = datetime(2026, 2, 1, tzinfo=UTC)
DECISION = datetime(2026, 3, 1, tzinfo=UTC)
CAPTURED = datetime(2026, 11, 11, tzinfo=UTC)
ACCESSION = "0000000001-26-000001"
URI = f"https://www.sec.gov/Archives/edgar/data/1/{ACCESSION.replace('-', '')}/original.xml"


def original():
    values = {
        "EntityCentralIndexKey": "0000000001",
        "EntityRegistrantName": "Example Co",
        "DocumentType": "10-K",
        "DocumentPeriodEndDate": "2025-12-31",
        "AmendmentFlag": "false",
    }
    facts = tuple(
        ParsedXbrlFactV1(
            concept=f"dei:{concept}",
            namespace_uri="http://xbrl.sec.gov/dei/2015-01-31",
            value=value,
            context_id="annual",
            entity_scheme="http://www.sec.gov/CIK",
            entity_identifier="0000000001",
            period_start=date(2025, 1, 1),
            period_end=date(2025, 12, 31),
            consolidation_scope="consolidated",
        )
        for concept, value in values.items()
    )
    monetary = facts[0].model_copy(
        update={
            "concept": "us-gaap:SalesRevenueNet",
            "namespace_uri": "http://fasb.org/us-gaap/2015-01-31",
            "is_numeric": True,
            "unit": "iso4217:USD",
            "value": "100",
            "consolidation_scope": "consolidated",
        }
    )
    profile = ArelleValidationProfileV1(profile_id="synthetic-issuer-identity")
    report = ArelleParseReportV1(
        filing_path="temporary-path.xml",
        parser_version="2.47.4",
        taxonomy_version="us-gaap-2015",
        validation_profile=profile,
        validation_profile_digest=profile.digest(),
        facts=(*facts, monetary),
        parsed_at=CAPTURED,
        source_content_hash="b" * 64,
        # This deliberately has no regulatory-completion evidence.
    )
    source = OriginalOperatingSourceV1(
        cik="0000000001",
        accession_number=ACCESSION,
        uri=URI,
        content_hash="a" * 64,
        parser_input_hash="b" * 64,
        form="10-K",
        available_at=ACCEPTED,
        captured_at=CAPTURED,
        http_status=None,
    )
    return report, source


def evaluate(report=None, source=None):
    default_report, default_source = original()
    return evaluate_original_issuer(
        report or default_report, source=source or default_source, decision_at=DECISION
    )


def operating_source():
    return compose_issuer_operating_source((evaluate(),), valuation_timestamp=DECISION)


def issuer_facts():
    return tuple(
        fact.model_copy(
            update={
                "issuer_id": "0000000001",
                "security_id": None,
                "security_scope": "issuer",
                "accession_number": ACCESSION,
                "available_at": ACCEPTED,
                "filed_at": ACCEPTED,
                "source": fact.source.model_copy(
                    update={
                        "source_url": URI,
                        "available_at": ACCEPTED,
                        "filed_at": ACCEPTED,
                        "accession_number": ACCESSION,
                    }
                ),
            }
        )
        for fact in operating_facts()
    )


def test_pre_cover_tagging_original_proves_only_issuer_scope():
    result = evaluate()
    assert result.status == "matched" and not result.issue_codes
    assert result.identity.issuer_id == "0000000001"
    assert result.report_period_end == date(2025, 12, 31)
    assert result.source.http_status is None
    assert set(result.unestablished_claims) == {
        "security_identity",
        "domicile",
        "regulatory_approval",
        "mapping_review",
        "data_release_authority",
    }
    assert (
        not {"security_id", "share_class", "domicile"}
        & result.identity.model_dump().keys()
    )
    assert (
        OriginalIssuerEvidenceV1.model_validate_json(canonical_bytes(result)) == result
    )
    with pytest.raises(ValidationError):
        IdentityV1.model_validate(result.identity.model_dump())
    with pytest.raises(ValidationError):
        SourceSnapshotV1.model_validate(operating_source().model_dump())


def test_order_paths_and_parse_time_do_not_change_original_evidence():
    report, _ = original()
    first = evaluate(report)
    reordered = report.model_copy(
        update={
            "facts": tuple(reversed(report.facts)),
            "filing_path": "different-temporary-path.xml",
            "parsed_at": datetime(2026, 11, 12, tzinfo=UTC),
        }
    )
    assert canonical_bytes(first) == canonical_bytes(evaluate(reordered))
    assert first.output_digest == sha256_digest(
        first.model_dump(exclude={"output_digest"})
    )
    assert operating_source() == compose_issuer_operating_source(
        (first,), valuation_timestamp=DECISION
    )


@pytest.mark.parametrize(
    "change",
    (
        {"source_content_hash": "c" * 64},
        {"offline": False},
        {"network_attempt_count": 1},
        {"validation_profile_digest": "c" * 64},
    ),
)
def test_wrong_parser_source_or_execution_is_retained_as_refusal(change):
    report, _ = original()
    result = evaluate(report.model_copy(update=change))
    assert result.issue_codes == ("ORIGINAL_ISSUER_SOURCE_INVALID",)
    assert result.status == "refused" and result.identity is None
    assert result.report.source_content_hash == change.get(
        "source_content_hash", report.source_content_hash
    )
    with pytest.raises(ValueError, match="matched originals"):
        compose_issuer_operating_source((result,), valuation_timestamp=DECISION)


@pytest.mark.parametrize(
    "change",
    (
        {"form": "10-K/A"},
        {"is_amendment": True},
        {"available_at": datetime(2027, 1, 1, tzinfo=UTC)},
        {"captured_at": datetime(2025, 1, 1, tzinfo=UTC)},
        {"uri": URI.replace("/data/1/", "/data/2/")},
        {"uri": URI + "../original.xml"},
        {"http_status": 403},
    ),
)
def test_original_source_scope_cannot_be_bypassed(change):
    _, source = original()
    result = evaluate(source=source.model_copy(update=change))
    assert result.issue_codes == ("ORIGINAL_ISSUER_SOURCE_INVALID",)
    assert result.identity is None


@pytest.mark.parametrize(
    "change",
    (
        {"namespace_uri": "https://issuer.test/fake-dei/2015"},
        {"entity_identifier": "0000000002"},
        {"entity_scheme": "https://issuer.test/entity"},
        {"dimensions": (("Axis", "Member"),)},
        {"period_start": date(2025, 10, 1)},
        {"period_end": date(2024, 12, 31)},
        {"unit": "iso4217:USD"},
        {"is_numeric": True},
    ),
)
def test_invalid_issuer_dei_context_cannot_establish_identity(change):
    report, _ = original()
    result = evaluate(
        report.model_copy(
            update={
                "facts": (
                    report.facts[0].model_copy(update=change),
                    *report.facts[1:],
                )
            }
        )
    )
    assert result.issue_codes == ("ORIGINAL_ISSUER_DEI_SCOPE_INVALID",)


@pytest.mark.parametrize(
    "concept,value",
    (
        ("dei:DocumentType", "10-Q"),
        ("dei:AmendmentFlag", "true"),
        ("dei:EntityCentralIndexKey", "0000000002"),
        ("dei:DocumentPeriodEndDate", "2026-12-31"),
        ("dei:DocumentPeriodEndDate", "not-a-date"),
    ),
)
def test_wrong_report_dei_values_remain_refused(concept, value):
    report, _ = original()
    result = evaluate(
        report.model_copy(
            update={
                "facts": tuple(
                    f.model_copy(update={"value": value}) if f.concept == concept else f
                    for f in report.facts
                )
            }
        )
    )
    assert result.status == "refused" and result.identity is None


def test_missing_conflicting_and_cross_period_dei_are_retained():
    report, _ = original()
    assert evaluate(
        report.model_copy(update={"facts": report.facts[1:]})
    ).issue_codes == ("ORIGINAL_ISSUER_DEI_MISSING",)
    conflicting = (*report.facts, report.facts[0].model_copy(update={"value": "2"}))
    first = evaluate(report.model_copy(update={"facts": conflicting}))
    second = evaluate(report.model_copy(update={"facts": tuple(reversed(conflicting))}))
    assert first.issue_codes == ("ORIGINAL_ISSUER_DEI_CONFLICT",)
    assert canonical_bytes(first) == canonical_bytes(second)
    misaligned = report.model_copy(
        update={
            "facts": (
                report.facts[0].model_copy(update={"period_start": date(2024, 12, 31)}),
                *report.facts[1:],
            )
        }
    )
    assert evaluate(misaligned).issue_codes == (
        "ORIGINAL_ISSUER_PERIOD_OR_CIK_INVALID",
    )


@pytest.mark.parametrize(
    "change",
    (
        {"unit": "iso4217:EUR"},
        {"unit": "iso4217:USD/xbrli:shares"},
        {"period_end": date(2024, 12, 31)},
        {"dimensions": (("Axis", "Member"),)},
        {"entity_identifier": "0000000002"},
    ),
)
def test_foreign_or_nonissuer_currency_observation_cannot_establish_scope(change):
    report, _ = original()
    result = evaluate(
        report.model_copy(
            update={
                "facts": (
                    *report.facts[:-1],
                    report.facts[-1].model_copy(update=change),
                )
            }
        )
    )
    assert result.issue_codes == ("ORIGINAL_ISSUER_CURRENCY_UNSUPPORTED",)


def test_mixed_currency_and_nonfinite_original_values_are_refused():
    report, _ = original()
    other = report.facts[-1].model_copy(update={"unit": "iso4217:EUR"})
    assert evaluate(
        report.model_copy(update={"facts": (*report.facts, other)})
    ).issue_codes == ("ORIGINAL_ISSUER_CURRENCY_UNSUPPORTED",)
    for invalid in ("NaN", "Infinity", "not-a-number"):
        result = evaluate(
            report.model_copy(
                update={
                    "facts": (
                        *report.facts[:-1],
                        report.facts[-1].model_copy(update={"value": invalid}),
                    )
                }
            )
        )
        assert result.issue_codes == ("ORIGINAL_ISSUER_MONETARY_VALUE_INVALID",)


@pytest.mark.parametrize("unusable", ("", "NaN", "Infinity", "not-a-number"))
def test_unusable_amounts_do_not_erase_independent_issuer_currency_evidence(unusable):
    report, _ = original()
    missing = report.facts[-1].model_copy(
        update={"concept": "us-gaap:CommitmentsAndContingencies", "value": unusable}
    )
    result = evaluate(report.model_copy(update={"facts": (*report.facts, missing)}))
    assert result.status == "matched"
    assert missing in result.report.facts
    assert result.source.http_status is None
    assert "data_release_authority" in result.unestablished_claims
    assert not any(fact.value == "0" for fact in result.report.facts)


def test_empty_amount_alone_cannot_establish_observed_currency():
    report, _ = original()
    empty = report.facts[-1].model_copy(update={"value": ""})
    result = evaluate(report.model_copy(update={"facts": (*report.facts[:-1], empty)}))
    assert result.issue_codes == ("ORIGINAL_ISSUER_MONETARY_VALUE_INVALID",)
    assert empty in result.report.facts


def test_naive_decision_time_fails_at_the_input_boundary():
    report, source = original()
    with pytest.raises(ValueError, match="timezone"):
        evaluate_original_issuer(
            report, source=source, decision_at=DECISION.replace(tzinfo=None)
        )


def test_duplicate_source_bytes_cannot_alias_different_accessions():
    report, source = original()
    other_accession = "0000000001-25-000001"
    other = evaluate(
        report,
        source.model_copy(
            update={
                "accession_number": other_accession,
                "uri": URI.replace(
                    ACCESSION.replace("-", ""), other_accession.replace("-", "")
                ),
            }
        ),
    )
    with pytest.raises(ValueError, match="distinct source hashes"):
        compose_issuer_operating_source(
            (evaluate(), other), valuation_timestamp=DECISION
        )


def test_issuer_identity_does_not_erase_regulatory_findings_or_grant_approval():
    report, _ = original()
    finding = ArelleFindingV1(
        code="DQC.US.TEST", severity="error", message="retained failure"
    )
    result = evaluate(report.model_copy(update={"findings": (finding,)}))
    assert result.identity is not None and result.status == "matched"
    assert result.report.blocking_finding_codes() == ("DQC.US.TEST",)
    assert "regulatory_approval" in result.unestablished_claims
    for alteration in (
        {"identity": None},
        {"unestablished_claims": ()},
        {"output_digest": "0" * 64},
    ):
        payload = result.model_dump()
        payload.update(alteration)
        with pytest.raises(ValidationError):
            OriginalIssuerEvidenceV1.model_validate(payload)


def test_issuer_source_view_rejects_duplicates_changed_issuer_and_future_label():
    first = evaluate()
    with pytest.raises(ValueError, match="distinct"):
        compose_issuer_operating_source((first, first), valuation_timestamp=DECISION)
    with pytest.raises(ValueError, match="matching available"):
        compose_issuer_operating_source(
            (first,), valuation_timestamp=datetime(2025, 1, 1, tzinfo=UTC)
        )
    payload = operating_source().model_dump()
    payload["identity"]["issuer_id"] = "0000000002"
    with pytest.raises(ValidationError):
        IssuerOperatingSourceV1.model_validate(payload)
    with pytest.raises(ValidationError):
        OriginalIssuerIdentityV1.model_validate(
            {**first.identity.model_dump(), "security_id": "FAKE"}
        )


def test_issuer_operating_stage_reuses_exact_math_without_security_placeholders():
    facts = issuer_facts()
    result = prepare(facts, snapshot=operating_source())
    baseline = prepare(operating_facts())
    assert result.status == "prepared"
    assert result.quality_status is QualityStatus.PROVISIONAL
    assert result.supported_history_threshold is None
    assert result.forecast == baseline.forecast
    assert result.tax_rate == baseline.tax_rate
    assert [n.value for n in result.nodes] == [n.value for n in baseline.nodes]
    assert result.input_digest != baseline.input_digest
    assert canonical_bytes(result) == canonical_bytes(
        prepare(tuple(reversed(facts)), snapshot=operating_source())
    )


def test_issuer_source_cannot_be_used_with_full_valuation_profile():
    source = operating_source()
    with pytest.raises(ValueError, match="exact operating profile"):
        prepare_automatic_valuation(
            issuer_facts(),
            snapshot=source,
            model_id="fcff_dcf",
            model_version="fcff_dcf-v1",
            policy_id="fcff-policy",
            policy_version="policy-v1",
            data_release_manifest_digest="d" * 64,
        )
    with pytest.raises(ValueError, match="exact operating profile"):
        resolve_annual_history(
            issuer_facts(),
            snapshot=source,
            valuation_timestamp=DECISION,
            profile=valuation_requirements_profile("fcff_dcf"),
        )


@pytest.mark.parametrize(
    "change",
    (
        {"security_id": "OTHER"},
        {"security_scope": "COMMON"},
        {"issuer_id": "FOREIGN"},
        {"quality": QualityStatus.PROVISIONAL},
    ),
)
def test_issuer_operating_path_cannot_select_security_or_unreviewed_facts(change):
    facts = tuple(
        f.model_copy(update=change) if f.normalized_field == "revenue" else f
        for f in issuer_facts()
    )
    result = prepare(facts, snapshot=operating_source())
    assert result.status == "abstained"
    assert "revenue" in result.missing_evidence
    assert not result.nodes


@pytest.mark.parametrize(
    "change",
    (
        {"accession_number": "0000000001-25-000002"},
        {"available_at": datetime(2026, 1, 1, tzinfo=UTC)},
        {"is_amendment": True},
    ),
)
def test_issuer_operating_facts_must_match_their_original_source(change):
    facts = tuple(
        f.model_copy(update=change) if f.normalized_field == "revenue" else f
        for f in issuer_facts()
    )
    result = prepare(facts, snapshot=operating_source())
    assert result.status == "abstained"
    assert "OPERATING_ORIGINAL_SOURCE_MISMATCH" in result.issue_codes
    assert not result.nodes


@pytest.mark.parametrize(
    "change",
    (
        {"source_url": "https://example.com/other.xml"},
        {"accession_number": "0000000001-25-000002"},
        {"available_at": datetime(2026, 1, 1, tzinfo=UTC)},
    ),
)
def test_issuer_operating_provenance_cannot_swap_original_metadata(change):
    facts = tuple(
        f.model_copy(update={"source": f.source.model_copy(update=change)})
        if f.normalized_field == "revenue"
        else f
        for f in issuer_facts()
    )
    result = prepare(facts, snapshot=operating_source())
    assert result.status == "abstained"
    assert "OPERATING_ORIGINAL_SOURCE_MISMATCH" in result.issue_codes
    assert not result.nodes
