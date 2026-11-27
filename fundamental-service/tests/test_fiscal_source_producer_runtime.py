from __future__ import annotations

import os
import hashlib
import json
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from contextlib import nullcontext

import pytest
from cryptography.hazmat.primitives import serialization

from fundamental_service.fiscal_source_closure import (
    FiscalArtifactRead,
    FiscalSourceClosure,
)
from fundamental_service.fiscal_classification_source import (
    FiscalClassificationSourceResolver,
)
from fundamental_service.fiscal_source_accounting_policy import (
    source_accounting_policy_identity,
)
from fundamental_service.fiscal_source_producer_contracts import (
    FiscalAccountingAccreditationV1,
)
from fundamental_service.fiscal_source_producer_runtime import (
    producer_reference,
    public_accounting_accreditation_provider,
)
from fundamental_service.fiscal_source_preparation import (
    FiscalSourceProducerEvidenceVerifier,
)
from fundamental_service.fiscal_source_classification import (
    FiscalSourceClassificationOwner,
)
from fundamental_service.fiscal_admission_history import (
    ReadOnlyFiscalAdmissionHistory,
    PostgresFiscalAdmissionHistory,
)
from fundamental_service.fiscal_focus_witness import FiscalFocusValidatorAuthorityV1
from fundamental_service.fiscal_discovery import FiscalDiscoveryEvidenceV1
from fundamental_service.parser_action_contracts import ParserActionResultV2
from fundamental_service.sec_capture import sec_response_artifact_id
from fundamental_service.artifact_evidence import read_retained_artifact
from fundamental_service.fiscal_source_preparation import (
    fiscal_source_producer_executable_digest,
    read_source_preparation,
)
from fundamental_service.fiscal_source_producer_contracts import FiscalProducerOrderV1
from fundamental_service.fiscal_source_producer_runtime import (
    FiscalSourceProducerInstallationV1,
    FiscalSourceProducerRuntime,
)
from fundamental_service.metadata import (
    PostgresContentStore,
    PostgresArtifactStore,
    PostgresMetadataStore,
)
from fundamental_service.serialization import canonical_bytes, sha256_digest
from fundamental_service.snapshots import SnapshotError
from test_fiscal_discovery import DiscoveryHarness
from test_fiscal_source_closure import SyntheticCompleteSource, _closure, _selection
import test_fiscal_source_classification as classification_cases
import test_fiscal_source_accounting_policy as accounting_cases

environment = classification_cases.environment
sources = accounting_cases.sources


@pytest.fixture
def protected_root():
    parent = Path(os.environ.get("ISSUE495_PRODUCER_PROTECTED_TEMP", str(Path.home())))
    with tempfile.TemporaryDirectory(
        prefix="issue495-source-producer-", dir=parent
    ) as temporary:
        yield Path(temporary)


class CountedSyntheticSource(SyntheticCompleteSource):
    calls = 0

    def validate(self, request, *, deadline_at):
        self.calls += 1
        self.harness.deadline = deadline_at
        return super().validate(request, deadline_at=deadline_at)

    def verify(self, request, outcome, *, artifacts, deadline_at):
        self.harness.deadline = deadline_at
        return super().verify(
            request, outcome, artifacts=artifacts, deadline_at=deadline_at
        )


def deadline():
    return datetime.now(UTC) + timedelta(seconds=60)


@pytest.fixture
def preparer(environment, tmp_path, protected_root):
    env = environment
    harness = DiscoveryHarness(tmp_path / "synthetic-source-infrastructure")
    harness.artifacts = env.store
    harness.content = env.store._content
    discovery, publication = harness.publish()
    source = CountedSyntheticSource(harness, blocked=True)
    closure = _closure(harness, source)
    roster = protected_root / "deployment.json"
    roster.write_bytes(canonical_bytes(env.authorities._configured()))
    roster.chmod(0o600)
    private = protected_root / "preparer.pem"
    private.write_bytes(
        env.preparer_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    private.chmod(0o600)
    orders = protected_root / "orders"
    orders.mkdir(mode=0o700)
    installation = FiscalSourceProducerInstallationV1(
        role="source_preparer",
        audience="ephemeral-preparer",
        authority_id="synthetic-source_preparer",
        workload_uid=os.getuid(),
        deployment_uid=os.getuid(),
        database_role="fundamental",
        deployment_file=roster,
        orders_directory=orders,
        private_key_file=private,
        source_configuration_files=(),
        declared_source_revision=harness.request.declared_source_revision,
        executable_digest=fiscal_source_producer_executable_digest(),
    )
    runtime = FiscalSourceProducerRuntime(
        installation=installation,
        artifacts=env.store,
        metadata=env.metadata,
        sources=closure,
        content=env.store._content.as_read_only(),
        classification_sources=None,
    )
    order = FiscalProducerOrderV1(
        order_id="prepare-one",
        role="source_preparer",
        audience=installation.audience,
        authority_id=installation.authority_id,
        deployment_digest=sha256_digest(env.authorities._configured()),
        executable_digest=installation.executable_digest,
        issuance=env.history.read_epoch(deadline_at=deadline()).issuance_context,
        source_request=_selection(discovery, publication),
        valid_from=datetime.now(UTC) - timedelta(seconds=1),
        expires_at=datetime.now(UTC) + timedelta(minutes=10),
    )
    path = orders / (order.order_id + ".json")
    path.write_bytes(canonical_bytes(order))
    path.chmod(0o600)
    return runtime, order, env, source


class RetainedDiscoveryAdapter:
    def __init__(self, discovery, evidence, store):
        self.discovery, self.evidence, self.store = discovery, evidence, store

    def read(self, artifact_id, *, deadline_at):
        assert artifact_id == self.discovery.artifact_id
        return self.discovery

    def read_current(self, artifact_id, *, deadline_at):
        return self.read(artifact_id, deadline_at=deadline_at)

    def read_current_with_metadata(self, artifact_id, *, deadline_at):
        return self.read(artifact_id, deadline_at=deadline_at), (
            (artifact_id, self.store.get(artifact_id)),
        )

    def read_for_validation(self, artifact_id, accession, *, deadline_at):
        assert artifact_id == self.discovery.artifact_id
        assert accession == self.evidence.request.filing.accession_number
        return (
            self.discovery.request,
            self.evidence.request.filing,
            ((artifact_id, self.store.get(artifact_id)),),
        )


class RetainedSECAdapter:
    def __init__(self, evidence):
        self.evidence = evidence

    def validate(self, request, *, deadline_at):
        assert request == self.evidence.request
        return self.evidence.outcome

    def verify(self, request, outcome, *, artifacts, deadline_at):
        assert request == self.evidence.request
        assert outcome == self.evidence.outcome
        for ref in outcome.action_refs:
            assert (
                hashlib.sha256(read_retained_artifact(artifacts, ref)).hexdigest()
                == ref.content_hash
            )

    def observe(self, request, outcome, *, artifacts, deadline_at):
        owner = self
        self.verify(request, outcome, artifacts=artifacts, deadline_at=deadline_at)

        class Read:
            @property
            def content_readsets(self):
                return ()

            @property
            def input_footprint(self):
                return (canonical_bytes(owner.evidence.model_dump(mode="json")).hex(),)

            def retained_input_binding(self, reference):
                from test_fiscal_projection_builder import (
                    synthetic_retained_input_binding,
                )

                return synthetic_retained_input_binding(owner.evidence, reference)

            def check_current(self):
                owner.verify(
                    request, outcome, artifacts=artifacts, deadline_at=deadline_at
                )
                assert datetime.now(UTC) < deadline_at

        return Read()

    def observe_current(self, request, outcome, binding, *, artifacts, deadline_at):
        observed = self.observe(
            request, outcome, artifacts=artifacts, deadline_at=deadline_at
        )
        assert observed.retained_input_binding(binding.source_validation_ref) == binding
        return observed


class RetainedFocusAdapter:
    def __init__(self, source, authority, artifacts):
        self.source, self.authority, self.artifacts = source, authority, artifacts

    def observe(self, artifact_id, *, deadline_at):
        from copy import deepcopy

        owner = self
        original = deepcopy(self.read(artifact_id, deadline_at=deadline_at))

        class Read:
            @property
            def artifact_readset(self):
                from fundamental_service.fiscal_source_closure import (
                    FiscalArtifactReadSet,
                )

                raw = canonical_bytes(original)
                return FiscalArtifactReadSet(
                    ((artifact_id, owner.artifacts.get(artifact_id)),),
                    ((artifact_id, (sha256_digest(original), len(raw))),),
                    (),
                )

            @property
            def input_footprint(self):
                return (self.artifact_readset.records, self.artifact_readset.bodies)

            @property
            def content_readsets(self):
                return ()

            @property
            def witness(self):
                return deepcopy(original)

            @property
            def records(self):
                return ((artifact_id, owner.artifacts.get(artifact_id)),)

            def check_current(self):
                assert owner.read(artifact_id, deadline_at=deadline_at) == original
                assert datetime.now(UTC) < deadline_at

        return Read()

    def _observe_current(self, artifact_id, binding, *, deadline_at):
        assert (
            binding.source_validation_ref
            == self.source.witness.witness.source_validation_ref
        )
        return self.observe(artifact_id, deadline_at=deadline_at)

    def read(self, artifact_id, *, deadline_at):
        witness = self.source.witness
        assert artifact_id == witness.artifact_id
        assert datetime.now(UTC) < witness.expires_at <= self.authority.valid_until
        assert witness.key_id == self.authority.key_id
        self.authority.public_key().verify(
            bytes.fromhex(witness.signature), witness.signing_bytes()
        )
        assert read_retained_artifact(
            self.artifacts, self.source.scope.witness_ref
        ) == canonical_bytes(witness)
        return witness


def populate_retained_content(source, content, retained_root):
    from fundamental_service.fiscal_source_preparation import source_content_references

    export = (
        retained_root
        / "dual-runtime/persistence-export/bf9d604c9dcb97b0b0b880cb22c0d22a5a1bc965419727a33bdcf8edae9b0710/content"
    )
    for ref in source_content_references(source.evidence):
        if ref.content_hash == source.evidence.outcome.integrity.archive_hash:
            raw = source.archive
        else:
            candidates = tuple(
                (export / ref.content_hash[:2]).glob(ref.content_hash + ".*")
            )
            assert len(candidates) == 1, ref
            raw = candidates[0].read_bytes()
        assert hashlib.sha256(raw).hexdigest() == ref.content_hash
        content.put(raw, media_type=ref.media_type)


@pytest.fixture(params=("historical", "current"))
def retained_producer(request, preparer, sources, protected_root, tmp_path):
    runtime, original_order, env, _ = preparer
    source = sources[request.param]
    retained_root = Path(os.environ["ISSUE495_RETAINED_EVIDENCE_ROOT"])
    formal = (
        retained_root
        / "formal-fiscal-sources"
        / source.evidence.request.pin.declared_source_revision
        / ("msft-" + request.param)
    )
    discovery = FiscalDiscoveryEvidenceV1.model_validate_json(
        json.dumps(
            json.loads((formal / "discover-1.stdout.json").read_bytes())["evidence"]
        )
    )
    store = env.store
    store.put_with_receipt(discovery.artifact_id, discovery, discovery.dependencies)
    evidence, outcome = source.evidence, source.evidence.outcome
    store.put_with_receipt(
        evidence.request.artifact_id,
        evidence.request,
        (evidence.request.selection.discovery_ref.content_hash,),
    )
    for receipt in outcome.responses:
        store.put_with_receipt(
            sec_response_artifact_id(evidence.request.scope, receipt.uri),
            receipt,
            (receipt.content_hash,),
        )
    for action in source.witness.witness.actions:
        raw = (
            retained_root
            / "formal-signed-witness-review"
            / (action.report_ref.content_hash + ".json")
        ).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == action.report_ref.content_hash
        store.put_bytes_with_receipt(
            action.report_ref.artifact_id, raw, (), media_type="application/json"
        )
        store.put_with_receipt(
            action.result_ref.artifact_id,
            ParserActionResultV2(
                request=action.request,
                report_content_hash=action.report_ref.content_hash,
            ),
        )
        store.put_with_receipt(action.delivery_ref.artifact_id, action.delivery)
    store.put_with_receipt(
        evidence.artifact_id, evidence.model_dump(mode="json"), evidence.dependencies
    )
    store.put_with_receipt(source.witness.artifact_id, source.witness)
    discovery_adapter = RetainedDiscoveryAdapter(discovery, evidence, store)
    closure = FiscalSourceClosure(
        discovery=discovery_adapter,
        artifacts=store,
        pin=evidence.request.pin,
        source=RetainedSECAdapter(evidence),
        capture_lock=lambda key, deadline: nullcontext(),
    )
    populate_retained_content(source, store._content, retained_root)
    runtime.sources = closure
    installation = runtime.installation.model_copy(
        update={
            "declared_source_revision": evidence.request.pin.declared_source_revision
        }
    )
    runtime.installation = installation
    preparation_order = original_order.model_copy(
        update={
            "order_id": "retained-prepare-" + request.param,
            "source_request": evidence.request.selection,
        }
    )
    (
        installation.orders_directory / (preparation_order.order_id + ".json")
    ).write_bytes(canonical_bytes(preparation_order))
    prepared = runtime.run(preparation_order.order_id, deadline_at=deadline())
    signed = read_source_preparation(FiscalArtifactRead(store, lambda: 60), prepared)
    assert signed.preparation.mode == "retained_then_replayed"
    authority = FiscalFocusValidatorAuthorityV1.model_validate_json(
        (
            retained_root / "dual-runtime/focus-public/validator-authority.json"
        ).read_bytes()
    )
    content = env.store._content
    content.put(
        source.archive,
        media_type=next(
            receipt.media_type
            for receipt in outcome.responses
            if receipt.uri == outcome.integrity.archive_uri
        ),
    )
    resolver = FiscalClassificationSourceResolver(
        sources=closure,
        discovery=discovery_adapter,
        witnesses=RetainedFocusAdapter(source, authority, store),
        content=content.as_read_only(),
    )
    review_raw = (
        retained_root
        / "source-policy-token-amended-review/independent-61/remaining-review.md"
    ).read_bytes()
    review_ref = producer_reference(
        store.put_bytes_with_receipt(
            "retained-independent-policy-review",
            review_raw,
            (),
            media_type="text/markdown",
        ).artifact,
        "independent-accounting-policy-review",
    )
    accreditation = FiscalAccountingAccreditationV1(
        policy=source_accounting_policy_identity(),
        independent_review_ref=review_ref,
        classifier_executable_digest=fiscal_source_producer_executable_digest(),
        valid_from=datetime.now(UTC) - timedelta(minutes=1),
        valid_until=datetime.now(UTC) + timedelta(hours=1),
    )
    accreditation_ref = producer_reference(
        store.put_with_receipt(
            "ephemeral-policy-accreditation", accreditation
        ).artifact,
        "fiscal-accounting-accreditation-v1",
    )
    release = protected_root / "accounting-release.json"
    release.write_bytes(canonical_bytes(accreditation_ref))
    private = protected_root / "classifier.pem"
    private.write_bytes(
        env.signer.key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    private.chmod(0o600)
    classifier_installation = installation.model_copy(
        update={
            "role": "classifier",
            "audience": "ephemeral-classifier",
            "authority_id": "synthetic-classifier",
            "private_key_file": private,
            "accreditation_file": release,
        }
    )
    classifier = FiscalSourceProducerRuntime(
        installation=classifier_installation,
        artifacts=store,
        metadata=env.metadata,
        sources=closure,
        content=env.store._content.as_read_only(),
        classification_sources=resolver,
    )
    classification_order = FiscalProducerOrderV1(
        order_id="classify-" + request.param,
        role="classifier",
        audience=classifier_installation.audience,
        authority_id=classifier_installation.authority_id,
        deployment_digest=original_order.deployment_digest,
        executable_digest=classifier_installation.executable_digest,
        issuance=original_order.issuance,
        preparation_ref=prepared,
        witness_ref=source.scope.witness_ref,
        security_id="MSFT",
        valid_from=datetime.now(UTC) - timedelta(seconds=1),
        expires_at=original_order.expires_at,
    )
    (
        installation.orders_directory / (classification_order.order_id + ".json")
    ).write_bytes(canonical_bytes(classification_order))
    return classifier, classification_order, env, source, release


def test_retained_sec_policy_producer_classifies_and_current_reader_replays(
    retained_producer, monkeypatch
):
    runtime, order, env, source, release = retained_producer
    first = runtime.run(order.order_id, deadline_at=deadline())
    signed = first.signed_classification
    assert signed.review.scope == source.scope
    assert signed.review.tagging == "unresolved"
    assert source.evidence.outcome.kind == "complete_refused"
    again = runtime.run(order.order_id, deadline_at=deadline())
    assert signed == again.signed_classification
    assert not again.publication.wrote
    reference = producer_reference(
        first.publication.artifact, "fiscal-source-classification-v2"
    )
    from test_fiscal_candidate_read_runtime import select_only_role, forbid
    from fundamental_service.fiscal_registry_runtime import build_fiscal_registry_reader

    with select_only_role(env.metadata, env.database_url) as reader_url:
        metadata = PostgresMetadataStore(reader_url, auto_migrate=False)
        try:
            metadata.start_read_only()
            monkeypatch.setattr(metadata, "register_content", forbid)
            monkeypatch.setattr(metadata, "publish_artifact", forbid)
            monkeypatch.setattr(metadata, "_apply_migration", forbid)
            content = PostgresContentStore(
                env.store._content._root, metadata, read_only=True
            )
            artifacts = PostgresArtifactStore(metadata, content, read_only=True)
            previous = runtime.classification_sources
            discovery = RetainedDiscoveryAdapter(
                previous.discovery.discovery, source.evidence, artifacts
            )
            closure = FiscalSourceClosure(
                discovery=discovery,
                artifacts=artifacts,
                pin=source.evidence.request.pin,
                source=RetainedSECAdapter(source.evidence),
                capture_lock=lambda key, deadline: nullcontext(),
            )
            resolver = FiscalClassificationSourceResolver(
                sources=closure,
                discovery=discovery,
                witnesses=RetainedFocusAdapter(
                    source, previous.witnesses.authority, artifacts
                ),
                content=content,
            )
            authorities = build_fiscal_registry_reader(
                deployment_file=runtime.installation.deployment_file,
                deployment_uid=os.getuid(),
                artifacts=artifacts,
                metadata=metadata,
            )
            reader = FiscalSourceClassificationOwner(
                artifacts=artifacts,
                history=ReadOnlyFiscalAdmissionHistory(
                    PostgresFiscalAdmissionHistory(metadata)
                ),
                authorities=authorities,
                sources=resolver,
                producer_evidence=FiscalSourceProducerEvidenceVerifier(
                    public_accounting_accreditation_provider(release, owner=os.getuid())
                ),
                require_production_evidence=True,
            )
            runtime.installation.private_key_file.unlink()
            derivation = None
            observe = resolver.observe

            def observe_source(*args, **kwargs):
                nonlocal derivation
                derivation = observe(*args, **kwargs)
                return derivation

            with monkeypatch.context() as capture:
                capture.setattr(resolver, "observe", observe_source)
                with reader.open_candidate_source(
                    source.scope, (reference,), deadline_at=deadline()
                ) as admission:
                    result = admission.current()
                    assert derivation is not None
                    accreditation_id = (
                        reader.producer_evidence.accreditation().artifact_id
                    )
                    read = artifacts.read

                    def refuse_late_parent_body(identity):
                        if identity == accreditation_id:
                            raise SnapshotError(
                                "ARTIFACT_BYTES_UNAVAILABLE",
                                "synthetic late parent body unavailable",
                            )
                        return read(identity)

                    with monkeypatch.context() as late:
                        late.setattr(artifacts, "read", refuse_late_parent_body)
                        derivation.check_current()
                        with pytest.raises(
                            SnapshotError,
                            match="synthetic late parent body unavailable",
                        ) as raised:
                            admission.current()
                        assert raised.value.code == "ARTIFACT_BYTES_UNAVAILABLE"
            assert result.source_use.scope == source.scope
            assert len(result.activities) == 3
            original = release.read_bytes()
            release.write_bytes(canonical_bytes(reference))
            with pytest.raises(SnapshotError):
                reader.require_candidate_source(
                    source.scope, (reference,), deadline_at=deadline()
                )
            release.write_bytes(original)
            from sqlalchemy import text

            archive_receipt = next(
                item
                for item in source.evidence.outcome.responses
                if item.uri == source.evidence.outcome.integrity.archive_uri
            )

            async def remove_archive_registration(connection):
                await connection.execute(
                    text(
                        "DELETE FROM fundamental.content_objects WHERE content_hash=:digest AND media_type=:media"
                    ),
                    {
                        "digest": archive_receipt.content_hash,
                        "media": archive_receipt.media_type,
                    },
                )

            env.metadata.run_fiscal_admission_history(remove_archive_registration)
            with pytest.raises(SnapshotError):
                reader.require_candidate_source(
                    source.scope, (reference,), deadline_at=deadline()
                )

            async def inspect_privileges_and_registration(connection):
                return tuple(
                    (
                        await connection.execute(
                            text(
                                "SELECT has_table_privilege(current_user,'fundamental.content_objects','INSERT'), has_schema_privilege(current_user,'fundamental','CREATE'), (SELECT count(*) FROM fundamental.content_objects WHERE content_hash=:digest)"
                            ),
                            {"digest": archive_receipt.content_hash},
                        )
                    ).one()
                )

            assert metadata.run_fiscal_admission_history(
                inspect_privileges_and_registration
            ) == (False, False, 0)
        finally:
            metadata.close()


@pytest.mark.parametrize("cut", ["unknown-sign", "durable-before-publication"])
def test_preparation_signing_cuts_never_resign(preparer, monkeypatch, cut):
    runtime, order, env, source = preparer
    original = env.store.put_bytes_with_receipt
    calls = []

    def crash(identity, *args, **kwargs):
        target = (
            ":preparation-signature:signed" if cut == "unknown-sign" else ":preparation"
        )
        if identity.endswith(target) and not calls:
            calls.append(identity)
            raise RuntimeError("source preparation durable cut")
        return original(identity, *args, **kwargs)

    monkeypatch.setattr(env.store, "put_bytes_with_receipt", crash)
    with pytest.raises(RuntimeError, match="durable cut"):
        runtime.run(order.order_id, deadline_at=deadline())
    monkeypatch.setattr(env.store, "put_bytes_with_receipt", original)
    if cut == "unknown-sign":
        with pytest.raises(SnapshotError) as failure:
            runtime.run(order.order_id, deadline_at=deadline())
        assert (
            failure.value.code == "FISCAL_SOURCE_PRODUCER_SIGNING_OUTCOME_UNAVAILABLE"
        )
    else:
        recovered = runtime.run(order.order_id, deadline_at=deadline())
        signed = read_source_preparation(
            FiscalArtifactRead(env.store, lambda: 60), recovered
        )
        assert canonical_bytes(signed) == env.store.read(recovered.artifact_id)
        assert runtime.run(order.order_id, deadline_at=deadline()) == recovered
    assert source.calls == 1


@pytest.mark.parametrize(
    "field,value", [("workload_uid", os.getuid() + 1), ("database_role", "wrong_role")]
)
def test_preparer_requires_actual_os_and_database_workload(preparer, field, value):
    runtime, order, _, source = preparer
    runtime.installation = runtime.installation.model_copy(update={field: value})
    with pytest.raises(SnapshotError, match="workload differs"):
        runtime.run(order.order_id, deadline_at=deadline())
    assert source.calls == 0


def test_source_only_preparation_executes_replays_and_retries_exactly(preparer):
    runtime, order, env, source = preparer
    first = runtime.run(order.order_id, deadline_at=deadline())
    assert first.role == "fiscal-source-preparation-execution-v2"
    signed = read_source_preparation(FiscalArtifactRead(env.store, lambda: 60.0), first)
    assert signed.preparation.mode == "captured_then_replayed"
    assert signed.preparation.request == order.source_request
    assert source.calls == 1
    again = runtime.run(order.order_id, deadline_at=deadline())
    assert first == again
    assert source.calls == 1
    assert runtime.classification_sources is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("audience", "wrong"),
        ("executable_digest", "f" * 64),
        ("deployment_digest", "f" * 64),
        ("authority_id", "synthetic-classifier"),
    ],
)
def test_preparation_rejects_wrong_protected_order_before_work(preparer, field, value):
    runtime, order, _, source = preparer
    path = runtime.installation.orders_directory / (order.order_id + ".json")
    path.write_bytes(canonical_bytes(order.model_copy(update={field: value})))
    with pytest.raises(SnapshotError):
        runtime.run(order.order_id, deadline_at=deadline())
    assert source.calls == 0


def test_malformed_order_is_operational_refusal_before_execution(preparer):
    runtime, order, _, source = preparer
    path = runtime.installation.orders_directory / (order.order_id + ".json")
    path.write_bytes(b'{"role":"classifier",')
    with pytest.raises(SnapshotError) as failure:
        runtime.run(order.order_id, deadline_at=deadline())
    assert failure.value.code == "FISCAL_SOURCE_PRODUCER_INVALID"
    assert source.calls == 0


def test_configured_preparer_separates_closure_writer_from_read_only_content(
    preparer, monkeypatch
):
    from types import SimpleNamespace
    from fundamental_service import fiscal_source_producer_runtime as producer_module

    runtime, _, env, _ = preparer
    monkeypatch.setattr(
        producer_module,
        "load_source_producer_installation",
        lambda role: runtime.installation,
    )
    acquisition = SimpleNamespace(
        capture_store=env.store,
        content_store=env.store._content,
        fiscal_source_closure=lambda **kwargs: runtime.sources,
    )
    configured = producer_module.configured_source_producer_runtime(
        acquisition, env.metadata, role="source_preparer"
    )
    assert configured.sources is runtime.sources
    assert configured.artifacts is env.store
    assert configured.content._read_only
    with pytest.raises(SnapshotError) as refused:
        configured.content.put(b"reader must not publish", media_type="text/plain")
    assert refused.value.code == "READ_ONLY_STORAGE"
