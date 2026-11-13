"""Batch mapping preserves every model role without author-selected proposals."""

import asyncio
import hashlib
import json
import os
from pathlib import Path
import subprocess

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
import pytest
from pydantic import ValidationError

from fundamental_service.automatic_mapping import (
    AutomaticMappingDecisionV1,
    verify_automatic_mapping_replay,
)
from fundamental_service.automatic_mapping_batch import (
    AutomaticMappingBatchDecisionV1,
    AutomaticMappingBatchRequestV1,
)
from fundamental_service.automatic_mapping_runner import approve_mapping_batch, main
from fundamental_service.data_releases import (
    AutomaticMappingApprovalV1,
    DataReleaseError,
)
from fundamental_service.metadata import (
    PostgresArtifactStore,
    PostgresContentStore,
    PostgresMetadataStore,
)
from fundamental_service.persistence_recovery import export_backup, restore_backup
from fundamental_service.replay import ArtifactStore
from fundamental_service.serialization import canonical_bytes
from fundamental_service.valuation_requirements import valuation_requirements_profile
from test_automatic_mapping import case, MACHINE_KEY
from test_issuer_operating_release import inventory


def batch_case(tmp_path, model_id="fcff_dcf"):
    single, store, roots, _ = case(tmp_path)
    request = AutomaticMappingBatchRequestV1(
        **single.model_dump(exclude={"protocol", "proposal"}),
        mapping_version=single.proposal.mapping_version,
        model_version=f"{model_id}-v2",
        requirements=valuation_requirements_profile(model_id),
    )
    return request, store, roots


def run_batch(request, store, roots, *, private_key=MACHINE_KEY):
    return approve_mapping_batch(
        request, artifacts=store, trust_roots=roots, private_key=private_key
    )


def read_decision(receipt, store):
    return AutomaticMappingBatchDecisionV1.model_validate_json(
        store.read(receipt.decision_publication.artifact.artifact_id)
    )


@pytest.mark.parametrize("model_id", ["fcff_dcf", "transition_fcff_dcf"])
def test_batch_keeps_all_roles_missing_observations_and_unsupported_classifications(
    tmp_path, model_id
):
    request, store, roots = batch_case(tmp_path, model_id)
    receipt = run_batch(request, store, roots)
    decision = read_decision(receipt, store)
    roles = {role.normalized_field: role for role in decision.roles}
    assert tuple(roles) == tuple(
        sorted(
            set(request.requirements.required_fact_fields)
            | set(request.requirements.supporting_fact_fields)
        )
    )
    assert len(request.requirements.required_fact_fields) == (
        26 if model_id == "transition_fcff_dcf" else 25
    )
    assert "finance_lease_cost" not in request.requirements.required_fact_fields
    assert "finance_lease_cost" in request.requirements.supporting_fact_fields
    assert roles["finance_lease_cost"].status == "abstain"
    assert roles["finance_lease_cost"].reason_codes == (
        "MAPPING_AUTOMATIC_RULE_UNSUPPORTED",
    )
    assert roles["revenue"].status == "approved"
    assert roles["non_operating_assets"].status == "abstain"
    assert roles["non_operating_assets"].reason_codes == (
        "MAPPING_AUTOMATIC_RULE_UNSUPPORTED",
    )
    assert roles["non_operating_assets"].decision is None
    assert (
        "MAPPING_NO_ELIGIBLE_OBSERVATIONS" in roles["capital_expenditure"].reason_codes
    )
    assert roles["capital_expenditure"].decision is not None
    assert all(
        role.approval is None for role in decision.roles if role.status == "abstain"
    )
    assert not set(request.requirements.market_policy_input_roles) & roles.keys()
    assert request.requirements.supported_history_threshold is None
    assert receipt.wrote
    for role in decision.roles:
        if role.approval is None:
            continue
        approval = AutomaticMappingApprovalV1.model_validate_json(
            store.read(role.approval.artifact_id)
        )
        child = AutomaticMappingDecisionV1.model_validate_json(
            store.read(role.decision.artifact_id)
        )
        assert child.mapping is not None
        verify_automatic_mapping_replay(approval, child.mapping, artifacts=store)


def test_complete_batch_repeat_preserves_bytes_order_and_mtimes(tmp_path):
    request, store, roots = batch_case(tmp_path)
    first = run_batch(request, store, roots)
    before = inventory(store.root)
    second = run_batch(request, ArtifactStore(store.root), roots)
    assert not second.wrote
    assert (
        first.input_digest == second.input_digest
        and first.output_digest == second.output_digest
    )
    assert before == inventory(store.root)
    assert all(
        not r.input_publication.wrote and not r.decision_publication.wrote
        for r in second.mapping_receipts
    )
    decision = read_decision(second, store)
    with pytest.raises(ValidationError):
        AutomaticMappingBatchDecisionV1.model_validate(
            {**decision.model_dump(), "roles": decision.roles[1:]}
        )
    with pytest.raises(ValidationError):
        AutomaticMappingBatchDecisionV1.model_validate(
            {**decision.model_dump(), "roles": tuple(reversed(decision.roles))}
        )


def test_certificate_invalidation_marks_the_dependent_batch_report_stale(tmp_path):
    request, store, roots = batch_case(tmp_path)
    receipt = run_batch(request, store, roots)
    certificate = next(
        role.approval
        for role in read_decision(receipt, store).roles
        if role.approval is not None
    )
    store.invalidate(certificate.artifact_id)
    affected = store.invalidate_dependency(certificate.content_hash)
    assert receipt.decision_publication.artifact.artifact_id in affected
    assert (
        store.get(receipt.decision_publication.artifact.artifact_id).status == "stale"
    )


@pytest.mark.parametrize(
    "change", ["omit", "add", "profile_version", "model_version", "threshold"]
)
def test_caller_cannot_select_easier_requirements_or_promote_history(tmp_path, change):
    request, _, _ = batch_case(tmp_path)
    payload = request.model_dump(mode="json")
    if change == "omit":
        payload["requirements"]["point_in_time_fact_fields"].remove(
            "non_operating_assets"
        )
    elif change == "add":
        payload["requirements"]["annual_duration_fields"].append("custom_role")
    elif change == "profile_version":
        payload["requirements"]["profile_version"] = "invented"
    elif change == "threshold":
        payload["requirements"]["supported_history_threshold"] = 3
    else:
        payload["model_version"] = "fcff_dcf-v1"
    with pytest.raises(ValidationError, match="exact service model and requirements"):
        AutomaticMappingBatchRequestV1.model_validate_json(canonical_bytes(payload))


def test_untrusted_batch_key_publishes_nothing(tmp_path):
    request, store, roots = batch_case(tmp_path)
    before = inventory(store.root)
    with pytest.raises(DataReleaseError) as error:
        run_batch(request, store, roots, private_key=Ed25519PrivateKey.generate())
    assert error.value.code == "MAPPING_AUTOMATIC_AUTHORITY_MISMATCH"
    assert inventory(store.root) == before


def test_batch_without_source_bytes_retains_every_refusal(tmp_path):
    request, _, roots = batch_case(tmp_path)
    store = ArtifactStore(tmp_path / "empty")
    first = run_batch(request, store, roots)
    decision = read_decision(first, store)
    assert all(role.status == "abstain" for role in decision.roles)
    revenue = next(
        role for role in decision.roles if role.normalized_field == "revenue"
    )
    assert "MAPPING_SOURCE_ARTIFACT_UNAVAILABLE" in revenue.reason_codes
    before = inventory(store.root)
    second = run_batch(request, ArtifactStore(store.root), roots)
    assert not second.wrote and first.output_digest == second.output_digest
    assert before == inventory(store.root)


def test_interrupted_batch_reuses_completed_children_before_publishing_summary(
    tmp_path,
):
    request, store, roots = batch_case(tmp_path)
    published_ids = []

    class InterruptedStore(ArtifactStore):
        writes = 0

        def put_with_receipt(self, *args, **kwargs):
            self.writes += 1
            if self.writes == 4:
                raise OSError("synthetic interruption")
            receipt = super().put_with_receipt(*args, **kwargs)
            published_ids.append(receipt.artifact.artifact_id)
            return receipt

    interrupted = InterruptedStore(store.root)
    with pytest.raises(OSError, match="synthetic interruption"):
        run_batch(request, interrupted, roots)
    partial = {
        name: value
        for name, value in inventory(store.root).items()
        if name.endswith(".artifact")
    }
    assert not any(
        name.startswith("automatic-mapping-batch-decision-") for name in published_ids
    )
    completed = run_batch(request, ArtifactStore(store.root), roots)
    assert completed.wrote
    after = inventory(store.root)
    assert all(after[name] == value for name, value in partial.items())
    repeated = run_batch(request, ArtifactStore(store.root), roots)
    assert not repeated.wrote and repeated.output_digest == completed.output_digest
    assert after == inventory(store.root)


def test_fresh_command_process_reuses_the_whole_batch(tmp_path, capsys):
    request, store, roots = batch_case(tmp_path)
    paths = {name: tmp_path / (name + ".json") for name in ("request", "roots")}
    paths["request"].write_bytes(canonical_bytes(request))
    paths["roots"].write_bytes(canonical_bytes(roots))
    key = tmp_path / "machine.pem"
    key.write_bytes(
        MACHINE_KEY.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    args = [
        "--request",
        str(paths["request"]),
        "--trust-roots",
        str(paths["roots"]),
        "--private-key",
        str(key),
        "--artifacts-root",
        str(store.root),
    ]
    assert main(args) == 0
    first = json.loads(capsys.readouterr().out)
    assert first["wrote"]
    before = inventory(store.root)
    command = [
        "uv",
        "run",
        "--frozen",
        "--project",
        str(Path(__file__).resolve().parents[1]),
        "python",
        "-m",
        "fundamental_service.automatic_mapping_runner",
        *args,
    ]
    result = subprocess.run(
        command,
        capture_output=True,
        check=True,
        env={**os.environ, "PYTHONHASHSEED": "51"},
    )
    second = json.loads(result.stdout)
    assert not second["wrote"] and first["output_digest"] == second["output_digest"]
    assert first["input_digest"] == second["input_digest"]
    assert inventory(store.root) == before


def test_postgres_batch_survives_restart_and_empty_store_restore(
    tmp_path, recovery_databases
):
    request, source, roots = batch_case(tmp_path)
    source_db, target_db = recovery_databases
    content_root = tmp_path / "postgres-content"
    metadata = PostgresMetadataStore(source_db, auto_migrate=True)
    metadata.start()
    try:
        store = PostgresArtifactStore(
            metadata, PostgresContentStore(content_root, metadata)
        )
        for ref in request.evidence_refs:
            store.put_bytes_with_receipt(
                ref.artifact_id, source.read(ref.artifact_id), media_type=ref.media_type
            )
        first = run_batch(request, store, roots)
    finally:
        metadata.close()
    before = inventory(content_root)
    metadata = PostgresMetadataStore(source_db)
    metadata.start()
    try:
        store = PostgresArtifactStore(
            metadata, PostgresContentStore(content_root, metadata)
        )
        second = run_batch(request, store, roots)
        assert not second.wrote and first.output_digest == second.output_digest
        assert inventory(content_root) == before
    finally:
        metadata.close()
    backup = asyncio.run(
        export_backup(
            source_db,
            content_root,
            tmp_path / "backups",
            source_revision=request.source_revision,
        )
    )
    restored_content = tmp_path / "restored-content"
    asyncio.run(
        restore_backup(
            target_db,
            restored_content,
            tmp_path / "backups" / backup.manifest_digest,
            manifest_digest=backup.manifest_digest,
        )
    )
    restored_before = inventory(restored_content)
    metadata = PostgresMetadataStore(target_db)
    metadata.start()
    try:
        store = PostgresArtifactStore(
            metadata, PostgresContentStore(restored_content, metadata)
        )
        third = run_batch(request, store, roots)
        assert not third.wrote and first.input_digest == third.input_digest
        assert first.output_digest == third.output_digest
        assert inventory(restored_content) == restored_before
        raw = store.read(third.decision_publication.artifact.artifact_id)
        assert hashlib.sha256(raw).hexdigest() == first.output_digest
    finally:
        metadata.close()
