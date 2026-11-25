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
    return env, inputs, config, builder, command, sources


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
    import json
    from decimal import Decimal
    from lxml import etree
    from fundamental_service.arelle_parser import fact_semantic_digest
    from fundamental_service.fiscal_candidate_contracts import (
        FiscalCandidateClassificationBindingV1,
        FiscalSourceUseScopeV1,
    )
    from fundamental_service.fiscal_classification_contracts import (
        FiscalRecordClassificationCommandV1,
        FiscalReviewFactV1,
        FiscalSourceAccountingReviewV1,
        FiscalSourcePreparationExecutionV1,
        SignedFiscalSourcePreparationExecutionV1,
        FiscalSourceReconciliationV1,
        FiscalReconciliationTermV1,
    )
    from fundamental_service.fiscal_diagnostic_focus import ArelleActualFocusFactV1
    from fundamental_service.fiscal_focus_witness import (
        FiscalDiagnosticFocusWitnessV1,
        SignedFiscalDiagnosticFocusWitnessV1,
    )
    from fundamental_service.fiscal_source_classification import (
        FiscalSourceClassificationOwner,
    )
    from fundamental_service.fiscal_statement_mapping import (
        map_fiscal_primary_source,
        fiscal_mapping_policy_digest,
        fiscal_display_profile_digest,
    )
    from fundamental_service.fiscal_statement_registry import (
        fiscal_statement_registry,
        fiscal_primary_scopes,
        selected_fiscal_coverage,
    )
    from fundamental_service.ingestion import read_sec_xbrl_archive
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from test_fiscal_admission_authority import reference
    from test_fiscal_source_classification import retained
    from fundamental_service.serialization import sha256_digest

    evidence_root = Path(os.environ["ISSUE495_RETAINED_EVIDENCE_ROOT"])
    opinion = json.loads(
        (
            evidence_root / "actual-witness-accounting-classification-review.json"
        ).read_bytes()
    )
    discovery = source_builder.discovery.read(
        discovery_ref.artifact_id, deadline_at=deadline()
    )
    coverage = selected_fiscal_coverage(discovery)
    reviewed = {
        scope.accession_number: scope
        for scope in fiscal_primary_scopes(fiscal_statement_registry())
    }
    focus_key = Ed25519PrivateKey.generate()
    witnesses = {}

    class SyntheticRetainedWitnesses:
        def read(self, identity, *, deadline_at):
            value = witnesses[identity]
            focus_key.public_key().verify(
                bytes.fromhex(value.signature), value.signing_bytes()
            )
            assert datetime.now(UTC) < value.expires_at
            return value

    from fundamental_service.fiscal_classification_source import (
        FiscalClassificationSource,
    )
    from fundamental_service.artifact_evidence import read_retained_artifact

    test_sources = {}

    class SyntheticRetainedClassificationSources:
        def resolve(
            self,
            source_ref,
            witness_ref,
            security_id,
            *,
            reader,
            check_deadline,
            deadline_at,
        ):
            check_deadline()
            assert security_id == "MSFT"
            source = test_sources[source_ref.artifact_id]
            assert source.scope.witness_ref == witness_ref
            assert read_retained_artifact(reader, source_ref) == canonical_bytes(
                source.evidence.model_dump(mode="json")
            )
            assert read_retained_artifact(reader, witness_ref) == canonical_bytes(
                source.witness
            )
            focus_key.public_key().verify(
                bytes.fromhex(source.witness.signature), source.witness.signing_bytes()
            )
            assert datetime.now(UTC) < source.witness.expires_at
            return source

    resolver = SyntheticRetainedClassificationSources()
    classifier = FiscalSourceClassificationOwner(
        artifacts=env.store,
        history=env.history,
        authorities=env.authorities,
        sources=resolver,
        signer=env.signer,
    )
    new_bindings = []
    for binding in bindings:
        source_ref = binding.source_validation_ref
        evidence = sources[source_ref.artifact_id]
        outcome = evidence.outcome
        report = outcome.claim.report
        filing = evidence.request.filing
        receipt = next(
            item
            for item in outcome.responses
            if item.uri == outcome.integrity.archive_uri
        )
        archive = source_builder.content.get(
            receipt.content_hash, media_type=receipt.media_type
        )
        batch = map_fiscal_primary_source(
            evidence,
            source_ref,
            archive=archive,
            reviewed=reviewed[filing.accession_number],
            target_periods=tuple(q.period for q in coverage.quarters),
            security_id="MSFT",
            policy_digest=fiscal_mapping_policy_digest(),
            check_deadline=lambda: 60.0,
        )
        actions = env.source.witness.witness.actions
        member = read_sec_xbrl_archive(
            archive, primary_document=filing.primary_document, dts_filenames=()
        )[filing.primary_document]
        root = etree.fromstring(
            member,
            etree.XMLParser(resolve_entities=False, no_network=True, recover=False),
        )
        tables = root.xpath('//*[local-name()="table"]')
        facts, by_name = [], {}
        for source_fact in opinion["facts"]:
            (node,) = root.xpath("//*[@id=$identity]", identity=source_fact["fact_id"])
            table = next(
                parent
                for parent in node.iterancestors()
                if etree.QName(parent).localname == "table"
            )
            row = next(
                parent
                for parent in node.iterancestors()
                if etree.QName(parent).localname == "tr"
            )
            fact = next(
                fact
                for fact in report.facts
                if fact.concept == source_fact["qname"]
                and fact.context_id == source_fact["context_id"]
                and fact.value == source_fact["value_usd"]
            )
            item = FiscalReviewFactV1(
                fact_id=source_fact["fact_id"],
                fact=fact,
                table_index=tables.index(table),
                row_index=table.xpath('.//*[local-name()="tr"]').index(row),
                table_sha256=hashlib.sha256(
                    etree.tostring(table, method="c14n")
                ).hexdigest(),
                row_sha256=hashlib.sha256(
                    etree.tostring(row, method="c14n")
                ).hexdigest(),
                raw_lexical=source_fact["lexical_value"],
                raw_sign=source_fact["sign"] or None,
                raw_scale=source_fact["scale"],
                raw_decimals=source_fact["decimals"],
                value=Decimal(source_fact["value_usd"]),
            )
            facts.append(item)
            by_name[source_fact["name"]] = item.fact_id
        focus = next(
            item for item in facts if item.fact_id == by_name["note4_derivatives"]
        )
        body = FiscalDiagnosticFocusWitnessV1(
            source_validation_ref=source_ref,
            request_digest=evidence.request.digest,
            filing=filing,
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
            actions=tuple(actions),
            filing_context=report.dqc_filing_context,
            actual_focus=ArelleActualFocusFactV1(
                fact_id=focus.fact_id, fact=focus.fact, numeric_value=str(focus.value)
            ),
            worker_module_sha256="a" * 64,
            applicability_policy_digest="b" * 64,
        )
        witness = SignedFiscalDiagnosticFocusWitnessV1(
            witness=body,
            authority_id="synthetic-retained-focus",
            principal_id="machine:synthetic-retained-focus",
            key_id=hashlib.sha256(
                focus_key.public_key().public_bytes_raw()
            ).hexdigest(),
            signed_at=datetime.now(UTC),
            expires_at=datetime.now(UTC) + timedelta(hours=1),
            signature="0" * 128,
        )
        witness = witness.model_copy(
            update={"signature": focus_key.sign(witness.signing_bytes()).hex()}
        )
        witnesses[witness.artifact_id] = witness
        witness_ref = retained(
            env.store,
            witness.artifact_id,
            witness,
            "fiscal-diagnostic-focus-witness-v1",
        )
        scope = FiscalSourceUseScopeV1(
            source_validation_ref=source_ref,
            validation_kind="complete_refused",
            source_binding_digest=batch.source_binding_digest,
            issuer_id=filing.cik,
            accession_number=filing.accession_number,
            cutoff_at=discovery.request.valuation_timestamp,
            runtime=outcome.runtime,
            raw_report_digest=sha256_digest(report.model_dump(mode="json")),
            parser_action_refs=outcome.action_refs,
            witness_ref=witness_ref,
            display_profile_digest=fiscal_display_profile_digest(),
            mapping_policy_digest=fiscal_mapping_policy_digest(),
            permitted_inputs=batch.observations,
        )
        test_sources[source_ref.artifact_id] = FiscalClassificationSource(
            scope, evidence, witness, archive
        )
        review = FiscalSourceAccountingReviewV1(
            scope=scope,
            facts=tuple(facts),
            reconciliations=tuple(
                FiscalSourceReconciliationV1(
                    description=item["name"],
                    terms=tuple(
                        FiscalReconciliationTermV1(
                            fact_id=by_name[term["fact_name"]],
                            coefficient=term["coefficient"],
                        )
                        for term in item["inputs"]
                    ),
                    result_fact_id=by_name[item["output_fact"]],
                    residual=Decimal(item["difference_usd"]),
                    precision_allowance=Decimal(
                        item["combined_rounding_allowance_usd"]
                    ),
                )
                for item in opinion["reconciliations"]
            ),
            limitations=(
                "Synthetic deployment fixture only. Archived facts are test inputs, not a new substantive review or formal source approval.",
            ),
        )
        grant = env.authorities.read_current(
            "synthetic-source_preparer",
            expected_role="source_preparer",
            deadline_at=deadline(),
        )
        execution = FiscalSourcePreparationExecutionV1(
            source_validation_ref=source_ref,
            source_binding_digest=scope.source_binding_digest,
            runtime=scope.runtime,
            authority_id=grant.grant.identity.authority_id,
            authority_grant_ref=grant.grant_ref,
            principal_id=grant.grant.identity.principal_id,
            principal_kind="machine",
            key_id=grant.grant.identity.key_id,
            execution_id="synthetic-retained-source:" + filing.accession_number,
            issuance=env.history.read_epoch(deadline_at=deadline()).issuance_context,
            started_at=datetime.now(UTC),
            completed_at=datetime.now(UTC),
        )
        signed = SignedFiscalSourcePreparationExecutionV1(
            execution=execution, signature="0" * 128
        )
        signed = signed.model_copy(
            update={"signature": env.preparer_key.sign(signed.signing_bytes()).hex()}
        )
        preparation_ref = retained(
            env.store,
            execution.execution_id,
            signed,
            "fiscal-source-preparation-execution-v1",
        )
        review_ref = retained(
            env.store,
            "synthetic-retained-review:" + filing.accession_number,
            review,
            "fiscal-source-accounting-review-v1",
        )
        command = FiscalRecordClassificationCommandV1(
            command_id="synthetic-retained-classify:" + filing.accession_number,
            authority_id="synthetic-classifier",
            source_validation_ref=source_ref,
            witness_ref=witness_ref,
            review_ref=review_ref,
            preparer_execution_ref=preparation_ref,
            security_id="MSFT",
            expires_at=datetime.now(UTC) + timedelta(minutes=20),
        )
        classified = classifier.record_classification(
            command, expected_head=None, deadline_at=deadline()
        )
        new_bindings.append(
            FiscalCandidateClassificationBindingV1(
                source_validation_ref=source_ref,
                witness_ref=witness_ref,
                classification_refs=(
                    reference(
                        classified.publication.artifact,
                        "fiscal-source-classification-v1",
                    ),
                ),
            )
        )
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
        state["generation"] = "revoked"
        return finish(*args, **kwargs)

    monkeypatch.setattr(history, "finish_observation", rotate)
    with pytest.raises(SnapshotError) as failure:
        reader.verify_candidate(first.reference, deadline_at=deadline())
    assert failure.value.code == "FISCAL_CANDIDATE_INVALID"
    assert env.store.read(first.reference.artifact_id) == canonical_bytes(
        first.candidate
    )
