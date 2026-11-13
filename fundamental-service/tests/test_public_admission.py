from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace

import pytest

from fundamental_service.contracts import SourceRole
from fundamental_service.damodaran_source import DamodaranReferenceProvider
from fundamental_service.public_acquisition import PublicSourceAcquisitionRequestV1
from fundamental_service.public_admission import (
    PublicSourceAdmission,
    PublicSourceAdmissionRequestV1,
)
from fundamental_service.public_source import PublicSourceAdapter
from fundamental_service.replay import ArtifactStore
from fundamental_service.snapshots import CapturedSource, SnapshotError
from fundamental_service.source_admission_evidence import load_release_source_admissions
from fundamental_service.source_capture import SourceCaptureRequest
from test_public_acquisition import acquisition, inventory
from test_public_source import FakeResponse
from test_source_admission import CAPTURE, METRIC, _reference_policy, _source, _terms


def admission_fixture(tmp_path, *, at=CAPTURE, artifacts=None, policy=None):
    artifacts = artifacts or ArtifactStore(tmp_path / "artifacts")
    policy = policy or _reference_policy()
    originals = (_source(), _terms())
    requests = tuple(
        PublicSourceAcquisitionRequestV1(
            source_id=source.source_id,
            uri=source.uri,
            source_profile=source.source_version,
            terms_reference=source.terms_reference,
            valuation_timestamp=at,
        )
        for source in originals
    )

    class Capture:
        def __init__(self):
            self.calls = []
            self.sources = {
                source.uri: CapturedSource(
                    source_id=source.source_id,
                    uri=source.uri,
                    role=SourceRole.REFERENCE,
                    content=source.content,
                    media_type="application/octet-stream",
                    http_status=200,
                    captured_at=at - timedelta(hours=1),
                    available_at=at - timedelta(hours=1),
                )
                for source in originals
            }
            self.errors = {}

        def validate_capture(self, source_id, uri):
            request = next(item for item in requests if item.uri == uri)
            return SourceCaptureRequest(source_id, uri, request.terms_reference)

        def capture(self, source_id, uri):
            self.calls.append(uri)
            if uri in self.errors:
                raise self.errors[uri]
            return self.sources[uri]

    capture = Capture()
    acquired = acquisition(tmp_path / "public", capture, artifacts=artifacts)
    request = PublicSourceAdmissionRequestV1(
        kind="reference",
        provider_id="damodaran-public-aggregates",
        metric_id=METRIC,
        valuation_at=at,
        policy_version=policy.policy_version,
        policy_digest=policy.digest,
        source_request_digests=(requests[0].digest,),
        terms_request_digests=(requests[1].digest,),
    )
    service = PublicSourceAdmission(
        acquisitions=acquired,
        artifacts=artifacts,
        policy=policy,
        reference_providers=(DamodaranReferenceProvider(),),
    )

    def captures():
        return tuple(
            acquired.read(acquired.execute(item).artifact.artifact_id)
            for item in requests
        )

    return SimpleNamespace(
        capture=capture,
        acquisition=acquired,
        service=service,
        request=request,
        requests=requests,
        captures=captures,
        policy=policy,
        artifacts=artifacts,
    )


def test_admission_publishes_release_lineage_and_reopened_repeat_writes_nothing(
    tmp_path,
):
    fixture = admission_fixture(tmp_path)
    captures = fixture.captures()
    result, first = fixture.service.execute(fixture.request, captures)
    assert result.admission.status == "admitted" and not result.issue_codes
    assert first.wrote and len(result.release_refs) == 3
    assert result.admission.source_checks[0].required_notices
    assert any(row.missing_reason for row in result.admission.vintage.rows)
    before = inventory(tmp_path)
    reopened = admission_fixture(tmp_path)
    repeated, second = reopened.service.execute(reopened.request, reopened.captures())
    assert result == repeated and first.artifact == second.artifact and not second.wrote
    assert not reopened.capture.calls and inventory(tmp_path) == before

    from test_preparation_runner import _fixture
    from fundamental_service.data_releases import DataReleaseManifestV1
    from fundamental_service.serialization import sha256_digest

    baseline = _fixture(tmp_path / "release")
    payload = baseline.manifest.model_dump(exclude={"manifest_digest"})
    payload["artifact_refs"] = (*baseline.manifest.artifact_refs, *result.release_refs)
    manifest = DataReleaseManifestV1(**payload, manifest_digest=sha256_digest(payload))
    assert load_release_source_admissions(
        manifest,
        artifacts=fixture.artifacts,
        policy=fixture.policy,
        macro_providers=(),
        reference_providers=(DamodaranReferenceProvider(),),
    ) == (result.admission,)


@pytest.mark.parametrize(
    "failure,code",
    [
        ("terms_missing", "SOURCE_USE_TERMS_MISSING"),
        ("terms_changed", "SOURCE_USE_TERMS_CHANGED"),
        ("late", "SOURCE_NOT_AVAILABLE_AT_VALUATION"),
        ("schema", "SOURCE_REPRODUCTION_FAILED"),
        ("failed", "SOURCE_ADMISSION_CAPTURE_FAILED"),
        ("policy", "SOURCE_ADMISSION_POLICY_MISMATCH"),
        ("provider", "SOURCE_ADMISSION_PROVIDER_UNAVAILABLE"),
        ("ambiguous", "SOURCE_ADMISSION_PROVIDER_UNAVAILABLE"),
        ("raw", "SOURCE_USE_PURPOSE_UNSUPPORTED"),
    ],
)
def test_admission_retains_failures_without_authorizing_release(
    tmp_path, failure, code
):
    fixture = admission_fixture(tmp_path)
    request = fixture.request
    source_uri, terms_uri = (item.uri for item in fixture.requests)
    if failure == "terms_missing":
        request = request.model_copy(update={"terms_request_digests": ()})
    if failure in {"terms_changed", "schema"}:
        uri = terms_uri if failure == "terms_changed" else source_uri
        fixture.capture.sources[uri] = replace(
            fixture.capture.sources[uri], content=b"changed"
        )
    if failure == "late":
        fixture.capture.sources[terms_uri] = replace(
            fixture.capture.sources[terms_uri],
            captured_at=CAPTURE + timedelta(hours=1),
            available_at=CAPTURE + timedelta(hours=1),
        )
    if failure == "failed":
        fixture.capture.errors[source_uri] = SnapshotError(
            "SOURCE_NOT_FOUND", "missing"
        )
    if failure == "policy":
        request = request.model_copy(update={"policy_digest": "0" * 64})
    if failure == "provider":
        request = request.model_copy(update={"provider_id": "uninstalled"})
    if failure == "ambiguous":
        fixture.service = PublicSourceAdmission(
            acquisitions=fixture.acquisition,
            artifacts=fixture.artifacts,
            policy=fixture.policy,
            reference_providers=(
                DamodaranReferenceProvider(),
                DamodaranReferenceProvider(),
            ),
        )
    if failure == "raw":
        request = request.model_copy(update={"intended_use": "raw_data_redistribution"})
    captures = fixture.captures()
    result, first = fixture.service.execute(request, captures)
    assert code in result.issue_codes and not result.release_refs
    assert len(result.acquisition_refs) == (1 if failure == "terms_missing" else 2)
    before = inventory(tmp_path)
    repeated, second = fixture.service.execute(request, captures)
    assert result == repeated and first.artifact == second.artifact and not second.wrote
    assert inventory(tmp_path) == before


def test_admission_concurrency_and_resume_after_intermediate_publication(
    tmp_path, monkeypatch
):
    fixture = admission_fixture(tmp_path)
    captures = fixture.captures()
    original = fixture.artifacts.put_with_receipt

    def interrupted(artifact_id, *args, **kwargs):
        receipt = original(artifact_id, *args, **kwargs)
        if artifact_id.startswith("source-admission:"):
            raise RuntimeError("after admission publication")
        return receipt

    monkeypatch.setattr(fixture.artifacts, "put_with_receipt", interrupted)
    with pytest.raises(RuntimeError, match="after admission"):
        fixture.service.execute(fixture.request, captures)
    monkeypatch.setattr(fixture.artifacts, "put_with_receipt", original)
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(
            pool.map(
                lambda _: fixture.service.execute(fixture.request, captures), range(3)
            )
        )
    assert len({receipt.artifact.content_hash for _, receipt in results}) == 1
    assert sum(receipt.wrote for _, receipt in results) == 1
    assert len(fixture.capture.calls) == 2


def test_admission_refuses_corrupted_original_without_repair_or_download(tmp_path):
    fixture = admission_fixture(tmp_path)
    captures = fixture.captures()
    fixture.service.execute(fixture.request, captures)
    source = captures[0].source
    paths = [
        path for path in (tmp_path / "public" / "content").rglob("*") if path.is_file()
    ]
    path = next(path for path in paths if source.content_sha256 in path.name)
    path.write_bytes(b"tampered")
    before = inventory(tmp_path)
    with pytest.raises(SnapshotError):
        fixture.service.execute(fixture.request, captures)
    assert len(fixture.capture.calls) == 2 and inventory(tmp_path) == before


def test_macro_provider_is_replaceable_without_admission_or_runner_changes(tmp_path):
    from hashlib import sha256
    from fundamental_service.source_admission import SourceUsePolicyV1, SourceUseRuleV1
    from test_public_source import AlternativeRateProvider

    fixture = admission_fixture(tmp_path)
    uri = fixture.requests[0].uri
    fixture.capture.sources[uri] = replace(
        fixture.capture.sources[uri], content=b"2025-01-01,4.125"
    )
    terms_uri = fixture.requests[1].uri
    rule = SourceUseRuleV1.model_validate(
        {
            **fixture.policy.rules[0].model_dump(),
            "rule_id": "alternative-rate",
            "provider_id": "alternative-rate-provider",
            "metric_id": "test.policy_rate",
            "population": "test.policy_rate",
            "terms": (
                {
                    "uri": terms_uri,
                    "content_sha256": sha256(_terms().content).hexdigest(),
                },
            ),
        }
    )
    policy = SourceUsePolicyV1(policy_version="alternative-test-v1", rules=(rule,))
    request = PublicSourceAdmissionRequestV1.model_validate(
        {
            **fixture.request.model_dump(),
            "kind": "macro",
            "metric_id": "test.policy_rate",
            "provider_id": "alternative-rate-provider",
            "policy_version": policy.policy_version,
            "policy_digest": policy.digest,
        }
    )
    service = PublicSourceAdmission(
        acquisitions=fixture.acquisition,
        artifacts=fixture.artifacts,
        policy=policy,
        macro_providers=(AlternativeRateProvider(),),
    )
    result, _ = service.execute(request, fixture.captures())
    assert result.admission.status == "admitted" and not result.issue_codes
    assert str(result.admission.vintage.observations[0].value) == "4.125"


@pytest.mark.parametrize("bind_release", [False, True])
def test_ordinary_preparation_pins_admission_before_formal_composer(
    tmp_path, bind_release
):
    from fundamental_service.data_releases import DataReleaseManifestV1
    from fundamental_service.preparation_runner import SourcePreparationPlanV2
    from fundamental_service.serialization import sha256_digest
    from test_preparation_runner import VALUATION_TIME, _fixture, _reader, _run, _runner

    fixture = _fixture(tmp_path)
    baseline = _reader(fixture, _run(_runner(fixture), fixture.plan))
    from quote_provider_fixtures import publish_synthetic_quote_admission
    from equity_award_fixtures import quote_source_bytes
    from fundamental_service.quote_admission import (
        QUOTE_ADMISSION_ROLE,
        QUOTE_TERMS_ROLE,
    )

    policy, quote_refs = publish_synthetic_quote_admission(
        fixture.dilution.quote,
        quote_source_bytes(fixture.snapshot),
        valuation_at=VALUATION_TIME,
        artifacts=fixture.artifacts,
        base_policy=_reference_policy(),
    )
    payload = fixture.manifest.model_dump(exclude={"manifest_digest"})
    payload["artifact_refs"] = (
        tuple(
            ref
            for ref in fixture.manifest.artifact_refs
            if ref.role not in {QUOTE_ADMISSION_ROLE, QUOTE_TERMS_ROLE}
        )
        + quote_refs
    )
    fixture.manifest = DataReleaseManifestV1(
        **payload, manifest_digest=sha256_digest(payload)
    )
    admitted = admission_fixture(
        tmp_path / "public-source",
        at=VALUATION_TIME,
        artifacts=fixture.artifacts,
        policy=policy,
    )
    plan = SourcePreparationPlanV2.model_validate(
        {
            **fixture.plan.model_dump(),
            "public_sources": admitted.requests,
            "source_admissions": (admitted.request,),
        }
    )
    admission, _ = admitted.service.execute(admitted.request, admitted.captures())
    fixture.application = replace(
        fixture.application, source_use_policy=admitted.policy
    )
    if bind_release:
        payload = fixture.manifest.model_dump(exclude={"manifest_digest"})
        payload["artifact_refs"] = (
            *fixture.manifest.artifact_refs,
            *admission.release_refs,
        )
        manifest = DataReleaseManifestV1(
            **payload, manifest_digest=sha256_digest(payload)
        )
        fixture.state.active = fixture.active.model_copy(
            update={
                "manifest": manifest,
                "active": fixture.active.active.model_copy(
                    update={
                        "manifest_digest": manifest.manifest_digest,
                    }
                ),
            }
        )
        fixture.metadata.get_data_release_manifest = (
            lambda digest: manifest if digest == manifest.manifest_digest else None
        )
    runner = _runner(
        fixture,
        public_acquisition=admitted.acquisition,
        public_admission=admitted.service,
    )
    receipt = _run(runner, plan)
    result = _reader(fixture, receipt)
    assert result.source_admission_outcomes == (admission,)
    assert admission.digest in receipt.artifact.dependency_hashes
    if bind_release:
        assert result.status == "approval_required"
        assert (
            result.preparation.input.model_version
            == baseline.preparation.input.model_version
        )
        assert (
            result.preparation.input.assumptions
            == baseline.preparation.input.assumptions
        )
        from fundamental_service.contracts import (
            CallerApprovalEnvelopeV1,
            QualityStatus,
        )

        calculated = _reader(
            fixture,
            _run(
                runner,
                plan,
                approval=CallerApprovalEnvelopeV1(
                    input_digest=result.preparation.input.input_digest,
                    decision="approved",
                    caller_id="operator",
                    decided_at=VALUATION_TIME,
                ),
            ),
        )
        assert calculated.status == "calculated"
        assert calculated.calculation.base.per_share_value > 0
        assert calculated.calculation.base.quality_status is QualityStatus.PROVISIONAL
    else:
        assert result.status == "blocked" and result.preparation is None
        assert result.issue_codes == ("SOURCE_ADMISSION_RELEASE_MISMATCH",)
    before = inventory(tmp_path)
    second = _run(runner, plan, correlation="repeat-admission")
    assert receipt.artifact == second.artifact and not second.wrote
    assert inventory(tmp_path) == before and len(admitted.capture.calls) == 2


def test_admission_persistence_survives_postgres_restart_and_empty_store_restore(
    tmp_path,
    recovery_databases,
):
    import asyncio
    from fundamental_service.persistence_recovery import export_backup, restore_backup
    from fundamental_service.metadata import (
        PostgresArtifactStore,
        PostgresContentStore,
        PostgresMetadataStore,
    )
    from fundamental_service.public_acquisition import (
        PostgresPublicCaptureLock,
        PublicSourceAcquisition,
    )
    from fundamental_service.serialization import canonical_bytes

    source_database, target_database = recovery_databases
    fixture = admission_fixture(tmp_path / "setup")

    def wire(database, content_root):
        metadata = PostgresMetadataStore(database, auto_migrate=True)
        metadata.start()
        content = PostgresContentStore(content_root, metadata)
        artifacts = PostgresArtifactStore(metadata, content)
        acquisitions = PublicSourceAcquisition(
            provider=fixture.capture,
            artifacts=artifacts,
            content=content,
            capture_lock=PostgresPublicCaptureLock(metadata),
        )
        service = PublicSourceAdmission(
            acquisitions=acquisitions,
            artifacts=artifacts,
            policy=fixture.policy,
            reference_providers=(DamodaranReferenceProvider(),),
        )
        return metadata, acquisitions, service

    root = tmp_path / "content"
    metadata, acquisitions, service = wire(source_database, root)
    try:
        captures = tuple(
            acquisitions.read(acquisitions.execute(item).artifact.artifact_id)
            for item in fixture.requests
        )
        result, first = service.execute(fixture.request, captures)
        assert result.admission.status == "admitted"
        metadata.close()
        metadata, acquisitions, service = wire(source_database, root)
        before = inventory(root)
        repeated, second = service.execute(fixture.request, captures)
        assert (
            first.artifact == second.artifact
            and not second.wrote
            and result == repeated
        )
        assert inventory(root) == before and len(fixture.capture.calls) == 2
        backup = asyncio.run(
            export_backup(
                source_database,
                root,
                tmp_path / "backup",
                source_revision="1" * 40,
            )
        )
        restored_root = tmp_path / "restored"
        asyncio.run(
            restore_backup(
                target_database,
                restored_root,
                tmp_path / "backup" / backup.manifest_digest,
                manifest_digest=backup.manifest_digest,
            )
        )
        recovered, acquisitions, service = wire(target_database, restored_root)
        try:
            before = inventory(restored_root)
            restored, receipt = service.execute(fixture.request, captures)
            assert canonical_bytes(restored) == canonical_bytes(result)
            assert receipt.artifact == first.artifact and not receipt.wrote
            assert (
                inventory(restored_root) == before and len(fixture.capture.calls) == 2
            )
        finally:
            recovered.close()
    finally:
        metadata.close()


def test_plan_rejects_admission_for_unpinned_capture_or_different_date(tmp_path):
    from fundamental_service.preparation_runner import SourcePreparationPlanV2
    from test_preparation_runner import VALUATION_TIME, _fixture
    from pydantic import ValidationError

    fixture = _fixture(tmp_path)
    admitted = admission_fixture(tmp_path / "public", at=VALUATION_TIME)
    for requests, admission in (
        ((), admitted.request),
        (
            admitted.requests,
            admitted.request.model_copy(update={"valuation_at": CAPTURE}),
        ),
    ):
        with pytest.raises(ValidationError, match="pin plan captures and date"):
            SourcePreparationPlanV2.model_validate(
                {
                    **fixture.plan.model_dump(),
                    "public_sources": requests,
                    "source_admissions": (admission,),
                }
            )


@pytest.mark.parametrize(
    "source_id,uri",
    [
        (
            "damodaran-use-terms",
            "https://pages.stern.nyu.edu/~adamodar/New_Home_Page/datahistory.html",
        ),
        ("bea-citation-terms", "https://www.bea.gov/help/guidelines-for-citing-bea"),
        (
            "us-government-works-terms",
            "https://www.govinfo.gov/content/pkg/USCODE-2024-title17/html/USCODE-2024-title17-chap1-sec105.htm",
        ),
        ("new-york-fed-use-terms", "https://www.newyorkfed.org/privacy/termsofuse"),
    ],
)
def test_terms_capture_uses_exact_registered_uri_and_actual_availability(
    source_id, uri
):
    calls = []
    adapter = PublicSourceAdapter(
        user_agent="test test@example.com",
        min_interval_seconds=0,
        opener=lambda *_a, **_kw: calls.append(True)
        or FakeResponse(b"terms", "text/html"),
    )
    capture = adapter.capture(source_id, uri)
    assert (
        capture.available_at == capture.captured_at and capture.publication_at is None
    )
    with pytest.raises(SnapshotError):
        adapter.capture(source_id, uri + "?override=1")
    with pytest.raises(SnapshotError):
        adapter.capture(source_id, uri, available_at=CAPTURE)
    assert len(calls) == 1
