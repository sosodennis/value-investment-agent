from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import os
import pytest
from cryptography.hazmat.primitives import serialization
from pydantic import ValidationError

from fundamental_service.fiscal_candidate_contracts import (
    FiscalPrepareCandidateCommandV1,
)
from fundamental_service.fiscal_preparation_runtime import (
    FiscalPreparationDeploymentV1,
    FiscalPreparationInputs,
    build_fiscal_candidate_runtime,
)
from fundamental_service.serialization import canonical_bytes
from fundamental_service.snapshots import SnapshotError
from test_fiscal_projection_builder import _case, assert_frozen_candidate_projection
import test_fiscal_source_classification as classification_cases
from test_fiscal_admission_authority import change_status

environment = classification_cases.environment


def deadline():
    return datetime.now(UTC) + timedelta(seconds=60)


def key_file(path, key):
    path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    path.chmod(0o600)
    return path


@pytest.fixture
def prepared_runtime(environment, tmp_path):
    env = environment
    source_builder, discovery_ref, _, _, sources = _case(
        tmp_path / "synthetic-retained-source-adapter",
        "aapl-historical",
        artifact_type=lambda _: env.store,
    )
    roster = tmp_path / "synthetic-deployment.json"
    roster.write_bytes(canonical_bytes(env.authorities._configured()))
    trust = tmp_path / "synthetic-mapping-trust.json"
    trust.write_bytes(canonical_bytes(source_builder.mapping_approvals.trust_roots()))
    config = FiscalPreparationDeploymentV1(
        authority_deployment_file=roster,
        candidate_authority_id="synthetic-source_preparer",
        mapping_trust_roots_file=trust,
        candidate_private_key_file=key_file(
            tmp_path / "synthetic-candidate.pem", env.preparer_key
        ),
        mapping_private_key_file=key_file(
            tmp_path / "synthetic-mapping.pem",
            source_builder.mapping_approvals.private_key(),
        ),
    )
    inputs = FiscalPreparationInputs(
        env.store,
        source_builder.content,
        source_builder.discovery,
        source_builder.sources,
        source_builder.pin,
        None,
    )
    builder = build_fiscal_candidate_runtime(inputs, env.metadata, config, write=True)
    command = FiscalPrepareCandidateCommandV1(
        command_id="synthetic-candidate",
        discovery_ref=discovery_ref,
        security_id="AAPL",
        expires_at=datetime.now(UTC) + timedelta(minutes=10),
    )
    try:
        yield env, inputs, config, builder, command, sources
    finally:
        import shutil

        for protected in getattr(env, "producer_protected_directories", ()):
            shutil.rmtree(protected)


def test_real_factory_prepares_reads_retries_and_refuses_nonfirst_source(
    prepared_runtime, monkeypatch
):
    env, inputs, config, builder, command, sources = prepared_runtime
    first = builder.prepare(command, deadline_at=deadline())
    assert first.candidate_publication.wrote
    assert_frozen_candidate_projection(first, "aapl-historical")
    assert len(first.content.source_uses) > 1
    assert first.preparation.principal_kind == "machine"
    assert all(proof.source_use.kind == "raw_pass" for proof in first.source_evidence)
    assert all(not hasattr(proof, "activities") for proof in first.source_evidence)
    original = env.store.read(first.reference.artifact_id)
    again = builder.prepare(command, deadline_at=deadline())
    assert not again.candidate_publication.wrote
    assert again.reference == first.reference
    assert canonical_bytes(again.candidate) == original
    read_config = config.model_copy(
        update={"candidate_private_key_file": None, "mapping_private_key_file": None}
    )
    reader = build_fiscal_candidate_runtime(
        inputs, env.metadata, read_config, write=False
    )
    assert not hasattr(reader.mapping_approvals, "approve")
    assert not hasattr(reader.preparation.history, "append_once")

    def forbidden(*args, **kwargs):
        raise AssertionError("pure candidate read attempted a write or signature")

    monkeypatch.setattr(env.store, "put_with_receipt", forbidden)
    monkeypatch.setattr(env.store, "put_bytes_with_receipt", forbidden)
    loaded = reader.verify_candidate(first.reference, deadline_at=deadline())
    assert loaded.reference == first.reference
    assert loaded.content == first.content
    other = list(sources)[-1]
    assert other != list(sources)[0]
    change_status(env, other, "invalidated")
    with pytest.raises(SnapshotError):
        reader.verify_candidate(first.reference, deadline_at=deadline())
    assert env.store.read(first.reference.artifact_id) == original


def test_refs_only_candidate_command_rejects_financial_or_actor_input(prepared_runtime):
    _, _, _, _, command, _ = prepared_runtime
    for key in (
        "rows",
        "principal_id",
        "key_id",
        "issuance",
        "execution_id",
        "content",
        "formula",
    ):
        with pytest.raises(ValidationError):
            FiscalPrepareCandidateCommandV1.model_validate(
                {**command.model_dump(), key: "caller-claim"}
            )


def test_same_command_changed_expiry_refuses_before_new_invocation(prepared_runtime):
    _, _, _, builder, command, _ = prepared_runtime
    first = builder.prepare(command, deadline_at=deadline())
    with pytest.raises(SnapshotError) as failure:
        builder.prepare(
            command.model_copy(
                update={"expires_at": command.expires_at + timedelta(seconds=1)}
            ),
            deadline_at=deadline(),
        )
    assert failure.value.code == "FISCAL_CANDIDATE_COMMAND_REUSED"
    assert builder.artifacts.read(first.reference.artifact_id) == canonical_bytes(
        first.candidate
    )


@pytest.mark.parametrize(
    "cut", ["intent", "signing-intent", "signed", "checkpoint", "control"]
)
def test_durable_crash_cuts_preserve_bytes_and_unknown_signing_refuses(
    prepared_runtime, monkeypatch, cut
):
    env, _, _, builder, command, _ = prepared_runtime
    history = builder.preparation.history
    put = env.store.put_with_receipt
    checkpoint = history.checkpoint
    append = history.append_once
    crashed = False

    def publication(identity, *args, **kwargs):
        nonlocal crashed
        result = put(identity, *args, **kwargs)
        prefix = {
            "intent": "fiscal-candidate-intent-v1:",
            "signing-intent": "fiscal-candidate-signing-intent-v1:",
            "signed": "fiscal-statement-candidate-v2:",
        }.get(cut)
        if prefix and identity.startswith(prefix) and not crashed:
            crashed = True
            raise RuntimeError("synthetic process loss after durable publication")
        return result

    def history_cut(original, stage, *args, **kwargs):
        nonlocal crashed
        result = original(*args, **kwargs)
        if cut == stage and not crashed:
            crashed = True
            raise RuntimeError("synthetic process loss after durable history")
        return result

    monkeypatch.setattr(env.store, "put_with_receipt", publication)
    monkeypatch.setattr(
        history,
        "checkpoint",
        lambda *a, **kw: history_cut(checkpoint, "checkpoint", *a, **kw),
    )
    monkeypatch.setattr(
        history,
        "append_once",
        lambda *a, **kw: history_cut(append, "control", *a, **kw),
    )
    with pytest.raises(RuntimeError):
        builder.prepare(command, deadline_at=deadline())
    assert crashed
    monkeypatch.setattr(env.store, "put_with_receipt", put)
    monkeypatch.setattr(history, "checkpoint", checkpoint)
    monkeypatch.setattr(history, "append_once", append)
    if cut == "signing-intent":
        with pytest.raises(SnapshotError) as failure:
            builder.prepare(command, deadline_at=deadline())
        assert failure.value.code == "FISCAL_CANDIDATE_SIGNING_OUTCOME_UNAVAILABLE"
    else:
        result = builder.prepare(command, deadline_at=deadline())
        assert result.candidate_publication.wrote is (cut == "intent")
        assert (
            builder.verify_candidate(result.reference, deadline_at=deadline()).reference
            == result.reference
        )


def synthetic_retained_classifications(
    env, source_builder, discovery_ref, bindings, sources
):
    import hashlib
    import tempfile
    from contextlib import nullcontext
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from fundamental_service.artifact_evidence import read_retained_artifact
    from fundamental_service.fiscal_candidate_contracts import (
        FiscalCandidateClassificationBindingV1,
    )
    from fundamental_service.fiscal_classification_source import (
        FiscalClassificationSourceResolver,
    )
    from fundamental_service.fiscal_focus_witness import (
        FiscalDiagnosticFocusWitnessV1,
        SignedFiscalDiagnosticFocusWitnessV1,
        FiscalFocusActionBindingV1,
    )
    from fundamental_service.fiscal_diagnostic_focus import ArelleActualFocusFactV1
    from fundamental_service.fiscal_source_accounting_policy import (
        source_accounting_policy_identity,
    )
    from fundamental_service.fiscal_source_closure import FiscalSourceClosure
    from fundamental_service.fiscal_source_preparation import (
        fiscal_source_producer_executable_digest,
    )
    from fundamental_service.fiscal_source_producer_contracts import (
        FiscalAccountingAccreditationV1,
        FiscalProducerOrderV1,
    )
    from fundamental_service.fiscal_source_producer_runtime import (
        FiscalSourceProducerInstallationV1,
        FiscalSourceProducerRuntime,
        producer_reference,
        public_accounting_accreditation_provider,
    )
    from fundamental_service.parser_action_contracts import (
        ParserActionResultV2,
        ParserActionDeliveryV2,
    )
    from fundamental_service.sec_capture import sec_response_artifact_id
    from fundamental_service.serialization import sha256_digest
    from fundamental_service.arelle_parser import fact_semantic_digest
    from test_fiscal_source_producer_runtime import (
        RetainedDiscoveryAdapter,
        RetainedSECAdapter,
    )
    from types import SimpleNamespace

    root = Path(os.environ["ISSUE495_RETAINED_EVIDENCE_ROOT"])
    parent = Path(os.environ.get("ISSUE495_PRODUCER_PROTECTED_TEMP", str(Path.home())))
    protected = Path(tempfile.mkdtemp(prefix="issue495-mixed-v2-", dir=parent))
    env.producer_protected_directories = [
        *getattr(env, "producer_protected_directories", ()),
        protected,
    ]
    orders = protected / "orders"
    orders.mkdir(mode=0o700)
    roster = protected / "deployment.json"
    roster.write_bytes(canonical_bytes(env.authorities._configured()))
    preparer_key = key_file(protected / "preparer.pem", env.preparer_key)
    classifier_key = key_file(protected / "classifier.pem", env.signer.key)
    independent = (
        root / "source-policy-token-amended-review/independent-61/remaining-review.md"
    ).read_bytes()
    independent_ref = producer_reference(
        env.store.put_bytes_with_receipt(
            "retained-policy-independent-review",
            independent,
            (),
            media_type="text/markdown",
        ).artifact,
        "independent-accounting-policy-review",
    )
    now = datetime.now(UTC)
    accreditation = FiscalAccountingAccreditationV1(
        policy=source_accounting_policy_identity(),
        independent_review_ref=independent_ref,
        classifier_executable_digest=fiscal_source_producer_executable_digest(),
        valid_from=now - timedelta(minutes=1),
        valid_until=now + timedelta(hours=1),
    )
    accreditation_ref = producer_reference(
        env.store.put_with_receipt(
            "mixed-ephemeral-policy-accreditation", accreditation
        ).artifact,
        "fiscal-accounting-accreditation-v1",
    )
    release = protected / "accounting-release.json"
    release.write_bytes(canonical_bytes(accreditation_ref))
    provider = public_accounting_accreditation_provider(release, owner=os.getuid())
    discovery = source_builder.discovery.read(
        discovery_ref.artifact_id, deadline_at=deadline()
    )
    focus_key = Ed25519PrivateKey.generate()
    witnesses = {}

    class RetainedSyntheticWitnesses:
        def observe(self, identity, *, deadline_at):
            from copy import deepcopy

            owner = self
            original = deepcopy(self.read(identity, deadline_at=deadline_at))

            class Read:
                @property
                def witness(self):
                    return deepcopy(original)

                @property
                def records(self):
                    return ((identity, env.store.get(identity)),)

                def check_current(self):
                    assert owner.read(identity, deadline_at=deadline_at) == original
                    assert datetime.now(UTC) < deadline_at

            return Read()

        def read(self, identity, *, deadline_at):
            value = witnesses[identity]
            assert read_retained_artifact(
                env.store,
                producer_reference(
                    env.store.get(identity), "fiscal-diagnostic-focus-witness-v1"
                ),
            ) == canonical_bytes(value)
            focus_key.public_key().verify(
                bytes.fromhex(value.signature), value.signing_bytes()
            )
            assert datetime.now(UTC) < value.expires_at
            return value

    new_bindings = []
    resolver = None
    for binding in bindings:
        evidence = sources[binding.source_validation_ref.artifact_id]
        outcome = evidence.outcome
        assert (
            evidence.request.pin.declared_source_revision
            == "293c068cc8cca6a4329b13a21f88ce93c1b47326"
        )
        recovered = root / "retained-293-content-recovery/content"
        for ref in outcome.action_refs:
            raw = (
                recovered / ref.content_hash[:2] / (ref.content_hash + ".json")
            ).read_bytes()
            assert hashlib.sha256(raw).hexdigest() == ref.content_hash
            env.store.put_bytes_with_receipt(
                ref.artifact_id, raw, (), media_type=ref.media_type
            )
        results = [
            ParserActionResultV2.model_validate_json(env.store.read(ref.artifact_id))
            for ref in outcome.action_refs
            if ref.role == "sec-parser-action-result-v2"
        ]
        deliveries = {
            value.action_key: value
            for ref in outcome.action_refs
            if ref.role == "sec-parser-action-delivery-v2"
            for value in [
                ParserActionDeliveryV2.model_validate_json(
                    env.store.read(ref.artifact_id)
                )
            ]
        }
        refs = {ref.artifact_id: ref for ref in outcome.action_refs}
        actions = tuple(
            FiscalFocusActionBindingV1(
                representation=result.request.representation,
                request=result.request,
                result_ref=refs[result.artifact_id],
                report_ref=next(
                    ref
                    for ref in outcome.action_refs
                    if ref.role == "sec-parser-action-report-v1"
                    and ref.content_hash == result.report_content_hash
                ),
                delivery_ref=next(
                    ref
                    for ref in outcome.action_refs
                    if ref.role == "sec-parser-action-delivery-v2"
                    and ref.content_hash
                    == sha256_digest(deliveries[result.request.digest])
                ),
                delivery=deliveries[result.request.digest],
                report_digest=result.report_content_hash,
            )
            for result in results
        )
        report = outcome.claim.report
        from lxml import etree
        from fundamental_service.ingestion import read_sec_xbrl_archive

        candidates = [
            fact
            for fact in report.facts
            if fact.concept == "us-gaap:ShortTermInvestments"
            and fact.instant == evidence.request.filing.report_period_end
            and any(
                member.endswith(":DerivativeMember") for _, member in fact.dimensions
            )
        ]
        assert len(candidates) == 1
        fact = candidates[0]
        receipt = next(
            item
            for item in outcome.responses
            if item.uri == outcome.integrity.archive_uri
        )
        archive = source_builder.content.get(
            receipt.content_hash, media_type=receipt.media_type
        )
        content = env.store._content
        from test_fiscal_source_producer_runtime import populate_retained_content

        populate_retained_content(
            SimpleNamespace(evidence=evidence, archive=archive), content, root
        )
        primary = read_sec_xbrl_archive(
            archive,
            primary_document=evidence.request.filing.primary_document,
            dts_filenames=(),
        )[evidence.request.filing.primary_document]
        document = etree.fromstring(
            primary,
            etree.XMLParser(resolve_entities=False, no_network=True, recover=False),
        )
        matches = document.xpath(
            "//*[@name=$concept][@contextRef=$context]",
            concept=fact.concept,
            context=fact.context_id,
        )
        assert len(matches) == 1
        actual_focus = ArelleActualFocusFactV1(
            fact_id=matches[0].get("id"), fact=fact, numeric_value=fact.value
        )
        body = FiscalDiagnosticFocusWitnessV1(
            source_validation_ref=binding.source_validation_ref,
            request_digest=evidence.request.digest,
            filing=evidence.request.filing,
            cutoff=evidence.request.valuation_timestamp,
            source_available_at=outcome.claim.source.available_at,
            integrity=outcome.integrity,
            runtime=outcome.runtime,
            source_responses=outcome.responses,
            raw_report_digest=sha256_digest(report.model_dump(mode="json")),
            raw_report_fact_digest=fact_semantic_digest(report),
            raw_report_findings_digest=sha256_digest(
                sorted(report.findings, key=sha256_digest)
            ),
            raw_finding=next(
                item for item in report.findings if item.code == "DQC.US.0015.5970"
            ),
            actions=actions,
            filing_context=report.dqc_filing_context,
            actual_focus=actual_focus,
            worker_module_sha256="a" * 64,
            applicability_policy_digest=report.dqc_filing_context.policy_digest,
        )
        witness = SignedFiscalDiagnosticFocusWitnessV1(
            witness=body,
            authority_id="ephemeral-retained-focus",
            principal_id="machine:ephemeral-retained-focus",
            key_id=hashlib.sha256(
                focus_key.public_key().public_bytes_raw()
            ).hexdigest(),
            signed_at=now,
            expires_at=now + timedelta(hours=1),
            signature="0" * 128,
        )
        witness = witness.model_copy(
            update={"signature": focus_key.sign(witness.signing_bytes()).hex()}
        )
        witness_ref = producer_reference(
            env.store.put_with_receipt(witness.artifact_id, witness).artifact,
            "fiscal-diagnostic-focus-witness-v1",
        )
        witnesses[witness.artifact_id] = witness
        env.store.put_with_receipt(
            evidence.request.artifact_id,
            evidence.request,
            (discovery_ref.content_hash,),
        )
        for receipt in outcome.responses:
            env.store.put_with_receipt(
                sec_response_artifact_id(evidence.request.scope, receipt.uri),
                receipt,
                (receipt.content_hash,),
            )
        discovery_adapter = RetainedDiscoveryAdapter(discovery, evidence, env.store)
        closure = FiscalSourceClosure(
            discovery=discovery_adapter,
            artifacts=env.store,
            pin=evidence.request.pin,
            source=RetainedSECAdapter(evidence),
            capture_lock=lambda key, at: nullcontext(),
        )
        resolver = FiscalClassificationSourceResolver(
            sources=closure,
            discovery=source_builder.discovery,
            witnesses=RetainedSyntheticWitnesses(),
            content=content.as_read_only(),
        )
        resolver.accounting_accreditation = provider
        resolver.accounting_release_file = release
        installed = FiscalSourceProducerInstallationV1(
            role="source_preparer",
            audience="ephemeral-mixed-preparer",
            authority_id="synthetic-source_preparer",
            workload_uid=os.getuid(),
            deployment_uid=os.getuid(),
            database_role="fundamental",
            deployment_file=roster,
            orders_directory=orders,
            private_key_file=preparer_key,
            source_configuration_files=(),
            declared_source_revision=evidence.request.pin.declared_source_revision,
            executable_digest=fiscal_source_producer_executable_digest(),
        )
        preparation_order = FiscalProducerOrderV1(
            order_id="mixed-prepare",
            role="source_preparer",
            audience=installed.audience,
            authority_id=installed.authority_id,
            deployment_digest=sha256_digest(env.authorities._configured()),
            executable_digest=installed.executable_digest,
            issuance=env.history.read_epoch(deadline_at=deadline()).issuance_context,
            source_request=evidence.request.selection,
            valid_from=now - timedelta(seconds=1),
            expires_at=now + timedelta(minutes=30),
        )
        (orders / "mixed-prepare.json").write_bytes(canonical_bytes(preparation_order))
        runtime = FiscalSourceProducerRuntime(
            installation=installed,
            artifacts=env.store,
            metadata=env.metadata,
            sources=closure,
            content=content.as_read_only(),
            classification_sources=None,
        )
        preparation_ref = runtime.run(
            preparation_order.order_id, deadline_at=deadline()
        )
        classifier_installation = installed.model_copy(
            update={
                "role": "classifier",
                "audience": "ephemeral-mixed-classifier",
                "authority_id": "synthetic-classifier",
                "private_key_file": classifier_key,
                "accreditation_file": release,
            }
        )
        classification_order = FiscalProducerOrderV1(
            order_id="mixed-classify",
            role="classifier",
            audience=classifier_installation.audience,
            authority_id=classifier_installation.authority_id,
            deployment_digest=preparation_order.deployment_digest,
            executable_digest=installed.executable_digest,
            issuance=preparation_order.issuance,
            preparation_ref=preparation_ref,
            witness_ref=witness_ref,
            security_id="MSFT",
            valid_from=preparation_order.valid_from,
            expires_at=preparation_order.expires_at,
        )
        (orders / "mixed-classify.json").write_bytes(
            canonical_bytes(classification_order)
        )
        classifier = FiscalSourceProducerRuntime(
            installation=classifier_installation,
            artifacts=env.store,
            metadata=env.metadata,
            sources=closure,
            content=content.as_read_only(),
            classification_sources=resolver,
        )
        publication = classifier.run(
            classification_order.order_id, deadline_at=deadline()
        )
        assert hasattr(publication, "signed_classification"), (
            "real accounting policy must support this retained source"
        )
        classified_ref = producer_reference(
            publication.publication.artifact, "fiscal-source-classification-v2"
        )
        new_bindings.append(
            FiscalCandidateClassificationBindingV1(
                source_validation_ref=binding.source_validation_ref,
                witness_ref=witness_ref,
                classification_refs=(classified_ref,),
            )
        )
    assert resolver is not None
    return resolver, tuple(
        sorted(
            new_bindings, key=lambda binding: binding.source_validation_ref.artifact_id
        )
    )


@pytest.mark.parametrize("case_id", ["msft-historical", "msft-current"])
def test_mixed_source_factory_preserves_verified_classification_activities(
    prepared_runtime, tmp_path, case_id
):
    env, _, config, _, _, _ = prepared_runtime
    source_builder, discovery_ref, bindings, _, sources = _case(
        tmp_path / "synthetic-msft",
        case_id,
        artifact_type=lambda _: env.store,
    )
    resolver, actual_bindings = synthetic_retained_classifications(
        env, source_builder, discovery_ref, bindings, sources
    )
    config.mapping_trust_roots_file.write_bytes(
        canonical_bytes(source_builder.mapping_approvals.trust_roots())
    )
    key_file(
        config.mapping_private_key_file, source_builder.mapping_approvals.private_key()
    )
    inputs = FiscalPreparationInputs(
        env.store,
        source_builder.content,
        source_builder.discovery,
        source_builder.sources,
        source_builder.pin,
        resolver,
        accounting_accreditation=resolver.accounting_accreditation,
    )
    builder = build_fiscal_candidate_runtime(inputs, env.metadata, config, write=True)
    command = FiscalPrepareCandidateCommandV1(
        command_id="synthetic-mixed",
        discovery_ref=discovery_ref,
        security_id="MSFT",
        classification_bindings=actual_bindings,
        expires_at=datetime.now(UTC) + timedelta(minutes=10),
    )
    first = builder.prepare(command, deadline_at=deadline())
    assert_frozen_candidate_projection(first, case_id)
    classified = [
        proof
        for proof in first.source_evidence
        if proof.source_use.kind == "classified_provisional"
    ]
    raw = [
        proof for proof in first.source_evidence if proof.source_use.kind == "raw_pass"
    ]
    assert raw and len(classified) == 1
    assert len(classified[0].activities) == 3
    assert classified[0].activities[1].principal_kind is None
    original = canonical_bytes(first.candidate)
    assert builder.prepare(command, deadline_at=deadline()).reference == first.reference
    readonly = build_fiscal_candidate_runtime(inputs, env.metadata, config, write=False)
    assert (
        readonly.verify_candidate(first.reference, deadline_at=deadline()).content
        == first.content
    )
    change_status(
        env, actual_bindings[0].classification_refs[0].artifact_id, "invalidated"
    )
    with pytest.raises(SnapshotError):
        readonly.verify_candidate(first.reference, deadline_at=deadline())
    assert env.store.read(first.reference.artifact_id) == original


@pytest.mark.parametrize(
    "dependency",
    [
        "last-source",
        "last-mapping",
        "projection",
        "grant",
        "head",
        "epoch",
        "expiry",
        "roster",
        "storage",
    ],
)
def test_success_exit_rechecks_last_dependency_and_whole_snapshot(
    prepared_runtime, monkeypatch, dependency
):
    from sqlalchemy import text
    from uuid import uuid4

    env, _, config, builder, command, sources = prepared_runtime
    result = builder.prepare(command, deadline_at=deadline())
    original = env.store.read(result.reference.artifact_id)
    history = builder.preparation.history
    finish = history.finish_observation

    def racing(records, heads, epoch, *, deadline_at):
        if dependency in {"last-source", "last-mapping", "projection", "grant"}:
            identity = {
                "last-source": list(sources)[-1],
                "last-mapping": result.content.mapping_refs[-1].artifact_id,
                "projection": result.content.projection_ref.artifact_id,
                "grant": result.preparation.grant_ref.artifact_id,
            }[dependency]
            change_status(env, identity, "invalidated")
        elif dependency == "head":
            from fundamental_service.fiscal_authority_contracts import (
                FiscalRevokeAuthorityCommandV1,
            )

            current = env.authorities.read_current(
                "synthetic-source_preparer",
                expected_role="source_preparer",
                deadline_at=deadline(),
            )
            env.authorities.revoke(
                FiscalRevokeAuthorityCommandV1(
                    command_id="synthetic-revoke-race",
                    authority_id="synthetic-source_preparer",
                    grant_ref=current.grant_ref,
                    reason="synthetic exit race",
                ),
                expected_head=next(
                    head
                    for head in current.history_heads
                    if head.stream_kind == "control"
                ),
                deadline_at=deadline(),
            )
        elif dependency == "epoch":
            epoch = epoch.model_copy(update={"local_origin_id": str(uuid4())})
        elif dependency == "expiry":
            builder.preparation.clock = lambda: command.expires_at
        elif dependency == "roster":
            config.authority_deployment_file.write_bytes(
                config.authority_deployment_file.read_bytes() + b"\n"
            )
        elif dependency == "storage":

            async def remove(connection):
                await connection.execute(
                    text(
                        "DELETE FROM fundamental.content_objects WHERE content_hash=:digest AND media_type=:media"
                    ),
                    {
                        "digest": result.content.projection_ref.content_hash,
                        "media": "application/json",
                    },
                )

            env.metadata.run_fiscal_admission_history(remove)
        return finish(records, heads, epoch, deadline_at=deadline_at)

    monkeypatch.setattr(history, "finish_observation", racing)
    with pytest.raises(SnapshotError):
        builder.verify_candidate(result.reference, deadline_at=deadline())
    assert env.store.read(result.reference.artifact_id) == original


def test_parent_metadata_budget_cancels_candidate_before_any_issuance(prepared_runtime):
    from time import monotonic
    from fundamental_service.metadata import metadata_operation_budget

    env, _, _, builder, command, _ = prepared_runtime
    started = monotonic()
    with metadata_operation_budget(
        lambda: 0.001,
        lambda: SnapshotError("SYNTHETIC_PARENT_DEADLINE", "parent budget ended"),
    ):
        with pytest.raises(SnapshotError):
            builder.prepare(command, deadline_at=deadline())
    assert monotonic() - started < 3
    with pytest.raises(SnapshotError):
        env.store.get(command.artifact_id("fiscal-statement-candidate-v2"))


def test_wrong_deployment_key_refuses_before_financial_work(
    prepared_runtime, monkeypatch
):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    env, _, config, builder, command, _ = prepared_runtime
    key_file(config.candidate_private_key_file, Ed25519PrivateKey.generate())

    def forbidden(*args, **kwargs):
        raise AssertionError("wrong candidate key entered the financial builder")

    monkeypatch.setattr(builder, "_build", forbidden)
    with pytest.raises(SnapshotError) as failure:
        builder.prepare(command, deadline_at=deadline())
    assert failure.value.code == "FISCAL_CANDIDATE_INVALID"
    with pytest.raises(SnapshotError):
        env.store.get(command.artifact_id("fiscal-candidate-signing-intent-v1"))


def test_read_refuses_unsigned_opaque_or_source_only_envelope(prepared_runtime):
    from test_fiscal_admission_authority import reference

    env, _, _, builder, _, _ = prepared_runtime
    for protocol in (
        "synthetic-opaque-json",
        "fundamental.signed-fiscal-source-preparation-execution.v1",
    ):
        artifact = env.store.put_with_receipt(
            "synthetic-wrong-envelope:" + protocol,
            {"protocol": protocol, "execution_id": "caller-claim"},
        )
        with pytest.raises(SnapshotError):
            builder.verify_candidate(
                reference(artifact.artifact, "fiscal-statement-candidate-v2"),
                deadline_at=deadline(),
            )


@pytest.mark.parametrize(
    "axis",
    [
        "issuer",
        "cutoff",
        "source-set",
        "mapping",
        "projection",
        "period",
        "lineage",
        "policy",
        "executable",
        "materialization",
        "precision",
        "principal-kind",
        "preparation-build",
        "signature",
    ],
)
def test_even_correctly_signed_candidate_tampering_never_bypasses_reconstruction(
    prepared_runtime, axis
):
    from fundamental_service.fiscal_candidate_contracts import (
        FiscalStatementCandidateV2,
    )
    from fundamental_service.serialization import sha256_digest
    from test_fiscal_admission_authority import reference

    env, _, _, builder, command, _ = prepared_runtime
    result = builder.prepare(command, deadline_at=deadline())
    body = result.candidate.body
    content = body.content
    command = body.command.model_copy(
        update={"command_id": "synthetic-tampered-" + axis}
    )
    if axis == "issuer":
        content = content.model_copy(
            update={
                "scope": content.scope.model_copy(update={"issuer_id": "0000789019"})
            }
        )
    elif axis == "cutoff":
        content = content.model_copy(
            update={"cutoff_at": content.cutoff_at + timedelta(seconds=1)}
        )
    elif axis == "source-set":
        uses = content.source_uses[:-1]
        content = content.model_copy(
            update={"source_uses": uses, "source_set_digest": sha256_digest(uses)}
        )
    elif axis == "mapping":
        content = content.model_copy(update={"mapping_refs": content.mapping_refs[:-1]})
    elif axis == "projection":
        content = content.model_copy(
            update={
                "projection_ref": content.projection_ref.model_copy(
                    update={"content_hash": "0" * 64}
                )
            }
        )
    elif axis in {"period", "lineage", "policy", "executable"}:
        field = {
            "period": "period_set_digest",
            "lineage": "row_lineage_digest",
            "policy": "projection_policy_digest",
            "executable": "executable_digest",
        }[axis]
        content = content.model_copy(update={field: "0" * 64})
    elif axis == "materialization":
        content = content.model_copy(
            update={
                "materialization": content.materialization.model_copy(
                    update={"declared_source_revision": "0" * 40}
                )
            }
        )
    elif axis == "precision":
        use = content.source_uses[-1]
        observations = use.scope.permitted_inputs
        scope = use.scope.model_copy(
            update={
                "permitted_inputs": (
                    observations[0].model_copy(update={"decimals": -1}),
                    *observations[1:],
                )
            }
        )
        uses = (*content.source_uses[:-1], use.model_copy(update={"scope": scope}))
        content = content.model_copy(
            update={"source_uses": uses, "source_set_digest": sha256_digest(uses)}
        )
    execution_updates = {
        "content_digest": content.content_digest,
        "command_digest": command.command_digest,
    }
    if axis == "principal-kind":
        execution_updates["principal_kind"] = "human"
    if axis == "preparation-build":
        execution_updates["preparation_executable_digest"] = "0" * 64
    body = body.model_copy(
        update={
            "command": command,
            "content": content,
            "preparation": body.preparation.model_copy(update=execution_updates),
        }
    )
    signed = FiscalStatementCandidateV2(
        body=body,
        signature=(
            "0" * 128
            if axis == "signature"
            else env.preparer_key.sign(canonical_bytes(body)).hex()
        ),
    )
    record = env.store.put_with_receipt(signed.artifact_id, signed).artifact
    with pytest.raises(SnapshotError):
        builder.verify_candidate(
            reference(record, "fiscal-statement-candidate-v2"), deadline_at=deadline()
        )
    assert env.store.read(result.reference.artifact_id) == canonical_bytes(
        result.candidate
    )


def test_second_process_same_command_lease_never_signs_concurrently(
    prepared_runtime, tmp_path
):
    import subprocess
    import sys
    from fundamental_service.serialization import sha256_digest

    env, _, config, builder, command, _ = prepared_runtime
    command_path = tmp_path / "synthetic-command.json"
    config_path = tmp_path / "synthetic-runtime.json"
    command_path.write_bytes(canonical_bytes(command))
    config_path.write_text(config.model_dump_json())
    script = """
import sys
from pathlib import Path
from datetime import UTC, datetime, timedelta
from fundamental_service.fiscal_preparation_runtime import FiscalPreparationDeploymentV1, FiscalPreparationInputs, build_fiscal_candidate_runtime
from fundamental_service.fiscal_candidate_contracts import FiscalPrepareCandidateCommandV1
from fundamental_service.metadata import PostgresMetadataStore, PostgresArtifactStore, PostgresContentStore
from fundamental_service.snapshots import SnapshotError
from test_fiscal_projection_builder import _case, assert_frozen_candidate_projection
metadata=PostgresMetadataStore(sys.argv[1],auto_migrate=False)
metadata.start()
try:
    store=PostgresArtifactStore(metadata,PostgresContentStore(Path(sys.argv[2]),metadata))
    source,_,_,_,_=_case(Path(sys.argv[3]),'aapl-historical',artifact_type=lambda _:store)
    inputs=FiscalPreparationInputs(store,source.content,source.discovery,source.sources,source.pin,None)
    builder=build_fiscal_candidate_runtime(inputs,metadata,FiscalPreparationDeploymentV1.model_validate_json(Path(sys.argv[4]).read_bytes()),write=True)
    command=FiscalPrepareCandidateCommandV1.model_validate_json(Path(sys.argv[5]).read_bytes())
    result=builder.prepare(command,deadline_at=datetime.now(UTC)+timedelta(seconds=60))
    print(result.reference.model_dump_json())
except SnapshotError as error:
    print(error.code)
    sys.exit(2)
finally:
    metadata.close()
"""
    lock_key = sha256_digest(("fiscal-candidate", command.command_id))
    lease = env.metadata.try_acquire_ingestion_lock(lock_key)
    assert lease is not None
    args = [
        sys.executable,
        "-c",
        script,
        env.database_url,
        str(tmp_path / "pg-content"),
        str(tmp_path / "child"),
        str(config_path),
        str(command_path),
    ]
    child_env = {
        **os.environ,
        "PYTHONPATH": str(Path(__file__).parent)
        + os.pathsep
        + os.environ.get("PYTHONPATH", ""),
    }
    try:
        rejected = subprocess.run(
            args, capture_output=True, text=True, timeout=60, env=child_env
        )
        assert rejected.returncode == 2, rejected.stderr
        assert rejected.stdout.strip() == "FISCAL_CANDIDATE_IN_FLIGHT"
    finally:
        env.metadata.release_ingestion_lock(lease)
    result = builder.prepare(command, deadline_at=deadline())
    original = env.store.read(result.reference.artifact_id)
    replay = subprocess.run(
        args, capture_output=True, text=True, timeout=60, env=child_env
    )
    assert replay.returncode == 0, replay.stdout + replay.stderr
    assert result.reference.model_dump_json() in replay.stdout
    assert env.store.read(result.reference.artifact_id) == original


@pytest.mark.parametrize("orphan", [False, True])
def test_restored_candidate_orphan_keeps_issuance_and_fresh_local_command_really_runs(
    prepared_runtime, tmp_path, monkeypatch, orphan
):
    from dataclasses import replace
    from test_fiscal_current_epoch import recovered, regrant
    from test_fiscal_projection_builder import SyntheticRetainedSourcePort
    from test_fiscal_admission_authority import reference

    env, inputs, config, builder, command, sources = prepared_runtime
    if orphan:
        with monkeypatch.context() as patch:
            patch.setattr(
                builder.preparation.history,
                "append_once",
                lambda *a, **kw: (_ for _ in ()).throw(
                    RuntimeError("synthetic pre-backup orphan")
                ),
            )
            with pytest.raises(RuntimeError):
                builder.prepare(command, deadline_at=deadline())
        ref = reference(
            env.store.get(command.artifact_id("fiscal-statement-candidate-v2")),
            "fiscal-statement-candidate-v2",
        )
    else:
        ref = builder.prepare(command, deadline_at=deadline()).reference
    original = env.store.read(ref.artifact_id)
    with recovered(
        env.database_url,
        tmp_path / "pg-content",
        env.authorities._configured(),
        env.authorities._signer,
        tmp_path,
    ) as target:
        restored_inputs = replace(
            inputs,
            artifacts=target.store,
            sources=SyntheticRetainedSourcePort(sources, target.store),
        )
        restored = build_fiscal_candidate_runtime(
            restored_inputs, target.metadata, config, write=True
        )
        with pytest.raises(SnapshotError):
            restored.verify_candidate(ref, deadline_at=deadline())
        regrant(target, env.grants["source_preparer"])
        with pytest.raises(SnapshotError):
            restored.prepare(command, deadline_at=deadline())
        assert target.store.read(ref.artifact_id) == original
        fresh_command = command.model_copy(
            update={"command_id": "synthetic-fresh-local-candidate"}
        )
        fresh = restored.prepare(fresh_command, deadline_at=deadline())
        assert (
            fresh.candidate.body.issuance.origin_id == target.receipt.target_origin_id
        )
        assert (
            fresh.candidate.body.preparation.started_at
            > target.receipt.activation.visible_by
        )
        assert fresh.candidate.body.preparation.execution_id not in original.decode()
        assert (
            restored.verify_candidate(fresh.reference, deadline_at=deadline()).reference
            == fresh.reference
        )
        assert target.store.read(ref.artifact_id) == original


def test_fiscal_runner_prepare_and_exact_ref_read_use_real_factory_results(
    prepared_runtime, tmp_path, monkeypatch, capsys
):
    import json
    from contextlib import asynccontextmanager
    from types import SimpleNamespace
    from fastapi import FastAPI
    import fundamental_service.app as app_module
    import fundamental_service.fiscal_source_runner as runner
    from test_fiscal_admission_authority import reference

    env, inputs, config, builder, command, _ = prepared_runtime
    readonly = build_fiscal_candidate_runtime(inputs, env.metadata, config, write=False)

    @asynccontextmanager
    async def lifespan(app):
        app.state.fiscal_sec_acquisition = object()
        app.state.application = SimpleNamespace(ready=True)
        app.state.metadata_store = env.metadata
        yield

    transport_app = FastAPI(lifespan=lifespan)
    transport_app.state.read_only_operator_lifespan = lifespan
    monkeypatch.setattr(app_module, "app", transport_app)
    monkeypatch.setattr(
        runner,
        "configured_fiscal_candidate_runtime",
        lambda *args, write, **kwargs: builder if write else readonly,
    )
    command_path = tmp_path / "runner-command.json"
    ref_path = tmp_path / "runner-ref.json"
    command_path.write_bytes(canonical_bytes(command))
    common = [
        "--source-revision",
        inputs.pin.declared_source_revision,
        "--timeout-seconds",
        "60",
    ]
    assert (
        runner.main([*common, "prepare-candidate", "--command-file", str(command_path)])
        == 0
    )
    first = json.loads(capsys.readouterr().out)
    ref = reference(
        env.store.get(first["publication"]["artifact"]["artifact_id"]),
        "fiscal-statement-candidate-v2",
    )
    ref_path.write_bytes(canonical_bytes(ref))
    assert (
        runner.main([*common, "read-candidate", "--candidate-ref-file", str(ref_path)])
        == 0
    )
    second = json.loads(capsys.readouterr().out)
    assert first["evidence"] == second["evidence"]
    assert first["publication"]["wrote"]
    assert not second["publication"]["wrote"]


def test_same_command_retries_never_call_private_signing_capability_twice(
    prepared_runtime,
):
    env, inputs, config, builder, command, _ = prepared_runtime

    class ObservedPrivateCapability:
        calls = 0

        def public_key(self):
            return env.preparer_key.public_key()

        def sign(self, message):
            self.calls += 1
            return env.preparer_key.sign(message)

    key = ObservedPrivateCapability()
    builder.preparation._private_key = lambda: key
    first = builder.prepare(command, deadline_at=deadline())
    assert key.calls == 1
    assert builder.prepare(command, deadline_at=deadline()).reference == first.reference
    assert key.calls == 1
    reader = build_fiscal_candidate_runtime(inputs, env.metadata, config, write=False)
    assert (
        reader.verify_candidate(first.reference, deadline_at=deadline()).reference
        == first.reference
    )
    assert key.calls == 1


def test_current_apple_factory_preserves_all_frozen_cells(prepared_runtime, tmp_path):
    env, _, config, _, _, _ = prepared_runtime
    source, discovery_ref, _, _, _ = _case(
        tmp_path / "synthetic-current-apple",
        "aapl-current",
        artifact_type=lambda _: env.store,
    )
    config.mapping_trust_roots_file.write_bytes(
        canonical_bytes(source.mapping_approvals.trust_roots())
    )
    key_file(config.mapping_private_key_file, source.mapping_approvals.private_key())
    inputs = FiscalPreparationInputs(
        env.store, source.content, source.discovery, source.sources, source.pin, None
    )
    builder = build_fiscal_candidate_runtime(inputs, env.metadata, config, write=True)
    command = FiscalPrepareCandidateCommandV1(
        command_id="synthetic-current-apple",
        discovery_ref=discovery_ref,
        security_id="AAPL",
        expires_at=datetime.now(UTC) + timedelta(minutes=10),
    )
    first = builder.prepare(command, deadline_at=deadline())
    assert_frozen_candidate_projection(first, "aapl-current")
    assert builder.prepare(command, deadline_at=deadline()).reference == first.reference
    reader = build_fiscal_candidate_runtime(inputs, env.metadata, config, write=False)
    assert (
        reader.verify_candidate(first.reference, deadline_at=deadline()).content
        == first.content
    )


def test_signature_computed_but_not_durable_is_unknown_and_never_resigned(
    prepared_runtime,
):
    env, _, _, builder, command, _ = prepared_runtime

    class LostSignatureCapability:
        calls = 0

        def public_key(self):
            return env.preparer_key.public_key()

        def sign(self, message):
            self.calls += 1
            env.preparer_key.sign(message)
            raise RuntimeError("synthetic loss after signature computation")

    capability = LostSignatureCapability()
    builder.preparation._private_key = lambda: capability
    with pytest.raises(RuntimeError):
        builder.prepare(command, deadline_at=deadline())
    assert capability.calls == 1
    with pytest.raises(SnapshotError) as failure:
        builder.prepare(command, deadline_at=deadline())
    assert failure.value.code == "FISCAL_CANDIDATE_SIGNING_OUTCOME_UNAVAILABLE"
    assert capability.calls == 1


def test_complete_source_configuration_rotation_before_snapshot_refuses(
    prepared_runtime, tmp_path, monkeypatch
):
    env, _, config, _, _, _ = prepared_runtime
    source, discovery_ref, bindings, _, sources = _case(
        tmp_path / "synthetic-config-rotation",
        "msft-historical",
        artifact_type=lambda _: env.store,
    )
    resolver, classified = synthetic_retained_classifications(
        env, source, discovery_ref, bindings, sources
    )
    config.mapping_trust_roots_file.write_bytes(
        canonical_bytes(source.mapping_approvals.trust_roots())
    )
    key_file(config.mapping_private_key_file, source.mapping_approvals.private_key())
    state = {"generation": "active", "calls": 0}

    class CurrentSources:
        def observe(self, *args, **kwargs):
            if state["generation"] != "active":
                raise SnapshotError(
                    "SYNTHETIC_FOCUS_REVOKED", "synthetic source configuration revoked"
                )
            return resolver.observe(*args, **kwargs)

        def resolve(self, *args, **kwargs):
            if state["generation"] != "active":
                raise SnapshotError(
                    "SYNTHETIC_FOCUS_REVOKED", "synthetic source configuration revoked"
                )
            return resolver.resolve(*args, **kwargs)

    def generation():
        state["calls"] += 1
        return state["generation"]

    inputs = FiscalPreparationInputs(
        env.store,
        source.content,
        source.discovery,
        source.sources,
        source.pin,
        CurrentSources(),
        generation,
        accounting_accreditation=resolver.accounting_accreditation,
    )
    builder = build_fiscal_candidate_runtime(inputs, env.metadata, config, write=True)
    command = FiscalPrepareCandidateCommandV1(
        command_id="synthetic-whole-source-config",
        discovery_ref=discovery_ref,
        security_id="MSFT",
        classification_bindings=classified,
        expires_at=datetime.now(UTC) + timedelta(minutes=10),
    )
    first = builder.prepare(command, deadline_at=deadline())
    reader = build_fiscal_candidate_runtime(inputs, env.metadata, config, write=False)
    assert (
        reader.verify_candidate(first.reference, deadline_at=deadline()).reference
        == first.reference
    )
    assert state["calls"] >= 4
    history = reader.preparation.history
    finish = history.finish_observation

    def rotate(*args, **kwargs):
        if any(record.artifact_id == first.reference.artifact_id for record in args[0]):
            state["generation"] = "revoked"
        return finish(*args, **kwargs)

    monkeypatch.setattr(history, "finish_observation", rotate)
    with pytest.raises(SnapshotError) as failure:
        reader.verify_candidate(first.reference, deadline_at=deadline())
    assert failure.value.code == "FISCAL_CANDIDATE_INVALID"
    assert env.store.read(first.reference.artifact_id) == canonical_bytes(
        first.candidate
    )
    state["generation"] = "active"
    release_bytes = resolver.accounting_release_file.read_bytes()

    def rotate_accounting_release(*args, **kwargs):
        result = finish(*args, **kwargs)
        if any(record.artifact_id == first.reference.artifact_id for record in args[0]):
            resolver.accounting_release_file.write_bytes(
                canonical_bytes(first.reference)
            )
        return result

    monkeypatch.setattr(history, "finish_observation", rotate_accounting_release)
    with pytest.raises(SnapshotError) as policy_rotation:
        reader.verify_candidate(first.reference, deadline_at=deadline())
    assert policy_rotation.value.code == "FISCAL_CANDIDATE_INVALID"
    resolver.accounting_release_file.write_bytes(release_bytes)
