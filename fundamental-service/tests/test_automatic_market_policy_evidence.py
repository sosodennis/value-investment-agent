import hashlib
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from fundamental_service.application.service import ServiceError
from fundamental_service.automatic_market_policy_evidence import (
    AUTOMATIC_MARKET_POLICY_REF_PREFIX,
    AUTOMATIC_MARKET_POLICY_ROLE,
    assemble_authorized_market_policy_record,
    build_automatic_market_policy_evidence,
    load_release_automatic_market_policy,
)
from fundamental_service.contracts import QualityStatus, ValuationEvidenceReadRequestV1
from fundamental_service.data_releases import (
    ArtifactRefV1,
    DataReleaseError,
    DataReleaseManifestV1,
    sign_data_release_verification,
)
from fundamental_service.policies import (
    FilesystemPolicyRepository,
    PolicyError,
    PolicyRecordV1,
    PolicyRegistry,
    initial_model_specs,
)
from fundamental_service.quote_sources import default_quote_providers
from fundamental_service.release_runner import DataReleaseCanaryRunner
from fundamental_service.serialization import canonical_bytes, sha256_digest
from fundamental_service.source_admission import (
    SourceUsePolicyV1,
    admit_macro_source,
    admit_reference_source,
)
from test_automatic_market_policy import (
    AT,
    AlternateReferenceProvider,
    _admissions,
    _market_policy,
    _plan_decision,
    _reference_inputs,
)
from test_preparation_runner import _fixture, _reviewed_candidate
from test_release_runner import _candidate
from test_source_admission_evidence import _packet
from test_terminal_growth import AnnualAndDailyProvider, _inputs as macro_inputs
from test_terminal_growth_evidence import replace_metadata


class _Artifacts:
    def __init__(self, data):
        self.data = data

    def read(self, artifact_id):
        return self.data[artifact_id]


def _bound(*, manifest=None, snapshot=None, admissions=None):
    if snapshot is None:
        manifest, _, snapshots, _, _, _, _ = _candidate()
        payload = snapshots.snapshot.model_dump(exclude={"manifest_digest"})
        payload["identity"] = snapshots.snapshot.identity.model_copy(
            update={"issuer_id": "0000320193"}
        )
        payload["valuation_timestamp"] = AT
        snapshot = type(snapshots.snapshot).model_validate(
            {
                **payload,
                "manifest_digest": sha256_digest(
                    {
                        key: value
                        for key, value in payload.items()
                        if key != "snapshot_id"
                    }
                ),
            }
        )
    at = snapshot.valuation_timestamp
    issuer_id = snapshot.identity.issuer_id
    plan_decision = _plan_decision(at, issuer_id=issuer_id)
    policy_spec = _market_policy(at)
    policy_spec = policy_spec.model_copy(
        update={
            "terminal_growth_plan": policy_spec.terminal_growth_plan.model_copy(
                update={"issuer_id": issuer_id}
            ),
        }
    )
    admissions = _admissions(at) if admissions is None else admissions
    evidence = build_automatic_market_policy_evidence(
        source_revision="1" * 40,
        plan_decision=plan_decision,
        policy=policy_spec,
        admissions=admissions,
    )
    contents = {}
    refs = list(manifest.artifact_refs)
    for role, value in (
        ("issuer_market_reference_plan", plan_decision.plan),
        ("issuer_terminal_growth_plan", policy_spec.terminal_growth_plan),
        (AUTOMATIC_MARKET_POLICY_ROLE, evidence),
    ):
        raw = canonical_bytes(value)
        digest = hashlib.sha256(raw).hexdigest()
        artifact_id = f"{role}:{digest}"
        contents[artifact_id] = raw
        refs.append(
            ArtifactRefV1(
                artifact_id=artifact_id,
                content_hash=digest,
                media_type="application/json",
                role=role,
            )
        )
    manifest_payload = manifest.model_dump(exclude={"manifest_digest"})
    manifest_payload["artifact_refs"] = tuple(
        {ref.artifact_id: ref for ref in refs}.values()
    )
    manifest = DataReleaseManifestV1(
        **manifest_payload, manifest_digest=sha256_digest(manifest_payload)
    )
    market_policy = evidence.decision.inputs
    assert market_policy is not None
    payload = {
        "contract_version": "fundamental.v1",
        "policy_id": plan_decision.plan.policy_id,
        "policy_version": policy_spec.policy_version,
        "profile_id": "us-gaap-public-v1",
        "model_id": "fcff_dcf",
        "model_version": "fcff_dcf-v2",
        "issuer_id": issuer_id,
        "assumptions": None,
        "market_inputs": market_policy,
        "source_refs": (
            AUTOMATIC_MARKET_POLICY_REF_PREFIX
            + hashlib.sha256(canonical_bytes(evidence)).hexdigest(),
            sha256_digest(plan_decision.plan),
            sha256_digest(policy_spec.terminal_growth_plan),
        ),
        "effective_at": at,
        "status": "active",
    }
    policy = PolicyRecordV1(**payload, policy_digest=sha256_digest(payload))
    return manifest, snapshot, policy, admissions, contents, evidence


def test_release_boundary_reproduces_automatic_policy_with_injected_sources():
    manifest, snapshot, policy, admissions, contents, expected = _bound()
    result = load_release_automatic_market_policy(
        manifest,
        snapshot=snapshot,
        policy=policy,
        admissions=admissions,
        artifacts=_Artifacts(contents),
    )
    assert result == expected
    assert (
        load_release_automatic_market_policy(
            manifest,
            snapshot=snapshot,
            policy=policy,
            admissions=tuple(reversed(admissions)),
            artifacts=_Artifacts(contents),
            expected_source_revision="1" * 40,
        )
        == expected
    )


def _authorization(policy, **changes):
    payload = policy.model_dump(exclude={"policy_digest"})
    payload.update(changes)
    if payload.get("data_release_manifest_digest") is None:
        payload.pop("data_release_manifest_digest", None)
    return PolicyRecordV1(**payload, policy_digest=sha256_digest(payload))


def test_policy_assembly_reuses_exact_authorized_evidence_without_side_effects():
    manifest, snapshot, expected, admissions, contents, _ = _bound()
    authorization = _authorization(expected, market_inputs=None)
    expected = _authorization(
        expected, data_release_manifest_digest=manifest.manifest_digest
    )
    before = canonical_bytes(authorization), dict(contents)
    kwargs = dict(
        authorization=authorization,
        model=initial_model_specs()[0],
        snapshot=snapshot,
        artifacts=_Artifacts(contents),
        expected_source_revision="1" * 40,
    )
    first = assemble_authorized_market_policy_record(
        manifest, admissions=admissions, **kwargs
    )
    second = assemble_authorized_market_policy_record(
        manifest, admissions=tuple(reversed(admissions)), **kwargs
    )
    assert first == second == expected
    assert (
        canonical_bytes(first) == canonical_bytes(second) == canonical_bytes(expected)
    )
    assert first.model_dump(
        exclude={"market_inputs", "policy_digest", "data_release_manifest_digest"}
    ) == (authorization.model_dump(exclude={"market_inputs", "policy_digest"}))
    assert (canonical_bytes(authorization), contents) == before
    assert authorization.market_inputs is None
    assert (
        assemble_authorized_market_policy_record(
            manifest, admissions=admissions, **{**kwargs, "authorization": first}
        )
        == first
    )


def test_policy_assembly_cannot_replace_an_already_published_policy(tmp_path):
    manifest, snapshot, policy, admissions, contents, _ = _bound()
    authorization = _authorization(policy, market_inputs=None)
    repository = FilesystemPolicyRepository(tmp_path)
    repository.publish(authorization)
    before = {
        path: (path.read_bytes(), path.stat().st_mtime_ns)
        for path in tmp_path.iterdir()
    }
    candidate = assemble_authorized_market_policy_record(
        manifest,
        authorization=authorization,
        model=initial_model_specs()[0],
        snapshot=snapshot,
        admissions=admissions,
        artifacts=_Artifacts(contents),
        expected_source_revision="1" * 40,
    )
    with pytest.raises(PolicyError) as failure:
        repository.publish(candidate)
    assert failure.value.code == "POLICY_IMMUTABLE"
    assert repository.get(authorization.policy_id) == authorization
    assert {
        path: (path.read_bytes(), path.stat().st_mtime_ns)
        for path in tmp_path.iterdir()
    } == before


def test_refused_decision_cannot_supply_market_inputs_or_become_a_policy():
    manifest, snapshot, policy, _, contents, evidence = _bound()
    refused = build_automatic_market_policy_evidence(
        source_revision=evidence.source_revision,
        plan_decision=evidence.plan_decision,
        policy=evidence.decision.policy,
        admissions=(),
    )
    assert refused.decision.status == "refused" and refused.decision.inputs is None
    assert refused.decision.issue_codes
    refs = []
    for ref in manifest.artifact_refs:
        if ref.role == AUTOMATIC_MARKET_POLICY_ROLE:
            raw = canonical_bytes(refused)
            ref = ref.model_copy(
                update={"content_hash": hashlib.sha256(raw).hexdigest()}
            )
            contents[ref.artifact_id] = raw
        refs.append(ref)
    authorization = _authorization(
        policy,
        market_inputs=None,
        source_refs=(
            AUTOMATIC_MARKET_POLICY_REF_PREFIX + sha256_digest(refused),
            *policy.source_refs[1:],
        ),
    )
    with pytest.raises(DataReleaseError) as failure:
        assemble_authorized_market_policy_record(
            manifest.model_copy(update={"artifact_refs": tuple(refs)}),
            authorization=authorization,
            model=initial_model_specs()[0],
            snapshot=snapshot,
            admissions=(),
            artifacts=_Artifacts(contents),
            expected_source_revision=evidence.source_revision,
        )
    assert failure.value.code == "AUTOMATIC_MARKET_POLICY_INPUTS_MISMATCH"
    assert authorization.market_inputs is None


@pytest.mark.parametrize(
    "change,code",
    [
        ("model", "AUTOMATIC_MARKET_POLICY_MODEL_MISMATCH"),
        ("profile", "AUTOMATIC_MARKET_POLICY_MODEL_MISMATCH"),
        ("issuer", "AUTOMATIC_MARKET_POLICY_CONTEXT_MISMATCH"),
        ("policy_id", "AUTOMATIC_MARKET_POLICY_CONTEXT_MISMATCH"),
        ("version", "AUTOMATIC_MARKET_POLICY_CONTEXT_MISMATCH"),
        ("decision_authority", "AUTOMATIC_MARKET_POLICY_UNAPPROVED"),
        ("plan_authority", "AUTOMATIC_MARKET_POLICY_PLAN_UNAPPROVED"),
        ("revision", "AUTOMATIC_MARKET_POLICY_REVISION_MISMATCH"),
        ("source", "AUTOMATIC_MARKET_POLICY_REPLAY_MISMATCH"),
        ("prefilled_value", "AUTOMATIC_MARKET_POLICY_INPUTS_MISMATCH"),
        ("future", "POLICY_NOT_EFFECTIVE"),
        ("retired", "POLICY_NOT_EFFECTIVE"),
        ("missing", "AUTOMATIC_MARKET_POLICY_EVIDENCE_MISSING"),
        ("ambiguous", "AUTOMATIC_MARKET_POLICY_EVIDENCE_AMBIGUOUS"),
        ("changed", "AUTOMATIC_MARKET_POLICY_EVIDENCE_MISMATCH"),
        ("noncanonical", "AUTOMATIC_MARKET_POLICY_EVIDENCE_NONCANONICAL"),
    ],
)
def test_policy_assembly_retains_missing_conflicting_or_unauthorized_inputs(
    change, code
):
    manifest, snapshot, policy, admissions, contents, _ = _bound()
    authorization = _authorization(policy, market_inputs=None)
    expected_revision = "1" * 40
    if change == "model":
        authorization = _authorization(authorization, model_version="other-version")
    elif change == "profile":
        authorization = _authorization(authorization, profile_id="other-profile")
    elif change in {"issuer", "policy_id", "version"}:
        field = {"issuer": "issuer_id", "version": "policy_version"}.get(change, change)
        authorization = _authorization(authorization, **{field: "other"})
    elif change == "decision_authority":
        authorization = _authorization(authorization, source_refs=("unapproved",))
    elif change == "plan_authority":
        authorization = _authorization(
            authorization, source_refs=(policy.source_refs[0],)
        )
    elif change == "revision":
        expected_revision = "2" * 40
    elif change == "source":
        admissions = admissions[:-1]
    elif change == "prefilled_value":
        inputs = policy.market_inputs.model_dump()
        inputs["beta"] += Decimal("0.1")
        for item in inputs["evidence"]:
            if item["role"] == "beta":
                item["value"] = inputs["beta"]
        authorization = _authorization(policy, market_inputs=inputs)
    elif change == "future":
        authorization = _authorization(
            authorization, effective_at=AT + timedelta(days=1)
        )
    elif change == "retired":
        authorization = _authorization(authorization, status="retired")
    else:
        ref = next(
            x for x in manifest.artifact_refs if x.role == AUTOMATIC_MARKET_POLICY_ROLE
        )
        if change == "missing":
            refs = tuple(x for x in manifest.artifact_refs if x != ref)
        elif change == "ambiguous":
            refs = (*manifest.artifact_refs, ref)
        else:
            contents[ref.artifact_id] += b" "
            refs = tuple(
                x.model_copy(
                    update={
                        "content_hash": hashlib.sha256(
                            contents[x.artifact_id]
                        ).hexdigest()
                    }
                )
                if x == ref and change == "noncanonical"
                else x
                for x in manifest.artifact_refs
            )
        manifest = manifest.model_copy(update={"artifact_refs": refs})
    before = canonical_bytes(authorization), dict(contents)
    with pytest.raises((DataReleaseError, PolicyError)) as failure:
        assemble_authorized_market_policy_record(
            manifest,
            authorization=authorization,
            model=initial_model_specs()[0],
            snapshot=snapshot,
            admissions=admissions,
            artifacts=_Artifacts(contents),
            expected_source_revision=expected_revision,
        )
    assert failure.value.code == code
    assert (canonical_bytes(authorization), contents) == before


def test_release_boundary_retains_missing_or_changed_automatic_evidence():
    manifest, snapshot, policy, admissions, contents, _ = _bound()
    ref = next(
        x for x in manifest.artifact_refs if x.role == AUTOMATIC_MARKET_POLICY_ROLE
    )
    missing = manifest.model_copy(
        update={"artifact_refs": tuple(x for x in manifest.artifact_refs if x != ref)}
    )
    with pytest.raises(DataReleaseError) as error:
        load_release_automatic_market_policy(
            missing,
            snapshot=snapshot,
            policy=policy,
            admissions=admissions,
            artifacts=_Artifacts(contents),
        )
    assert error.value.code == "AUTOMATIC_MARKET_POLICY_EVIDENCE_MISSING"
    contents[ref.artifact_id] = contents[ref.artifact_id] + b" "
    with pytest.raises(DataReleaseError) as error:
        load_release_automatic_market_policy(
            manifest,
            snapshot=snapshot,
            policy=policy,
            admissions=admissions,
            artifacts=_Artifacts(contents),
        )
    assert error.value.code == "AUTOMATIC_MARKET_POLICY_EVIDENCE_MISMATCH"


@pytest.mark.parametrize(
    "change,code",
    [
        ("issuer", "AUTOMATIC_MARKET_POLICY_CONTEXT_MISMATCH"),
        ("date", "AUTOMATIC_MARKET_POLICY_CONTEXT_MISMATCH"),
        ("currency", "AUTOMATIC_MARKET_POLICY_CONTEXT_MISMATCH"),
        ("version", "AUTOMATIC_MARKET_POLICY_CONTEXT_MISMATCH"),
        ("unpinned", "AUTOMATIC_MARKET_POLICY_UNAPPROVED"),
        ("unapproved_plan", "AUTOMATIC_MARKET_POLICY_PLAN_UNAPPROVED"),
        ("missing_source", "AUTOMATIC_MARKET_POLICY_REPLAY_MISMATCH"),
        ("value", "AUTOMATIC_MARKET_POLICY_INPUTS_MISMATCH"),
        ("revision", "AUTOMATIC_MARKET_POLICY_REVISION_MISMATCH"),
    ],
)
def test_rehashed_inputs_cannot_substitute_context_sources_or_policy(change, code):
    manifest, snapshot, policy, admissions, contents, _ = _bound()
    kwargs = {}
    if change in {"issuer", "currency"}:
        snapshot = snapshot.model_copy(
            update={
                "identity": snapshot.identity.model_copy(
                    update={"issuer_id": "other"}
                    if change == "issuer"
                    else {"currency": "EUR"}
                )
            }
        )
    elif change == "date":
        snapshot = snapshot.model_copy(
            update={"valuation_timestamp": AT + timedelta(days=1)}
        )
    elif change == "missing_source":
        admissions = admissions[:-1]
    elif change == "revision":
        kwargs["expected_source_revision"] = "2" * 40
    else:
        payload = policy.model_dump(exclude={"policy_digest"})
        if change == "version":
            payload["policy_version"] = "changed-version"
        elif change == "unpinned":
            payload["source_refs"] = ("other",)
        elif change == "unapproved_plan":
            payload["source_refs"] = (policy.source_refs[0],)
        else:
            payload["market_inputs"]["beta"] += Decimal("0.1")
            for item in payload["market_inputs"]["evidence"]:
                if item["role"] == "beta":
                    item["value"] = payload["market_inputs"]["beta"]
        policy = PolicyRecordV1(**payload, policy_digest=sha256_digest(payload))
    with pytest.raises(DataReleaseError) as error:
        load_release_automatic_market_policy(
            manifest,
            snapshot=snapshot,
            policy=policy,
            admissions=admissions,
            artifacts=_Artifacts(contents),
            **kwargs,
        )
    assert error.value.code == code


def _service_bound(fixture):
    at = fixture.snapshot.valuation_timestamp
    inputs = (*_reference_inputs(at), *macro_inputs(at=at))
    rules = {rule.rule_id: rule for item in inputs for rule in item["policy"].rules}
    source_policy = SourceUsePolicyV1(
        policy_version="synthetic-full-market-policy-v1",
        rules=tuple(rules[key] for key in sorted(rules)),
    )
    manifest = fixture.manifest
    admissions = []
    for item in inputs:
        item = {**item, "policy": source_policy}
        admission = (
            admit_reference_source(AlternateReferenceProvider(), **item)
            if "metric" in item
            else admit_macro_source(AnnualAndDailyProvider(), **item)
        )
        admissions.append(admission)
        manifest, artifacts, _, _ = _packet(manifest, result=admission, inputs=item)
        for name, content in artifacts.data.items():
            fixture.artifacts.put_bytes_with_receipt(name, content)
    manifest, _, policy, admissions, contents, evidence = _bound(
        manifest=manifest,
        snapshot=fixture.snapshot,
        admissions=tuple(admissions),
    )
    for name, raw in contents.items():
        fixture.artifacts.put_bytes_with_receipt(name, raw)
    policy = assemble_authorized_market_policy_record(
        manifest,
        authorization=_authorization(policy, market_inputs=None),
        model=initial_model_specs()[0],
        snapshot=fixture.snapshot,
        admissions=admissions,
        artifacts=fixture.artifacts,
        expected_source_revision=evidence.source_revision,
    )
    application = replace(
        fixture.application,
        metadata_store=replace_metadata(fixture, manifest),
        policy_registry=PolicyRegistry(initial_model_specs(), (policy,)),
        macro_providers=(AnnualAndDailyProvider(),),
        reference_providers=(AlternateReferenceProvider(),),
        source_use_policy=source_policy,
    )
    return manifest, policy, application, evidence


@pytest.mark.parametrize(
    "change,code",
    [
        (None, None),
        ("missing_provider", "SOURCE_ADMISSION_PROVIDER_UNAVAILABLE"),
        ("missing_evidence", "AUTOMATIC_MARKET_POLICY_EVIDENCE_MISSING"),
        ("changed_value", "AUTOMATIC_MARKET_POLICY_INPUTS_MISMATCH"),
    ],
)
def test_serving_and_canary_reproduce_the_same_automatic_policy(tmp_path, change, code):
    fixture = _fixture(tmp_path)
    candidate, canary = _reviewed_candidate(fixture)
    fixture.manifest = candidate.manifest
    manifest, policy, application, evidence = _service_bound(fixture)
    if change == "missing_provider":
        application = replace(application, reference_providers=())
    elif change == "missing_evidence":
        payload = manifest.model_dump(exclude={"manifest_digest"})
        payload["artifact_refs"] = tuple(
            ref
            for ref in manifest.artifact_refs
            if ref.role != AUTOMATIC_MARKET_POLICY_ROLE
        )
        manifest = DataReleaseManifestV1(
            **payload, manifest_digest=sha256_digest(payload)
        )
        policy = _authorization(
            policy, data_release_manifest_digest=manifest.manifest_digest
        )
    elif change == "changed_value":
        payload = policy.model_dump(exclude={"policy_digest"})
        payload["market_inputs"]["beta"] += Decimal("0.1")
        for item in payload["market_inputs"]["evidence"]:
            if item["role"] == "beta":
                item["value"] = payload["market_inputs"]["beta"]
        policy = PolicyRecordV1(**payload, policy_digest=sha256_digest(payload))
    application = replace(
        application,
        metadata_store=replace_metadata(fixture, manifest),
        policy_registry=PolicyRegistry(initial_model_specs(), (policy,)),
    )
    request = ValuationEvidenceReadRequestV1(
        contract_version="fundamental.v1",
        snapshot_id=fixture.snapshot.snapshot_id,
        data_release_manifest_digest=manifest.manifest_digest,
        model_id="fcff_dcf",
    )
    if code:
        with pytest.raises(ServiceError) as error:
            application.prepare_valuation(request)
        assert error.value.code == code
    else:
        prepared = application.prepare_valuation(request)
        assert prepared.status == "prepared"
        assert prepared.quality_status is QualityStatus.PROVISIONAL
        assert "HISTORY_THRESHOLD_UNVALIDATED" in prepared.issue_codes
        assert prepared.input.assumptions.wacc.beta == evidence.decision.inputs.beta
    payload = candidate.verification.model_dump(
        exclude={"signature", "verification_digest"}
    )
    payload["manifest_digest"] = manifest.manifest_digest
    verification = sign_data_release_verification(
        payload,
        Ed25519PrivateKey.from_private_bytes(b"verifier-key".ljust(32, b"0")),
    )
    runner = DataReleaseCanaryRunner(
        snapshot_repository=fixture.snapshots,
        fact_repository=fixture.facts,
        mapping_reader=fixture.metadata,
        artifact_reader=canary._artifacts,
        trust_roots=canary._trust_roots,
        quote_providers=default_quote_providers(),
        macro_providers=application.macro_providers,
        reference_providers=application.reference_providers,
        source_use_policy=application.source_use_policy,
        policy_registry=application.policy_registry,
    )
    before = {
        p: (p.read_bytes(), p.stat().st_mtime_ns)
        for p in tmp_path.rglob("*")
        if p.is_file()
    }
    if code:
        with pytest.raises(DataReleaseError) as error:
            runner.validate(manifest, verification)
        assert error.value.code == code
    else:
        first = runner.validate(manifest, verification)
        assert len(first.market_policy_checks) == 1
        assert runner.validate(manifest, verification) == first
        assert application.prepare_valuation(request) == prepared
    assert before == {
        p: (p.read_bytes(), p.stat().st_mtime_ns)
        for p in tmp_path.rglob("*")
        if p.is_file()
    }
