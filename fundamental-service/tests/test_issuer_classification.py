from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import UTC, date, datetime

import pytest

from fundamental_service.issuer_classification import (
    IssuerClassificationAttributeV1,
    IssuerClassificationObservationV1,
    IssuerClassificationRequestV1,
    reproduce_issuer_classification,
)
from fundamental_service.sec_classification_source import (
    SEC_CLASSIFICATION_PROFILE,
    SEC_CLASSIFICATION_SOURCE,
    SEC_CLASSIFICATION_TERMS,
    SecSubmissionClassificationProvider,
)
from fundamental_service.serialization import canonical_bytes, sha256_digest
from fundamental_service.snapshots import SnapshotError
from fundamental_service.source_evidence import RetainedSourceV1, SourceArtifactV1

CIK = "0000320193"
ACCESSION = "0000320193-24-000123"
ACCEPTED = datetime(2024, 11, 1, 10, 1, 36, tzinfo=UTC)
CAPTURED = datetime(2026, 11, 13, tzinfo=UTC)
DECISION = datetime(2025, 1, 1, tzinfo=UTC)


def sec_submission(
    *,
    cik: str = CIK,
    accession: str = ACCESSION,
    accepted: str = "20241101060136",
    period: str = "20240928",
    form: str = "10-K",
    sic: str | None = "ELECTRONIC COMPUTERS [3571]",
    state: str | None = "CA",
) -> RetainedSourceV1:
    fields = [
        f"ACCESSION NUMBER:\t\t{accession}",
        f"CONFORMED SUBMISSION TYPE:\t{form}",
        f"CONFORMED PERIOD OF REPORT:\t{period}",
        "FILED AS OF DATE:\t\t20241101",
        "DATE AS OF CHANGE:\t\t20241101",
        "",
        "FILER:",
        "",
        "\tCOMPANY DATA:",
        "\t\tCOMPANY CONFORMED NAME:\t\t\tExample Inc.",
        f"\t\tCENTRAL INDEX KEY:\t\t{cik}",
    ]
    if sic is not None:
        fields.append(f"\t\tSTANDARD INDUSTRIAL CLASSIFICATION:\t{sic}")
    if state is not None:
        fields.append(f"\t\tSTATE OF INCORPORATION:\t{state}")
    fields.extend(
        [
            "",
            "\tFILING VALUES:",
            f"\t\tFORM TYPE:\t{form}",
        ]
    )
    content = (
        f"<SEC-DOCUMENT>{accession}.txt : 20241101\n"
        f"<SEC-HEADER>{accession}.hdr.sgml : 20241101\n"
        f"<ACCEPTANCE-DATETIME>{accepted}\n"
        + "\n".join(fields)
        + "\n</SEC-HEADER>\n<DOCUMENT>\n"
    ).encode()
    return RetainedSourceV1(
        source_id=SEC_CLASSIFICATION_SOURCE,
        uri=(
            f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/"
            f"{accession.replace('-', '')}/{accession}.txt"
        ),
        source_version=SEC_CLASSIFICATION_PROFILE,
        terms_reference=SEC_CLASSIFICATION_TERMS,
        content=content,
        captured_at=CAPTURED,
    )


def request(**changes) -> IssuerClassificationRequestV1:
    return IssuerClassificationRequestV1.model_validate(
        {
            "issuer_id": CIK,
            "accession_number": ACCESSION,
            "report_period_end": date(2024, 9, 28),
            "valuation_at": DECISION,
            **changes,
        }
    )


def test_sec_original_header_reproduces_pit_claims_with_exact_provenance():
    original = sec_submission()
    provider = SecSubmissionClassificationProvider()
    first = reproduce_issuer_classification(
        provider, request=request(), sources=(original,)
    )
    repeated = reproduce_issuer_classification(
        provider, request=request(), sources=(original,), expected=first
    )

    assert first.status == "matched"
    assert first == repeated
    observation = first.observation
    assert observation is not None
    attributes = {item.role: item for item in observation.attributes}
    assert observation.provider_id == "sec-submission-header"
    assert observation.issuer_id == CIK
    assert observation.accession_number == ACCESSION
    assert observation.form == "10-K"
    assert observation.accepted_at == ACCEPTED
    assert observation.available_at == ACCEPTED
    assert attributes["industry_code"].scheme == "sec-sic-v1"
    assert attributes["industry_code"].value == "3571"
    assert attributes["industry_code"].source_value == "ELECTRONIC COMPUTERS [3571]"
    assert attributes["incorporation_jurisdiction"].value == "CA"
    source_hash = hashlib.sha256(original.content).hexdigest()
    assert observation.artifacts[0].content_sha256 == source_hash
    assert all(item.source_sha256 == source_hash for item in observation.attributes)
    assert first.input_digest == sha256_digest(
        {
            "protocol": first.protocol,
            "request": first.request,
            "provider_id": first.provider_id,
            "source_artifacts": first.source_artifacts,
        }
    )


@pytest.mark.parametrize(
    "changes,code",
    [
        ({"issuer_id": "0000320194"}, "ISSUER_CLASSIFICATION_ISSUER_MISMATCH"),
        (
            {"accession_number": "0000320193-24-000124"},
            "ISSUER_CLASSIFICATION_ACCESSION_MISMATCH",
        ),
        (
            {"report_period_end": date(2024, 9, 29)},
            "ISSUER_CLASSIFICATION_PERIOD_MISMATCH",
        ),
        (
            {"valuation_at": datetime(2024, 10, 1, tzinfo=UTC)},
            "ISSUER_CLASSIFICATION_NOT_AVAILABLE",
        ),
    ],
)
def test_sec_original_header_retains_scope_and_point_in_time_refusals(changes, code):
    result = reproduce_issuer_classification(
        SecSubmissionClassificationProvider(),
        request=request(**changes),
        sources=(sec_submission(),),
    )
    assert result.status == "refused"
    assert result.issue_codes == (code,)
    assert result.observation is not None


@pytest.mark.parametrize(
    "source_changes,code",
    [
        ({"form": "10-K/A"}, "ISSUER_CLASSIFICATION_AMENDMENT_UNSUPPORTED"),
        ({"sic": None}, "ISSUER_CLASSIFICATION_INDUSTRY_MISSING"),
        ({"state": None}, "ISSUER_CLASSIFICATION_JURISDICTION_MISSING"),
        ({"cik": "0000320194"}, "ISSUER_CLASSIFICATION_ISSUER_MISMATCH"),
    ],
)
def test_sec_adapter_retains_incomplete_original_claims(source_changes, code):
    result = reproduce_issuer_classification(
        SecSubmissionClassificationProvider(),
        request=request(),
        sources=(sec_submission(**source_changes),),
    )
    assert result.status == "refused"
    assert code in result.issue_codes
    assert result.observation is not None


@pytest.mark.parametrize(
    "mutate",
    [
        lambda source: replace(source, content=b"not a submission"),
        lambda source: replace(source, source_version="sec-current-sic"),
        lambda source: replace(source, uri="https://example.test/source"),
        lambda source: replace(
            source, content=source.content.replace(b"3571", b"357x")
        ),
    ],
)
def test_sec_adapter_refuses_changed_or_noncanonical_originals(mutate):
    original = mutate(sec_submission())
    result = reproduce_issuer_classification(
        SecSubmissionClassificationProvider(),
        request=request(),
        sources=(original,),
    )
    assert result.status == "refused"
    assert result.observation is None
    assert "ISSUER_CLASSIFICATION_REPRODUCTION_FAILED" in result.issue_codes
    assert (
        result.source_artifacts[0].content_sha256
        == hashlib.sha256(original.content).hexdigest()
    )


def test_replay_detects_changed_source_bytes():
    provider = SecSubmissionClassificationProvider()
    original = sec_submission()
    first = reproduce_issuer_classification(
        provider, request=request(), sources=(original,)
    )
    changed = replace(original, content=original.content.replace(b"3571", b"3572"))
    with pytest.raises(SnapshotError) as error:
        reproduce_issuer_classification(
            provider, request=request(), sources=(changed,), expected=first
        )
    assert error.value.code == "ISSUER_CLASSIFICATION_REPLAY_MISMATCH"


class AlternateJsonClassificationProvider:
    provider_id = "alternate-json-classification"

    def reproduce_classification(self, *, sources):
        source = sources[0]
        payload = json.loads(source.content)
        digest = hashlib.sha256(source.content).hexdigest()
        artifact = SourceArtifactV1(
            source_id=source.source_id,
            uri=source.uri,
            source_version=source.source_version,
            terms_reference=source.terms_reference,
            content_sha256=digest,
            captured_at=source.captured_at,
        )
        attributes = tuple(
            sorted(
                (
                    IssuerClassificationAttributeV1(
                        role="incorporation_jurisdiction",
                        scheme="alternate-country-v1",
                        value=payload["country"],
                        source_value=payload["country"],
                        locator="country",
                        source_sha256=digest,
                    ),
                    IssuerClassificationAttributeV1(
                        role="industry_code",
                        scheme="alternate-industry-v1",
                        value=payload["sic"],
                        source_value=payload["sic"],
                        locator="sic",
                        source_sha256=digest,
                    ),
                ),
                key=lambda item: item.role,
            )
        )
        return IssuerClassificationObservationV1.build(
            provider_id=self.provider_id,
            source_version="alternate-json-v1",
            issuer_id=payload["cik"],
            accession_number=payload["accession"],
            form="10-K",
            report_period_end=date.fromisoformat(payload["period_end"]),
            accepted_at=ACCEPTED,
            available_at=ACCEPTED,
            captured_at=source.captured_at,
            artifacts=(artifact,),
            attributes=attributes,
        )


def test_independent_provider_uses_same_contract_and_deterministic_selection():
    payload = {
        "cik": CIK,
        "accession": ACCESSION,
        "period_end": "2024-09-28",
        "country": "US",
        "sic": "3571",
    }
    source = RetainedSourceV1(
        source_id="alternate-classification-source",
        uri="https://example.test/issuer/0000320193/2024",
        source_version="json-v1",
        terms_reference="https://example.test/terms",
        content=canonical_bytes(payload),
        captured_at=CAPTURED,
    )
    provider = AlternateJsonClassificationProvider()
    first = reproduce_issuer_classification(
        provider, request=request(), sources=(source,)
    )
    second = reproduce_issuer_classification(
        provider, request=request(), sources=(source,), expected=first
    )
    assert first == second
    assert first.status == "matched"
    assert first.observation is not None
    assert first.observation.attributes[0].scheme == "alternate-country-v1"


def test_provider_cannot_omit_original_source_bytes_or_substitute_its_identity():
    provider = AlternateJsonClassificationProvider()
    source = RetainedSourceV1(
        source_id="alternate-classification-source",
        uri="https://example.test/issuer/0000320193/2024",
        source_version="json-v1",
        terms_reference="https://example.test/terms",
        content=canonical_bytes(
            {
                "cik": CIK,
                "accession": ACCESSION,
                "period_end": "2024-09-28",
                "country": "US",
                "sic": "3571",
            }
        ),
        captured_at=CAPTURED,
    )
    first = reproduce_issuer_classification(
        provider, request=request(), sources=(source,)
    )
    changed = replace(source, content=source.content + b" ")
    with pytest.raises(SnapshotError) as error:
        reproduce_issuer_classification(
            provider, request=request(), sources=(changed,), expected=first
        )
    assert error.value.code == "ISSUER_CLASSIFICATION_REPLAY_MISMATCH"
