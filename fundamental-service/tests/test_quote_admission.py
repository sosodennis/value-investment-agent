"""Quote source reproduction and permission are independent release gates."""

from dataclasses import replace
from datetime import timedelta
from hashlib import sha256
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from fundamental_service.contracts import ValuationEvidenceReadRequestV1
from fundamental_service.data_releases import (
    ArtifactRefV1,
    DataReleaseError,
    DataReleaseManifestV1,
)
from fundamental_service.equity_dilution import DilutionError
from fundamental_service.free_source_policy import free_market_source_policy
from fundamental_service.quote_admission import (
    QUOTE_ADMISSION_ROLE,
    QUOTE_TERMS_ROLE,
    QuoteAdmissionV1,
    admit_quote_source,
)
from fundamental_service.quote_sources import default_quote_providers
from fundamental_service.operations import ServiceError
from fundamental_service.replay import ArtifactStore
from fundamental_service.serialization import canonical_bytes, sha256_digest
from fundamental_service.source_evidence import RetainedSourceV1
from equity_award_fixtures import quote_source_bytes
from test_preparation_runner import _fixture, _reviewed_candidate


def _inputs(fixture):
    ref = next(
        r for r in fixture.manifest.artifact_refs if r.role == QUOTE_ADMISSION_ROLE
    )
    admission = QuoteAdmissionV1.model_validate_json(
        fixture.artifacts.read(ref.artifact_id)
    )
    terms = tuple(
        RetainedSourceV1(
            **item.model_dump(exclude={"content_sha256"}),
            content=fixture.artifacts.read(
                next(
                    r.artifact_id
                    for r in fixture.manifest.artifact_refs
                    if r.role == QUOTE_TERMS_ROLE
                    and r.content_hash == item.content_sha256
                )
            ),
        )
        for item in admission.request.terms_artifacts
    )
    return dict(
        quote=fixture.dilution.quote,
        raw=quote_source_bytes(fixture.snapshot),
        providers=default_quote_providers(),
        terms=terms,
        policy=fixture.application.source_use_policy,
        valuation_at=fixture.snapshot.valuation_timestamp,
    )


def _manifest(fixture, refs):
    payload = fixture.manifest.model_dump(exclude={"manifest_digest"})
    payload["artifact_refs"] = tuple(refs)
    fixture.manifest = DataReleaseManifestV1(
        **payload, manifest_digest=sha256_digest(payload)
    )
    fixture.metadata.get_data_release_manifest = lambda digest: (
        fixture.manifest if digest == fixture.manifest.manifest_digest else None
    )


def _decision(fixture, admission):
    raw = canonical_bytes(admission)
    identifier = "quote-admission:" + sha256(raw).hexdigest()
    fixture.artifacts.put_bytes_with_receipt(
        identifier, raw, media_type="application/json"
    )
    _manifest(
        fixture,
        (
            r.model_copy(
                update={
                    "artifact_id": identifier,
                    "content_hash": sha256(raw).hexdigest(),
                }
            )
            if r.role == QUOTE_ADMISSION_ROLE
            else r
            for r in fixture.manifest.artifact_refs
        ),
    )


def _consume(fixture, consumer):
    if consumer == "canary":
        candidate, canary = _reviewed_candidate(fixture)
        canary.validate(candidate.manifest, candidate.verification)
    else:
        fixture.application.prepare_valuation(
            ValuationEvidenceReadRequestV1(
                contract_version="fundamental.v1",
                snapshot_id=fixture.snapshot.snapshot_id,
                data_release_manifest_digest=fixture.manifest.manifest_digest,
                model_id="fcff_dcf",
            )
        )


def test_quote_admission_reopens_without_writes_or_changed_identity(tmp_path):
    fixture = _fixture(tmp_path)
    inputs = _inputs(fixture)
    first = admit_quote_source(**inputs)
    assert first.status == "admitted" and first.source_check.required_notices
    store = ArtifactStore(tmp_path / "quote-decisions")
    receipt = store.put_with_receipt(first.output_digest, first)
    before = tuple(
        (p.name, p.read_bytes(), p.stat().st_mtime_ns)
        for p in sorted(tmp_path.rglob("*"))
        if p.is_file()
    )
    for _ in range(2):
        repeated = admit_quote_source(**inputs, expected=first)
        result = ArtifactStore(tmp_path / "quote-decisions").put_with_receipt(
            first.output_digest, repeated
        )
        assert not result.wrote and result.artifact == receipt.artifact
    assert before == tuple(
        (p.name, p.read_bytes(), p.stat().st_mtime_ns)
        for p in sorted(tmp_path.rglob("*"))
        if p.is_file()
    )


def test_installed_nasdaq_parser_and_default_policy_do_not_grant_quote_use(tmp_path):
    inputs = _inputs(_fixture(tmp_path))
    inputs["policy"] = free_market_source_policy()
    result = admit_quote_source(**inputs)
    assert result.status == "refused"
    assert result.issue_codes == ("SOURCE_USE_POLICY_MISSING",)
    assert result.request.quote.price == 10


@pytest.mark.parametrize(
    "change,code",
    [
        ("missing_terms", "SOURCE_USE_TERMS_MISSING"),
        ("changed_terms", "SOURCE_USE_TERMS_CHANGED"),
        ("ambiguous_terms", "SOURCE_USE_TERMS_AMBIGUOUS"),
        ("purpose", "SOURCE_USE_PURPOSE_UNSUPPORTED"),
        ("future", "SOURCE_NOT_AVAILABLE_AT_VALUATION"),
        ("future_terms", "SOURCE_USE_TERMS_NOT_AVAILABLE_AT_VALUATION"),
        ("changed_source", "DILUTION_QUOTE_SOURCE_MISMATCH"),
        ("provider", "DILUTION_QUOTE_SOURCE_PROFILE_UNSUPPORTED"),
    ],
)
def test_quote_admission_retains_source_permission_and_time_failures(
    tmp_path, change, code
):
    inputs = _inputs(_fixture(tmp_path))
    if change == "missing_terms":
        inputs["terms"] = ()
    elif change == "changed_terms":
        inputs["terms"] = (replace(inputs["terms"][0], content=b"changed permission"),)
    elif change == "ambiguous_terms":
        inputs["terms"] += (
            replace(inputs["terms"][0], content=b"conflicting permission"),
        )
    elif change == "purpose":
        inputs["intended_use"] = "raw_data_redistribution"
    elif change == "future":
        inputs["valuation_at"] -= timedelta(seconds=1)
    elif change == "future_terms":
        inputs["terms"] = (
            replace(
                inputs["terms"][0],
                captured_at=inputs["valuation_at"] + timedelta(seconds=1),
            ),
        )
    elif change == "changed_source":
        inputs["raw"] += b"changed"
    else:
        inputs["providers"] = ()
    result = admit_quote_source(**inputs)
    assert result.status == "refused" and code in result.issue_codes
    assert admit_quote_source(**inputs, expected=result) == result


def test_corrupt_quote_inputs_have_their_own_identity(tmp_path):
    inputs = _inputs(_fixture(tmp_path))
    first = admit_quote_source(**inputs)
    inputs["raw"] += b"corrupt"
    failure = admit_quote_source(**inputs)
    assert first.input_digest != failure.input_digest
    assert failure.request.source_content_sha256 == sha256(inputs["raw"]).hexdigest()
    with pytest.raises(DilutionError, match="differs from reproduced"):
        admit_quote_source(**inputs, expected=first)


def test_release_can_reuse_a_quote_with_distinct_valuation_admissions(tmp_path):
    from test_equity_award_evidence import _load

    fixture = _fixture(tmp_path)
    inputs = _inputs(fixture)
    later = admit_quote_source(
        **(inputs | {"valuation_at": inputs["valuation_at"] + timedelta(seconds=1)})
    )
    raw = canonical_bytes(later)
    digest = sha256(raw).hexdigest()
    fixture.artifacts.put_bytes_with_receipt(digest, raw, media_type="application/json")
    _manifest(
        fixture,
        (
            *fixture.manifest.artifact_refs,
            ArtifactRefV1(
                artifact_id=digest,
                content_hash=digest,
                media_type="application/json",
                role=QUOTE_ADMISSION_ROLE,
            ),
        ),
    )
    assert _load(fixture) == fixture.dilution


@pytest.mark.parametrize(
    "field", ["input_digest", "output_digest", "issue_codes", "status"]
)
def test_quote_admission_rejects_inconsistent_serialized_decisions(tmp_path, field):
    result = admit_quote_source(**_inputs(_fixture(tmp_path)))
    payload = result.model_dump()
    payload[field] = (
        "0" * 64
        if field.endswith("digest")
        else ("forged",)
        if field == "issue_codes"
        else "refused"
    )
    with pytest.raises(ValidationError):
        QuoteAdmissionV1.model_validate(payload)


@pytest.mark.parametrize("consumer", ["serving", "canary"])
@pytest.mark.parametrize(
    "change,code",
    [
        ("missing", "DILUTION_QUOTE_ADMISSION_MISSING"),
        ("no_policy", "DILUTION_QUOTE_USE_POLICY_UNAVAILABLE"),
        ("changed_policy", "DILUTION_QUOTE_ADMISSION_REPLAY_MISMATCH"),
        ("refused", "DILUTION_QUOTE_ADMISSION_REFUSED"),
        ("wrong_time", "DILUTION_QUOTE_ADMISSION_SCOPE_MISMATCH"),
        ("wrong_purpose", "DILUTION_QUOTE_ADMISSION_SCOPE_MISMATCH"),
        ("missing_terms", "DILUTION_QUOTE_TERMS_MISSING"),
        ("duplicate", "DILUTION_QUOTE_ADMISSION_AMBIGUOUS"),
    ],
)
def test_signed_release_cannot_replace_quote_permission(
    tmp_path, consumer, change, code
):
    fixture = _fixture(tmp_path, released=False)
    inputs = _inputs(fixture)
    if change in {"no_policy", "changed_policy", "refused"}:
        policy = None if change == "no_policy" else free_market_source_policy()
        fixture.application = replace(fixture.application, source_use_policy=policy)
        if change == "refused":
            _decision(fixture, admit_quote_source(**(inputs | {"policy": policy})))
    elif change in {"wrong_time", "wrong_purpose"}:
        alteration = (
            {"valuation_at": inputs["valuation_at"] + timedelta(seconds=1)}
            if change == "wrong_time"
            else {"intended_use": "derived_valuation_display"}
        )
        _decision(fixture, admit_quote_source(**(inputs | alteration)))
    else:
        refs = fixture.manifest.artifact_refs
        role = QUOTE_TERMS_ROLE if change == "missing_terms" else QUOTE_ADMISSION_ROLE
        if change == "duplicate":
            existing = next(r for r in refs if r.role == role)
            fixture.artifacts.put_bytes_with_receipt(
                "duplicate-quote-admission",
                fixture.artifacts.read(existing.artifact_id),
                media_type="application/json",
            )
            refs = (
                *refs,
                existing.model_copy(
                    update={"artifact_id": "duplicate-quote-admission"}
                ),
            )
        else:
            refs = tuple(r for r in refs if r.role != role)
        _manifest(fixture, refs)
    with pytest.raises((ServiceError, DataReleaseError)) as error:
        _consume(fixture, consumer)
    assert error.value.code == code
    assert fixture.state.active is None and fixture.state.publications == 0


@pytest.mark.parametrize(
    "change,code",
    [
        ("hash", "DILUTION_QUOTE_ADMISSION_ARTIFACT_MISMATCH"),
        ("noncanonical", "DILUTION_QUOTE_ADMISSION_NONCANONICAL"),
        ("terms", "DILUTION_QUOTE_TERMS_MISMATCH"),
    ],
)
def test_quote_admission_rejects_changed_retained_artifacts(tmp_path, change, code):
    from test_equity_award_evidence import _load

    fixture = _fixture(tmp_path)
    role = QUOTE_TERMS_ROLE if change == "terms" else QUOTE_ADMISSION_ROLE
    ref = next(r for r in fixture.manifest.artifact_refs if r.role == role)
    raw = fixture.artifacts.read(ref.artifact_id) + b"\n"
    reader = SimpleNamespace(
        read=lambda name: raw
        if name == ref.artifact_id
        else fixture.artifacts.read(name)
    )
    if change == "noncanonical":
        _manifest(
            fixture,
            tuple(
                r.model_copy(update={"content_hash": sha256(raw).hexdigest()})
                if r == ref
                else r
                for r in fixture.manifest.artifact_refs
            ),
        )
    with pytest.raises(DilutionError) as error:
        _load(fixture, artifacts=reader)
    assert error.value.code == code
