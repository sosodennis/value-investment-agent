from dataclasses import dataclass
from contextlib import contextmanager
from datetime import date, timedelta
from collections.abc import Callable
import json

import pytest
from pydantic import ValidationError

from fundamental_service.arelle_parser import ArelleFindingV1, fact_semantic_digest
from fundamental_service.artifact_evidence import require_retained_artifact
from fundamental_service.contracts import (
    ArelleFindingEvidenceV1,
    SecIntegrityEvidenceV1,
)
from fundamental_service.data_releases import ArtifactRefV1
from fundamental_service.fiscal_source_closure import (
    FiscalArtifactRead,
    FiscalSourceClosure,
)
from fundamental_service.fiscal_source_contracts import evaluate_fiscal_issuer
from fundamental_service.fiscal_validation_contracts import (
    FiscalOriginalValidationRequestV1,
    FiscalValidationCompleteRefusedV1,
    FiscalValidationIncompleteV1,
    FiscalValidationMatchedV1,
    FiscalValidationPinV1,
    FiscalValidationRuntimeV1,
)
from fundamental_service.parser_action_contracts import ParserBuildIdentityV1
from fundamental_service.replay import ArtifactStore
from fundamental_service.sec_capture import (
    SecResponseReceiptV1,
    sec_response_artifact_id,
)
from fundamental_service.sec_source import SecSourceError
from fundamental_service.serialization import canonical_bytes, sha256_digest
from fundamental_service.snapshots import FilesystemContentStore, SnapshotError

from test_fiscal_discovery import (
    DiscoveryHarness,
    HISTORY,
    RECENT,
    row,
    rows,
    uncontended_lock,
    uri,
)
from test_fiscal_source_contracts import _case


def _ref(record, role):
    return ArtifactRefV1(
        role=role,
        artifact_id=record.artifact_id,
        content_hash=record.content_hash,
        media_type=record.media_type,
    )


def _selection(discovery, publication, accession=None):
    return FiscalOriginalValidationRequestV1(
        discovery_ref=_ref(publication.artifact, "fiscal-discovery"),
        accession_number=accession or discovery.selection.selected[0].accession_number,
    )


def _closure(harness, source, *, lock=None, pin=None):
    return FiscalSourceClosure(
        discovery=harness.discovery(),
        artifacts=harness.artifacts,
        source=source,
        pin=pin
        or FiscalValidationPinV1(
            declared_source_revision=harness.request.declared_source_revision,
            taxonomy_manifest_id="synthetic-fiscal-cache",
        ),
        capture_lock=lock or (lambda key, deadline_at: uncontended_lock(key)),
        clock=lambda: harness.now,
    )


@pytest.mark.parametrize("parent_read_first", (False, True))
def test_consumer_keeps_overlap_but_does_not_inherit_parent_reads(
    tmp_path, parent_read_first
):
    artifacts = ArtifactStore(tmp_path)
    shared = artifacts.put("shared", {"value": "shared"})
    later = artifacts.put("later", {"value": "later"})
    parent = FiscalArtifactRead(artifacts, lambda: 60)
    shared_raw = artifacts.read(shared.artifact_id)
    if parent_read_first:
        parent.read(shared.artifact_id)
    consumer = parent.for_consumer()
    assert consumer.records == ()
    assert consumer.read(shared.artifact_id) == shared_raw
    parent.read(later.artifact_id)
    assert consumer.records == ((shared.artifact_id, shared),)
    assert parent.records == (
        (shared.artifact_id, shared),
        (later.artifact_id, later),
    )

    artifacts._artifact_path(later.content_hash, later.media_type).write_bytes(
        b"changed"
    )
    consumer.check_bodies()
    with pytest.raises(SnapshotError):
        parent.check_bodies()
    artifacts._artifact_path(shared.content_hash, shared.media_type).write_bytes(
        b"changed"
    )
    with pytest.raises(SnapshotError):
        consumer.check_bodies()


@pytest.mark.parametrize("consumer", (False, True))
def test_reader_keeps_metadata_absence_and_non_enrolling_probe(tmp_path, consumer):
    artifacts = ArtifactStore(tmp_path)
    metadata = artifacts.put("metadata", {"value": "metadata"}, ("1" * 64,))
    parent = FiscalArtifactRead(artifacts, lambda: 60)
    reader = parent.for_consumer() if consumer else parent
    assert reader.current("missing") is None
    assert reader.records == ()
    reader.expect(metadata.artifact_id, metadata)
    reader.expect("absent", None)
    assert (
        parent.records
        == reader.records
        == (
            (metadata.artifact_id, metadata),
            ("absent", None),
        )
    )
    artifacts._artifact_path(metadata.content_hash, metadata.media_type).write_bytes(
        b"unconsumed body"
    )
    reader.check_bodies()
    artifacts.put("absent", {"value": "appeared"})
    for observed in (reader, parent):
        with pytest.raises(SnapshotError, match="metadata changed"):
            observed.check_current()
    with pytest.raises(SnapshotError, match="metadata changed"):
        reader.get("absent")
    assert dict(reader.records)["absent"] is None
    assert dict(parent.records)["absent"] is None


@pytest.mark.parametrize(
    "change",
    (
        {"content_hash": "2" * 64},
        {"media_type": "text/plain"},
        {"dependency_hashes": ("3" * 64,)},
        {"status": "invalidated"},
        {"retention": "operational_cache"},
    ),
)
def test_consumer_metadata_conflict_cannot_replace_parent_observation(tmp_path, change):
    artifacts = ArtifactStore(tmp_path)
    record = artifacts.put("metadata", {"value": "metadata"})
    parent = FiscalArtifactRead(artifacts, lambda: 60)
    parent.expect(record.artifact_id, record)
    consumer = parent.for_consumer()
    changed = record.model_copy(update=change)
    with pytest.raises(SnapshotError, match="metadata changed"):
        consumer.expect(record.artifact_id, changed)
    assert parent.records == ((record.artifact_id, record),)
    assert consumer.records == ((record.artifact_id, changed),)
    with pytest.raises(SnapshotError, match="metadata changed"):
        consumer.expect(record.artifact_id, record)
    parent.check_current()


@pytest.mark.parametrize("consumer", (False, True))
@pytest.mark.parametrize("failure", ("io", "registration", "hash", "deadline"))
def test_reader_does_not_return_bytes_after_store_or_deadline_failure(
    tmp_path, monkeypatch, consumer, failure
):
    artifacts = ArtifactStore(tmp_path)
    record = artifacts.put("body", {"value": "body"})
    expired = False

    def budget():
        if expired:
            raise SnapshotError("REQUEST_DEADLINE_EXCEEDED", "deadline expired")
        return 60

    parent = FiscalArtifactRead(artifacts, budget)
    reader = parent.for_consumer() if consumer else parent
    original = artifacts.read_bounded

    def read(identity, *, maximum_bytes):
        nonlocal expired
        if failure == "io":
            raise OSError("synthetic read failed")
        if failure == "registration":
            raise SnapshotError("CONTENT_NOT_FOUND", "synthetic registration missing")
        if failure == "hash":
            return b"changed"
        raw = original(identity, maximum_bytes=maximum_bytes)
        expired = True
        return raw

    monkeypatch.setattr(artifacts, "read_bounded", read)
    with pytest.raises((OSError, SnapshotError)) as raised:
        reader.read(record.artifact_id)
    if failure == "io":
        assert isinstance(raised.value, OSError)
        assert str(raised.value) == "synthetic read failed"
    else:
        assert isinstance(raised.value, SnapshotError)
        assert (
            raised.value.code
            == {
                "registration": "CONTENT_NOT_FOUND",
                "hash": "FISCAL_VALIDATION_INVALID",
                "deadline": "REQUEST_DEADLINE_EXCEEDED",
            }[failure]
        )
    assert parent.records == reader.records == ((record.artifact_id, record),)
    monkeypatch.setattr(artifacts, "read_bounded", original)
    expired = False
    assert reader.read(record.artifact_id) == original(
        record.artifact_id, maximum_bytes=8 * 1024 * 1024
    )
    parent.check_bodies()


@pytest.mark.parametrize("conflicting_owner", ("local", "parent"))
def test_consumer_body_conflict_does_not_return_bytes_or_replace_first_length(
    tmp_path, conflicting_owner
):
    artifacts = ArtifactStore(tmp_path)
    record = artifacts.put("body", {"value": "body"})
    parent = FiscalArtifactRead(artifacts, lambda: 60)
    consumer = parent.for_consumer()
    owner = consumer if conflicting_owner == "local" else parent
    owner._expect_body(
        record.artifact_id,
        (record.content_hash, len(artifacts.read(record.artifact_id)) + 1),
    )
    with pytest.raises(SnapshotError, match="bytes changed"):
        consumer.read(record.artifact_id)
    with pytest.raises(SnapshotError, match="bytes changed"):
        owner.check_bodies()


@dataclass
class SyntheticIncompleteSource:
    calls: int = 0
    on_verify: Callable[[], None] | None = None

    def validate(self, request, *, deadline_at):
        self.calls += 1
        return FiscalValidationIncompleteV1(
            issue_codes=("SYNTHETIC_SOURCE_UNAVAILABLE",)
        )

    def verify(self, request, outcome, *, artifacts, deadline_at):
        assert outcome.issue_codes == ("SYNTHETIC_SOURCE_UNAVAILABLE",)
        if self.on_verify:
            self.on_verify()


def test_synthetic_refusal_roundtrips_through_rebuilt_filesystem_stores(tmp_path):
    harness = DiscoveryHarness(tmp_path)
    discovery, published = harness.publish()
    source = SyntheticIncompleteSource()
    request = _selection(discovery, published)

    def closure():
        return _closure(harness, source)

    evidence, publication = closure().execute(request, deadline_at=harness.deadline)
    assert evidence.outcome.kind == "incomplete_refused"
    assert not evidence.outcome.retryable
    assert evidence.request.filing == discovery.selection.selected[0]
    assert publication.wrote
    retained = harness.inventory()

    harness.artifacts = ArtifactStore(tmp_path / "artifacts")
    harness.content = FilesystemContentStore(tmp_path / "content")
    assert (
        closure().read(evidence.artifact_id, deadline_at=harness.deadline) == evidence
    )
    previous, replay = closure().execute(request, deadline_at=harness.deadline)
    assert previous == evidence
    assert replay.artifact == publication.artifact
    assert not replay.wrote
    assert source.calls == 1
    assert harness.inventory() == retained

    record = publication.artifact
    harness.artifacts._artifact_path(
        record.content_hash, record.media_type
    ).write_bytes(b"corrupt")
    with pytest.raises(SnapshotError):
        closure().read(evidence.artifact_id, deadline_at=harness.deadline)
    harness.now = harness.deadline
    with pytest.raises(SecSourceError, match="deadline"):
        closure().read(evidence.artifact_id, deadline_at=harness.deadline)


@dataclass
class SyntheticCompleteSource:
    harness: DiscoveryHarness
    blocked: bool = True
    include_marker: bool = True
    current_runtime_digest: str = "2" * 64
    on_verify: Callable[[], None] | None = None

    def validate(self, request, *, deadline_at):
        assert deadline_at == self.harness.deadline
        filing = request.filing
        report, _, original = _case(period_end=filing.report_period_end)
        folder = (
            f"https://www.sec.gov/Archives/edgar/data/{int(filing.cik)}/"
            f"{filing.accession_number.replace('-', '')}"
        )
        primary_uri = f"{folder}/{filing.primary_document}"
        archive_uri = f"{folder}/{filing.accession_number}-xbrl.zip"
        index_uri = f"{folder}/index.json"
        captures = {
            primary_uri: (b"synthetic primary", "text/html"),
            archive_uri: (b"synthetic archive", "application/zip"),
            index_uri: (b'{"synthetic":"index"}', "application/json"),
        }
        receipts = {}
        for uri_value, (payload, media_type) in sorted(captures.items()):
            content_hash = self.harness.content.put(payload, media_type=media_type)
            receipt = SecResponseReceiptV1(
                scope=request.scope,
                uri=uri_value,
                content_hash=content_hash,
                http_status=200,
                media_type=media_type,
                captured_at=self.harness.provider.at,
                response_headers=(),
                declared_size=len(payload),
                received_size=len(payload),
            )
            self.harness.artifacts.put(
                sec_response_artifact_id(request.scope, uri_value),
                receipt,
                (content_hash,),
            )
            receipts[uri_value] = receipt
        primary, archive, index = (
            receipts[primary_uri],
            receipts[archive_uri],
            receipts[index_uri],
        )
        action_key = sha256_digest("synthetic action")
        result_digest = sha256_digest("synthetic result")
        body_value = {"synthetic": "report body"}
        body_hash = sha256_digest(body_value)
        body_role = "sec-parser-action-report-v1"
        body_id = f"{body_role}:{body_hash}"
        action_role = "sec-parser-action-result-v2"
        action_id = f"{action_role}:{action_key}:{result_digest}"
        delivery_role = "sec-parser-action-delivery-v2"
        delivery_value = {"synthetic": "delivery"}
        delivery_digest = sha256_digest(delivery_value)
        delivery_id = f"{delivery_role}:{delivery_digest}"
        body = self.harness.artifacts.put(body_id, body_value)
        result = self.harness.artifacts.put(
            action_id, {"body": body.artifact_id}, (body_hash,)
        )
        delivery = self.harness.artifacts.put(delivery_id, delivery_value)
        marker = f"sec-parser-action-v2:normalized:{action_key}:{result_digest}:{delivery_digest}"
        action_refs = tuple(
            sorted(
                (
                    _ref(body, body_role),
                    _ref(result, action_role),
                    _ref(delivery, delivery_role),
                ),
                key=lambda ref: ref.artifact_id,
            )
        )
        context = report.dqc_filing_context
        assert context is not None
        context = context.model_copy(
            update={
                "issuer_id": filing.cik,
                "accession_number": filing.accession_number,
                "filing_date": filing.filing_date,
            }
        )
        findings = (
            (
                ArelleFindingV1(
                    code="DQC.US.0015.5970",
                    severity="error",
                    message="Synthetic finding",
                ),
            )
            if self.blocked
            else ()
        )
        report = report.model_copy(
            update={
                "facts": tuple(
                    fact.model_copy(
                        update={
                            "period_start": date(filing.report_period_end.year, 1, 1)
                        }
                    )
                    for fact in report.facts
                ),
                "findings": findings,
                "source_content_hash": primary.content_hash,
                "taxonomy_cache_hash": request.pin.taxonomy_cache_sha256,
                "dqc_filing_context": context,
                "validation_evidence": (
                    *report.validation_evidence[:-1],
                    context.evidence_marker(),
                    *((marker,) if self.include_marker else ()),
                ),
            }
        )
        original = original.model_copy(
            update={
                "uri": primary_uri,
                "cik": filing.cik,
                "accession_number": filing.accession_number,
                "available_at": filing.accepted_at,
                "captured_at": primary.captured_at,
                "content_hash": primary.content_hash,
                "parser_input_hash": primary.content_hash,
            }
        )
        claim = evaluate_fiscal_issuer(
            report,
            filing=filing,
            source=original,
            decision_at=request.valuation_timestamp,
            request_digest=request.digest,
        )
        integrity = SecIntegrityEvidenceV1(
            accession_number=filing.accession_number,
            primary_document_uri=primary_uri,
            captured_at=primary.captured_at,
            dqc_filing_context=context,
            archive_index_uri=index_uri,
            archive_index_hash=index.content_hash,
            declared_primary_size=primary.received_size,
            raw_received_size=primary.received_size,
            raw_content_hash=primary.content_hash,
            archive_uri=archive_uri,
            archive_size=archive.received_size,
            archive_hash=archive.content_hash,
            archive_member_name=filing.primary_document,
            archive_member_size=primary.received_size,
            archive_member_hash=primary.content_hash,
            integrity_relation="exact",
            normalized_content_size=primary.received_size,
            normalized_content_hash=primary.content_hash,
            normalized_fact_count=len(report.facts),
            normalized_fact_digest=fact_semantic_digest(report),
            archive_fact_count=len(report.facts),
            archive_fact_digest=fact_semantic_digest(report),
            parser_input_hash=primary.content_hash,
            validation_profile_digest=report.validation_profile_digest,
            validation_engines=report.validation_engines,
            validation_evidence=report.validation_evidence,
            network_attempt_count=0,
            taxonomy_manifest_hash=request.pin.taxonomy_cache_sha256,
            arelle_version=report.parser_version,
            efm_profile=report.validation_profile.efm_profile,
            dqc_version=report.validation_profile.dqc_version,
            xule_version=report.validation_profile.xule_version,
            quality_decision="block" if self.blocked else "pass",
            findings=tuple(
                ArelleFindingEvidenceV1(
                    code=finding.code, severity=finding.severity, blocks=True
                )
                for finding in findings
            ),
        )
        runtime = FiscalValidationRuntimeV1(
            pin=request.pin,
            taxonomy_version=report.taxonomy_version,
            dqc_namespace="http://fasb.org/us-gaap/2024",
            validation_profile_id=report.validation_profile.profile_id,
            validation_profile_digest=report.validation_profile_digest,
            delivery_revision=request.pin.declared_source_revision,
            parser_build=ParserBuildIdentityV1(
                implementation_digest="1" * 64,
                runtime_digest="2" * 64,
                output_schema_digest="3" * 64,
            ),
        )
        complete = dict(
            claim=claim,
            runtime=runtime,
            integrity=integrity,
            responses=tuple(receipts.values()),
            action_refs=action_refs,
        )
        if self.blocked:
            return FiscalValidationCompleteRefusedV1(
                issue_codes=claim.issue_codes, **complete
            )
        return FiscalValidationMatchedV1(**complete)

    def verify(self, request, outcome, *, artifacts, deadline_at):
        assert deadline_at == self.harness.deadline
        if outcome.runtime.parser_build.runtime_digest != self.current_runtime_digest:
            raise SnapshotError(
                "SYNTHETIC_BUILD_CHANGED", "synthetic current build differs"
            )
        normalized = next(
            ref
            for ref in outcome.action_refs
            if ref.role == "sec-parser-action-result-v2"
        )
        body = next(
            ref
            for ref in outcome.action_refs
            if ref.role == "sec-parser-action-report-v1"
        )
        require_retained_artifact(
            artifacts, normalized, dependency_hashes=(body.content_hash,)
        )
        for receipt in outcome.responses:
            self.harness.content.get(
                receipt.content_hash, media_type=receipt.media_type
            )
        if self.on_verify:
            self.on_verify()


@dataclass
class SyntheticRecoveringSource(SyntheticCompleteSource):
    failures_remaining: int = 1
    calls: int = 0

    def validate(self, request, *, deadline_at):
        assert deadline_at == self.harness.deadline
        self.calls += 1
        if self.failures_remaining:
            self.failures_remaining -= 1
            return FiscalValidationIncompleteV1(
                issue_codes=("SYNTHETIC_SOURCE_UNAVAILABLE",), retryable=True
            )
        return super().validate(request, deadline_at=deadline_at)

    def verify(self, request, outcome, *, artifacts, deadline_at):
        if isinstance(outcome, FiscalValidationIncompleteV1):
            assert deadline_at == self.harness.deadline
            assert outcome.issue_codes == ("SYNTHETIC_SOURCE_UNAVAILABLE",)
            assert outcome.retryable
            if self.on_verify:
                self.on_verify()
            return
        super().verify(request, outcome, artifacts=artifacts, deadline_at=deadline_at)


@pytest.mark.parametrize("failure_count", [1, 2])
def test_synthetic_retryable_failure_can_complete_after_rebuilding_stores(
    tmp_path, failure_count
):
    harness = DiscoveryHarness(tmp_path)
    discovery, published = harness.publish()
    source = SyntheticRecoveringSource(
        harness, blocked=False, failures_remaining=failure_count
    )
    request = _selection(discovery, published)
    lock_calls = []

    @contextmanager
    def lock(key, deadline_at):
        lock_calls.append((key, deadline_at))
        yield

    attempt, attempted = _closure(harness, source, lock=lock).execute(
        request, deadline_at=harness.deadline
    )
    attempt_id = attempted.artifact.artifact_id
    attempt_bytes = harness.artifacts.read(attempt_id)
    assert attempt_id == (
        f"fiscal-original-validation-attempt:{attempted.artifact.content_hash}"
    )
    assert attempt.outcome.kind == "incomplete_refused"
    assert attempt.outcome.retryable
    assert attempted.wrote

    harness.artifacts = ArtifactStore(tmp_path / "artifacts")
    harness.content = FilesystemContentStore(tmp_path / "content")
    service = _closure(harness, source, lock=lock)
    if failure_count == 2:
        repeated, duplicate = service.execute(request, deadline_at=harness.deadline)
        assert repeated == attempt
        assert duplicate.artifact == attempted.artifact
        assert not duplicate.wrote
        assert harness.artifacts.read(attempt_id) == attempt_bytes

    completed, publication = service.execute(request, deadline_at=harness.deadline)
    assert completed.outcome.kind == "complete_matched"
    assert publication.wrote
    assert publication.artifact.artifact_id != attempt_id
    assert (
        service.read_matched(
            _ref(publication.artifact, "fiscal-original-validation"),
            deadline_at=harness.deadline,
        ).outcome
        == completed.outcome
    )

    replayed, replay = service.execute(request, deadline_at=harness.deadline)
    assert replayed == completed
    assert replay.artifact == publication.artifact
    assert not replay.wrote
    assert source.calls == failure_count + 1
    assert lock_calls == [(publication.artifact.artifact_id, harness.deadline)] * (
        failure_count + 2
    )
    assert service.read(attempt_id, deadline_at=harness.deadline) == attempt
    assert harness.artifacts.get(attempt_id) == attempted.artifact
    assert harness.artifacts.read(attempt_id) == attempt_bytes
    with pytest.raises(SnapshotError) as refusal:
        service.read_matched(
            _ref(attempted.artifact, "fiscal-original-validation"),
            deadline_at=harness.deadline,
        )
    assert refusal.value.code == "FISCAL_VALIDATION_REFUSED"


@pytest.mark.parametrize("during", ["read_verification", "publication_unlock"])
def test_synthetic_retryable_attempt_rechecks_revoked_metadata(tmp_path, during):
    harness = DiscoveryHarness(tmp_path)
    discovery, published = harness.publish()
    source = SyntheticRecoveringSource(harness, failures_remaining=2)
    request = _selection(discovery, published)
    service = _closure(harness, source)
    attempt, _ = service.execute(request, deadline_at=harness.deadline)

    def revoke():
        harness.artifacts.invalidate(attempt.artifact_id)

    @contextmanager
    def lock(_key, _deadline_at):
        yield
        revoke()

    with pytest.raises(SnapshotError) as failure:
        if during == "read_verification":
            source.on_verify = revoke
            service.read(attempt.artifact_id, deadline_at=harness.deadline)
        else:
            _closure(harness, source, lock=lock).execute(
                request, deadline_at=harness.deadline
            )
    assert failure.value.code == "FISCAL_VALIDATION_INVALID"
    assert harness.artifacts.get(attempt.artifact_id).status == "invalidated"


@pytest.mark.parametrize("blocked", [True, False])
def test_synthetic_complete_source_retains_raw_outcome_and_gates_matched_access(
    tmp_path, blocked
):
    harness = DiscoveryHarness(tmp_path)
    discovery, published = harness.publish()
    source = SyntheticCompleteSource(harness, blocked=blocked)
    service = _closure(harness, source)
    evidence, publication = service.execute(
        _selection(discovery, published), deadline_at=harness.deadline
    )
    ref = _ref(publication.artifact, "fiscal-original-validation")
    harness.artifacts = ArtifactStore(tmp_path / "artifacts")
    harness.content = FilesystemContentStore(tmp_path / "content")
    service = _closure(harness, source)

    retained = service.read(evidence.artifact_id, deadline_at=harness.deadline)
    assert retained == evidence
    source.include_marker = False
    repeated, replay = service.execute(
        _selection(discovery, published), deadline_at=harness.deadline
    )
    assert repeated == evidence
    assert replay.artifact == publication.artifact
    assert not replay.wrote
    assert evidence.outcome.claim.metadata_status == "matched"
    if blocked:
        assert evidence.outcome.kind == "complete_refused"
        assert evidence.outcome.integrity.quality_decision == "block"
        assert evidence.outcome.claim.report.blocking_finding_codes() == (
            "DQC.US.0015.5970",
        )
        with pytest.raises(SnapshotError) as refused:
            service.read_matched(ref, deadline_at=harness.deadline)
        assert refused.value.code == "FISCAL_VALIDATION_REFUSED"
    else:
        assert evidence.outcome.kind == "complete_matched"
        assert (
            service.read_matched(ref, deadline_at=harness.deadline).outcome
            == evidence.outcome
        )


def test_synthetic_parser_completion_without_actions_is_refused(tmp_path):
    harness = DiscoveryHarness(tmp_path)
    discovery, published = harness.publish()
    source = SyntheticCompleteSource(harness, blocked=False, include_marker=False)
    with pytest.raises(SnapshotError) as failure:
        _closure(harness, source).execute(
            _selection(discovery, published), deadline_at=harness.deadline
        )
    assert failure.value.code == "FISCAL_VALIDATION_INVALID"
    assert not any(
        b'"artifact_id":"fiscal-original-validation:' in raw
        for raw, _ in harness.inventory().values()
    )


@pytest.mark.parametrize(
    "target",
    ["discovery", "discovery_request", "validation_request", "source", "action"],
)
def test_synthetic_complete_read_rechecks_revocable_metadata_after_verification(
    tmp_path, target
):
    harness = DiscoveryHarness(tmp_path)
    discovery, published = harness.publish()
    source = SyntheticCompleteSource(harness)
    service = _closure(harness, source)
    evidence, _ = service.execute(
        _selection(discovery, published), deadline_at=harness.deadline
    )
    outcome = evidence.outcome
    ids = {
        "discovery": discovery.artifact_id,
        "discovery_request": harness.ids(discovery)["request"],
        "validation_request": evidence.request.artifact_id,
        "source": sec_response_artifact_id(
            evidence.request.scope, outcome.responses[0].uri
        ),
        "action": outcome.action_refs[0].artifact_id,
    }
    source.on_verify = lambda: harness.artifacts.invalidate(ids[target])

    with pytest.raises(SnapshotError) as failure:
        service.read(evidence.artifact_id, deadline_at=harness.deadline)
    assert failure.value.code == "FISCAL_VALIDATION_INVALID"


@pytest.mark.parametrize(
    "target",
    [
        "closure_dependencies",
        "receipt_dependencies",
        "action_dependencies",
        "source_bytes",
    ],
)
def test_synthetic_complete_read_rejects_tampered_dependencies_or_content(
    tmp_path, target
):
    harness = DiscoveryHarness(tmp_path)
    discovery, published = harness.publish()
    source = SyntheticCompleteSource(harness)
    service = _closure(harness, source)
    evidence, publication = service.execute(
        _selection(discovery, published), deadline_at=harness.deadline
    )
    receipt = evidence.outcome.responses[0]
    if target == "source_bytes":
        harness.content._path(receipt.content_hash, receipt.media_type).write_bytes(
            b"wrong"
        )
    else:
        action = next(
            ref
            for ref in evidence.outcome.action_refs
            if ref.role == "sec-parser-action-result-v2"
        )
        identities = {
            "closure_dependencies": publication.artifact.artifact_id,
            "receipt_dependencies": sec_response_artifact_id(
                evidence.request.scope, receipt.uri
            ),
            "action_dependencies": action.artifact_id,
        }
        record = harness.artifacts.get(identities[target])
        harness.replace_record(record.model_copy(update={"dependency_hashes": ()}))

    with pytest.raises(SnapshotError):
        service.read(evidence.artifact_id, deadline_at=harness.deadline)


def test_expired_lock_consumes_original_deadline_without_validating(tmp_path):
    harness = DiscoveryHarness(tmp_path)
    discovery, published = harness.publish()
    source = SyntheticIncompleteSource()

    @contextmanager
    def lock(_key, deadline_at):
        assert deadline_at == harness.deadline
        harness.now = deadline_at
        yield

    with pytest.raises(SecSourceError, match="deadline"):
        _closure(harness, source, lock=lock).execute(
            _selection(discovery, published), deadline_at=harness.deadline
        )
    assert source.calls == 0


@pytest.mark.parametrize(
    ("prefix", "failures", "initial_calls"),
    [
        ("fiscal-original-validation-request:", 0, 0),
        ("fiscal-original-validation:", 0, 1),
        ("fiscal-original-validation-attempt:", 1, 1),
    ],
)
def test_expired_publication_cannot_be_replayed(
    tmp_path, monkeypatch, prefix, failures, initial_calls
):
    harness = DiscoveryHarness(tmp_path)
    discovery, published = harness.publish()
    request = _selection(discovery, published)
    source = SyntheticRecoveringSource(
        harness, blocked=False, failures_remaining=failures
    )
    append = harness.artifacts._append_record_unlocked
    delayed = []

    def expire_before_append(record, **kwargs):
        if record.artifact_id.startswith(prefix):
            delayed.append(record)
            harness.now = harness.deadline
        return append(record, **kwargs)

    monkeypatch.setattr(
        harness.artifacts, "_append_record_unlocked", expire_before_append
    )
    with pytest.raises(SecSourceError) as expired:
        _closure(harness, source).execute(request, deadline_at=harness.deadline)
    assert expired.value.code == "REQUEST_DEADLINE_EXCEEDED"
    assert source.calls == initial_calls
    (unpublished,) = delayed

    harness.artifacts = ArtifactStore(tmp_path / "artifacts")
    with pytest.raises(SnapshotError) as missing:
        persisted = harness.artifacts.get(unpublished.artifact_id)
        pytest.fail(f"expired publication left replayable metadata: {persisted}")
    assert missing.value.code == "ARTIFACT_NOT_FOUND"

    harness.deadline += timedelta(minutes=1)
    service = _closure(harness, source)
    completed, publication = service.execute(request, deadline_at=harness.deadline)
    assert completed.outcome.kind == "complete_matched"
    assert publication.wrote
    for _ in range(2):
        replayed, replay = service.execute(request, deadline_at=harness.deadline)
        assert replayed == completed
        assert replay.artifact == publication.artifact
        assert not replay.wrote
    assert source.calls == initial_calls + 1
    with pytest.raises(SnapshotError) as expired_replay:
        harness.artifacts.put_bytes_with_receipt(
            publication.artifact.artifact_id,
            harness.artifacts.read(publication.artifact.artifact_id),
            publication.artifact.dependency_hashes,
            media_type=publication.artifact.media_type,
            publication_budget=lambda: 0.0,
        )
    assert expired_replay.value.code == "REQUEST_DEADLINE_EXCEEDED"


@pytest.mark.parametrize("change", ["wrong_pin", "wrong_build", "unconfigured"])
def test_synthetic_complete_read_rejects_runtime_changes(tmp_path, change):
    harness = DiscoveryHarness(tmp_path)
    discovery, published = harness.publish()
    source = SyntheticCompleteSource(harness)
    evidence, _ = _closure(harness, source).execute(
        _selection(discovery, published), deadline_at=harness.deadline
    )
    if change == "unconfigured":
        reader = _closure(harness, None)
    elif change == "wrong_pin":
        reader = _closure(
            harness,
            source,
            pin=evidence.request.pin.model_copy(
                update={"taxonomy_manifest_id": "other-cache"}
            ),
        )
    else:
        source.current_runtime_digest = "4" * 64
        reader = _closure(harness, source)

    with pytest.raises((SnapshotError, SecSourceError)) as refusal:
        reader.read(evidence.artifact_id, deadline_at=harness.deadline)
    assert (
        refusal.value.code
        == {
            "wrong_pin": "FISCAL_VALIDATION_INVALID",
            "wrong_build": "SYNTHETIC_BUILD_CHANGED",
            "unconfigured": "FISCAL_VALIDATION_UNCONFIGURED",
        }[change]
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("filing", "caller override"),
        ("form", "caller override"),
        ("cik", "caller override"),
        ("valuation_timestamp", "caller override"),
        ("retryable", True),
    ],
)
def test_request_cannot_override_trusted_discovery_scope(tmp_path, field, value):
    harness = DiscoveryHarness(tmp_path)
    discovery, published = harness.publish()
    request = _selection(discovery, published)
    with pytest.raises(ValidationError):
        FiscalOriginalValidationRequestV1.model_validate(
            {**request.model_dump(), field: value}
        )


@pytest.mark.parametrize(
    "revision", ["none", "future", "amendment", "unsupported_original"]
)
def test_prior_support_source_uses_its_own_cutoff_and_latest_period_policy(
    tmp_path, revision
):
    harness = DiscoveryHarness(tmp_path)
    prior_period = date(2021, 9, 30)
    prior = row(prior_period)
    history = json.loads(harness.provider.pages[uri(HISTORY)])
    entries = [prior]
    if revision != "none":
        changed_at = harness.request.valuation_timestamp.date() + (
            timedelta(days=1) if revision == "future" else timedelta(days=-1)
        )
        entries.append(
            row(
                prior_period,
                accessionNumber="0000950170-24-123456",
                filingDate=changed_at.isoformat(),
                acceptanceDateTime=f"{changed_at.isoformat()}T16:00:00Z",
                form="10-Q" if revision == "unsupported_original" else "10-Q/A",
                isXBRL=0 if revision == "unsupported_original" else 1,
            )
        )
    recent = json.loads(harness.provider.pages[uri(RECENT)])
    extra_rows = rows(*entries).model_dump(exclude_none=True)
    harness.provider.pages[uri(HISTORY)] = canonical_bytes(
        {
            key: [*values, *extra_rows[key]]
            for key, values in history.items()
            if values is not None
        }
    )
    for name in ("filingCount", "filingTo"):
        if name == "filingCount":
            recent["filings"]["files"][0][name] += len(entries)
        else:
            recent["filings"]["files"][0][name] = max(
                recent["filings"]["files"][0][name],
                *(entry["filingDate"] for entry in entries),
            )
    harness.provider.pages[uri(RECENT)] = canonical_bytes(recent)
    discovery, published = harness.publish()
    assert prior_period not in {
        item.report_period_end for item in discovery.selection.selected
    }
    accession = prior["accessionNumber"]
    assert any(
        item.accession_number == accession for item in discovery.selection.candidates
    )
    source = SyntheticIncompleteSource()
    service = _closure(harness, source)
    request = _selection(discovery, published, accession)

    if revision in {"amendment", "unsupported_original"}:
        with pytest.raises(SnapshotError) as failure:
            service.execute(request, deadline_at=harness.deadline)
        assert failure.value.code == "FISCAL_CANDIDATE_INELIGIBLE"
        assert source.calls == 0
    else:
        evidence, _ = service.execute(request, deadline_at=harness.deadline)
        assert evidence.request.filing.report_period_end == prior_period
        assert (
            evidence.request.valuation_timestamp == harness.request.valuation_timestamp
        )
        assert source.calls == 1
