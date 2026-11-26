from __future__ import annotations

import hashlib
import os
import shutil
import json
from pathlib import Path
from datetime import UTC, datetime, timedelta

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pydantic import ValidationError

from fundamental_service.automatic_data_release import automatic_release_suite_digest
from fundamental_service.data_releases import (
    ArtifactRefV1,
    DataReleaseError,
    DataReleaseTrustRootsV1,
    DataReleaseVerifierV1,
)
from fundamental_service.fiscal_candidate_contracts import (
    FiscalPrepareCandidateCommandV1,
)
from fundamental_service.fiscal_display_admission import FiscalDisplayAdmission
from fundamental_service.fiscal_display_runtime import build_fiscal_display_reader
from fundamental_service.fiscal_preparation_runtime import (
    FiscalPreparationInputs,
    build_fiscal_candidate_runtime,
)
from fundamental_service.fiscal_read_contracts import (
    FiscalReadRequestV1,
    FiscalReadResultV1,
)
from fundamental_service.fiscal_release_contracts import FiscalPublishV1
from fundamental_service.fiscal_release_runtime import (
    FiscalReleaseInstallationV1,
    FiscalReleaseOrderV1,
    FiscalReleaseReadConfigurationV1,
    FiscalReleaseRuntime,
    build_fiscal_release_reader,
    release_configuration_digest,
)
from fundamental_service.fiscal_releases import FiscalReleaseService
from fundamental_service.fiscal_source_closure import FiscalArtifactRead
from fundamental_service.serialization import canonical_bytes, sha256_digest
from fundamental_service.snapshots import SnapshotError
import test_fiscal_display_admission as display_cases
import test_fiscal_releases as release_cases
from test_fiscal_admission_authority import public_key, change_status
from test_fiscal_candidate_preparation import (
    key_file,
    synthetic_retained_classifications,
)
from test_fiscal_projection_builder import _case, assert_frozen_candidate_projection


environment = display_cases.environment
protected_deployment_root = display_cases.protected_deployment_root
display = display_cases.display
release = release_cases.release
published = release_cases.published


def deadline():
    return datetime.now(UTC) + timedelta(seconds=60)


@pytest.fixture
def classified_display(display, tmp_path, protected_deployment_root, monkeypatch):
    env = display.env
    source_builder, discovery_ref, bindings, _, sources = _case(
        tmp_path / "retained-msft", "msft-historical", artifact_type=lambda _: env.store
    )
    try:
        resolver, actual_bindings = synthetic_retained_classifications(
            env, source_builder, discovery_ref, bindings, sources
        )
        config = display.candidate_config
        config.mapping_trust_roots_file.write_bytes(
            canonical_bytes(source_builder.mapping_approvals.trust_roots())
        )
        key_file(
            config.mapping_private_key_file,
            source_builder.mapping_approvals.private_key(),
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
        writer = build_fiscal_candidate_runtime(
            inputs, env.metadata, config, write=True
        )
        candidate = writer.prepare(
            FiscalPrepareCandidateCommandV1(
                command_id="classified-service-integration",
                discovery_ref=discovery_ref,
                security_id="MSFT",
                classification_bindings=actual_bindings,
                expires_at=datetime.now(UTC) + timedelta(minutes=10),
            ),
            deadline_at=deadline(),
        )
        assert_frozen_candidate_projection(candidate, "msft-historical")
        assert any(
            item.source_use.kind == "classified_provisional"
            for item in candidate.source_evidence
        )
        focus = protected_deployment_root / "focus-public.json"
        focus.write_bytes(
            canonical_bytes({"retained_focus": actual_bindings[0].witness_ref})
        )
        monkeypatch.setenv("FUNDAMENTAL_FISCAL_FOCUS_AUTHORITY_FILE", str(focus))
        display.runtime.installation = display.runtime.installation.model_copy(
            update={
                "mapping_trust_roots_sha256": hashlib.sha256(
                    config.mapping_trust_roots_file.read_bytes()
                ).hexdigest(),
                "focus_authority_file": focus,
                "focus_authority_sha256": hashlib.sha256(
                    focus.read_bytes()
                ).hexdigest(),
            }
        )
        display.runtime.candidates = build_fiscal_candidate_runtime(
            inputs, env.metadata, config, write=False
        )
        display.order = display.order.model_copy(
            update={
                "request": display.order.request.model_copy(
                    update={"candidate_ref": candidate.reference}
                ),
            }
        )
        display.write(display.order)
        yield display, resolver.accounting_release_file
    finally:
        for protected in getattr(env, "producer_protected_directories", ()):
            shutil.rmtree(protected)


def test_real_provider_rotation_refuses_display_and_release_final_exits(
    classified_display, protected_deployment_root, monkeypatch
):
    display, accreditation = classified_display
    candidates, env = display.runtime.candidates, display.env
    original = accreditation.read_bytes()
    initial_generation = candidates.current_configuration_digest()

    def rotate():
        ref = ArtifactRefV1.model_validate_json(original)
        accreditation.write_bytes(
            canonical_bytes(
                ref.model_copy(update={"artifact_id": ref.artifact_id + "-rotated"})
            )
        )
        assert candidates.current_configuration_digest() != initial_generation

    current = display.runtime.apply(display.order.order_id, deadline_at=deadline())
    read = build_fiscal_display_reader(
        candidates=candidates,
        deployment_file=display.runtime.installation.deployment_file,
        deployment_uid=os.getuid(),
        mapping_trust_roots_file=display.candidate_config.mapping_trust_roots_file,
        focus_authority_file=display.runtime.installation.focus_authority_file,
        artifacts=env.store,
        metadata=env.metadata,
    )
    assert (
        read.read_current(
            current.reference, current.candidate.reference, deadline_at=deadline()
        ).reference
        == current.reference
    )
    finish = read.history.finish_observation

    def display_last_cut(*args, **kwargs):
        result = finish(*args, **kwargs)
        rotate()
        return result

    with monkeypatch.context() as patch:
        patch.setattr(read.history, "finish_observation", display_last_cut)
        with pytest.raises(SnapshotError, match="configuration"):
            read.read_current(
                current.reference, current.candidate.reference, deadline_at=deadline()
            )
    accreditation.write_bytes(original)
    review = FiscalDisplayAdmission.review_and_decide

    def display_runtime_last_cut(self, *args, **kwargs):
        result = review(self, *args, **kwargs)
        rotate()
        return result

    with monkeypatch.context() as patch:
        patch.setattr(
            FiscalDisplayAdmission, "review_and_decide", display_runtime_last_cut
        )
        with pytest.raises(SnapshotError, match="configuration"):
            display.runtime.apply(display.order.order_id, deadline_at=deadline())
    accreditation.write_bytes(original)
    key = Ed25519PrivateKey.generate()
    roots = DataReleaseTrustRootsV1(
        verifiers={
            "integration-fiscal": DataReleaseVerifierV1(
                workflow_identity="integration-fiscal-workflow",
                public_key_ed25519_base64=public_key(key),
                verification_suite_digest=automatic_release_suite_digest(),
            ),
        },
        mapping_reviewers={"integration-mapping": public_key(key)},
    )
    env.metadata._data_release_trust_roots = roots
    trust = protected_deployment_root / "release-trust.json"
    trust.write_bytes(canonical_bytes(roots))
    configuration = FiscalReleaseReadConfigurationV1(
        deployment_uid=os.getuid(),
        deployment_file=display.runtime.installation.deployment_file,
        candidate_authority_id=display.candidate_config.candidate_authority_id,
        mapping_trust_roots_file=display.candidate_config.mapping_trust_roots_file,
        release_trust_roots_file=trust,
        declared_source_revision=display.runtime.installation.declared_source_revision,
        focus_authority_file=display.runtime.installation.focus_authority_file,
    )
    reader = build_fiscal_release_reader(
        candidates=candidates,
        artifacts=env.store,
        metadata=env.metadata,
        configuration=configuration,
    )
    approved = FiscalPublishV1(
        candidate_ref=current.candidate.reference, decision_ref=current.reference
    )
    observed = reader.observe(approved, deadline_at=deadline())
    reader.finish(
        observed,
        FiscalArtifactRead(reader.artifacts, lambda: 60),
        deadline_at=deadline(),
    )
    finish_release = reader.history.finish_observation

    def release_last_cut(*args, **kwargs):
        result = finish_release(*args, **kwargs)
        rotate()
        return result

    with monkeypatch.context() as patch:
        patch.setattr(reader.history, "finish_observation", release_last_cut)
        with pytest.raises(SnapshotError, match="configuration"):
            reader.finish(
                observed,
                FiscalArtifactRead(reader.artifacts, lambda: 60),
                deadline_at=deadline(),
            )
    accreditation.write_bytes(original)
    orders = protected_deployment_root / "release-orders"
    orders.mkdir(mode=0o700)
    installed = FiscalReleaseInstallationV1(
        audience="integration-release",
        reader=configuration,
        workload_uid=os.getuid(),
        database_role="fundamental",
        orders_directory=orders,
        private_key_file=key_file(protected_deployment_root / "release.pem", key),
        verifier_id="integration-fiscal",
        workflow_identity="integration-fiscal-workflow",
        source_revision="b" * 40,
        verification_suite_digest=automatic_release_suite_digest(),
    )
    now = datetime.now(UTC)
    order = FiscalReleaseOrderV1(
        order_id="publish-integration",
        audience=installed.audience,
        installation_digest=sha256_digest(installed.model_dump(mode="json")),
        configuration_digest=release_configuration_digest(configuration),
        issuance=env.history.read_epoch(deadline_at=deadline()).issuance_context,
        approved=approved,
        verification_run_id="integration-run",
        valid_from=now - timedelta(seconds=1),
        valid_until=now + timedelta(minutes=5),
    )
    (orders / (order.order_id + ".json")).write_bytes(canonical_bytes(order))
    runtime = FiscalReleaseRuntime(
        installation=installed,
        candidates=candidates,
        artifacts=env.store,
        metadata=env.metadata,
    )
    first = runtime.apply(order.order_id, deadline_at=deadline())
    assert first.wrote
    publish = FiscalReleaseService.publish

    def release_runtime_last_cut(self, *args, **kwargs):
        result = publish(self, *args, **kwargs)
        rotate()
        return result

    with monkeypatch.context() as patch:
        patch.setattr(FiscalReleaseService, "publish", release_runtime_last_cut)
        with pytest.raises(ValueError, match="binding"):
            runtime.apply(order.order_id, deadline_at=deadline())
    accreditation.write_bytes(original)
    assert candidates.current_configuration_digest() == initial_generation


def test_typed_source_documents_match_exact_evidence_and_final_readset(
    published, monkeypatch
):
    display, _, _, reader, receipt = published
    manifest = display.env.metadata.get_data_release_manifest(receipt.manifest_digest)
    request = FiscalReadRequestV1(
        manifest_digest=receipt.manifest_digest,
        scope=manifest.scope,
        cutoff_at=manifest.cutoff_at,
        frequency="quarter",
    )
    result = reader.read(request, deadline_at=deadline())
    output = os.getenv("ISSUE495_INTEGRATION_OUTPUT")
    if output and not (Path(output) / "apple-quarter-response.json").exists():
        root = Path(output)
        (root / "apple-quarter-response.json").write_bytes(canonical_bytes(result))
        ttm = reader.read(
            request.model_copy(update={"frequency": "ttm"}), deadline_at=deadline()
        )
        (root / "apple-ttm-response.json").write_bytes(canonical_bytes(ttm))
        (root / "fiscal-read-result-schema.json").write_bytes(
            canonical_bytes(FiscalReadResultV1.model_json_schema())
        )
    for source in result.evidence.source_uses:
        raw = json.loads(
            display.env.store.read(source.source_validation_ref.artifact_id)
        )
        document = source.source_document
        assert document.primary_document_url == raw["outcome"]["claim"]["source"]["uri"]
        assert (
            document.primary_document_sha256
            == raw["outcome"]["integrity"]["raw_content_hash"]
        )
        assert (
            document.archive_member_sha256
            == raw["outcome"]["integrity"]["archive_member_hash"]
        )
        assert document.issuer_id == raw["request"]["filing"]["cik"]
        assert document.accession_number == raw["request"]["filing"]["accession_number"]
    observed = result.evidence.observations[0]
    for field, value in (
        ("source_artifact_id", "unbound"),
        ("source_binding_digest", "f" * 64),
        ("issuer_id", "0000000000"),
        ("accession_number", "0000000000-00-000000"),
    ):
        evidence = result.evidence.model_copy(
            update={
                "observations": (
                    observed.model_copy(update={field: value}),
                    *result.evidence.observations[1:],
                )
            }
        )
        with pytest.raises(ValidationError, match="source differs"):
            FiscalReadResultV1.model_validate(
                {**result.model_dump(), "evidence": evidence.model_dump()}
            )
    locator = observed.source_locator.model_copy(
        update={"primary_document_sha256": "f" * 64}
    )
    evidence = result.evidence.model_copy(
        update={
            "observations": (
                observed.model_copy(update={"source_locator": locator}),
                *result.evidence.observations[1:],
            )
        }
    )
    with pytest.raises(ValidationError, match="source differs"):
        FiscalReadResultV1.model_validate(
            {**result.model_dump(), "evidence": evidence.model_dump()}
        )
    load = reader._source_document
    tripped = []

    def revoke_after_load(scope, observation, artifact_reader):
        document = load(scope, observation, artifact_reader)
        if not tripped:
            tripped.append(scope.source_validation_ref.artifact_id)
            change_status(display.env, tripped[0], "invalidated")
        return document

    monkeypatch.setattr(reader, "_source_document", revoke_after_load)
    with pytest.raises((SnapshotError, DataReleaseError)):
        reader.read(request, deadline_at=deadline())
    assert tripped


def test_release_runner_publishes_for_trusted_group(environment, tmp_path, monkeypatch):
    import asyncio
    import stat
    from contextlib import asynccontextmanager
    from types import SimpleNamespace
    from fundamental_service import app as app_module
    from fundamental_service import fiscal_release_runner as runner

    env = environment
    data_root = tmp_path / "group-release-data"
    data_root.mkdir(mode=0o700)
    configuration = FiscalReleaseReadConfigurationV1(
        deployment_uid=os.getuid(),
        deployment_file=data_root / "roster.json",
        candidate_authority_id="candidate",
        mapping_trust_roots_file=data_root / "mapping.json",
        release_trust_roots_file=data_root / "release.json",
        declared_source_revision="test-constructor",
    )
    installation = FiscalReleaseInstallationV1(
        audience="constructor-test",
        reader=configuration,
        workload_uid=os.getuid(),
        database_role="fundamental",
        orders_directory=data_root / "orders",
        private_key_file=data_root / "private.pem",
        verifier_id="constructor-test",
        workflow_identity="constructor-test",
        source_revision="b" * 40,
        verification_suite_digest="a" * 64,
    )

    @asynccontextmanager
    async def operator(_):
        yield

    monkeypatch.setenv("FUNDAMENTAL_SERVICE_DATA_ROOT", str(data_root))
    monkeypatch.setenv("FUNDAMENTAL_SERVICE_CONTENT_READER_GID", str(os.getegid()))
    monkeypatch.setattr(
        runner,
        "protected_release_file",
        lambda *args, **kwargs: canonical_bytes(installation.model_dump(mode="json")),
    )
    monkeypatch.setattr(
        runner, "configured_fiscal_candidate_runtime", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(
        app_module,
        "app",
        SimpleNamespace(
            state=SimpleNamespace(
                read_only_operator_lifespan=operator,
                fiscal_sec_acquisition=object(),
                metadata_store=env.metadata,
            )
        ),
    )

    class PublishOnlyRuntime:
        def __init__(self, *, artifacts, **kwargs):
            self.artifacts = artifacts

        def apply(self, order_id, *, deadline_at):
            return self.artifacts.put_bytes_with_receipt(
                "constructor-publication",
                b'{"exact":"release"}',
                (),
                media_type="application/json",
            ).artifact

    monkeypatch.setattr(runner, "FiscalReleaseRuntime", PublishOnlyRuntime)
    previous = os.umask(0o077)
    try:
        raw = asyncio.run(runner._run("constructor-publication", deadline()))
    finally:
        os.umask(previous)
    record = json.loads(raw)
    digest = record["content_hash"]
    path = data_root / "content" / digest[:2] / (digest + ".json")
    assert path.read_bytes() == b'{"exact":"release"}'
    assert stat.S_IMODE(path.stat().st_mode) == 0o640
    assert path.stat().st_gid == os.getegid()
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o750
    assert env.metadata.content_byte_length(
        digest, media_type="application/json"
    ) == len(b'{"exact":"release"}')
