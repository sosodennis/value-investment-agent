from dataclasses import replace
from decimal import Decimal
import hashlib

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from fundamental_service.application.service import ServiceError
from fundamental_service.contracts import QualityStatus, ValuationEvidenceReadRequestV1
from fundamental_service.data_releases import (
    ArtifactRefV1,
    DataReleaseError,
    DataReleaseManifestV1,
    sign_data_release_verification,
)
from fundamental_service.policies import (
    PolicyRecordV1,
    PolicyRegistry,
    initial_model_specs,
)
from fundamental_service.quote_sources import default_quote_providers
from fundamental_service.release_runner import DataReleaseCanaryRunner
from fundamental_service.serialization import canonical_bytes, sha256_digest
from fundamental_service.source_admission import admit_macro_source
from fundamental_service.terminal_growth import (
    select_terminal_growth,
    terminal_growth_evidence,
)
from fundamental_service.terminal_growth_evidence import (
    TERMINAL_GROWTH_PLAN_ROLE,
    load_release_terminal_growth_selection,
)
from test_market_source_binding import _observed_market_inputs
from test_preparation_runner import _fixture, _reviewed_candidate
from test_source_admission_evidence import _packet
from test_terminal_growth import AnnualAndDailyProvider, _inputs, _plan


def _bound(fixture):
    rate_inputs, gdp_inputs = _inputs(at=fixture.snapshot.valuation_timestamp)
    admissions = tuple(
        admit_macro_source(AnnualAndDailyProvider(), **inputs)
        for inputs in (rate_inputs, gdp_inputs)
    )
    manifest = fixture.manifest
    for inputs, admission in zip((rate_inputs, gdp_inputs), admissions, strict=True):
        manifest, artifacts, _, _ = _packet(manifest, result=admission, inputs=inputs)
        for name, content in artifacts.data.items():
            fixture.artifacts.put_bytes_with_receipt(name, content)
    plan = _plan(issuer_id=fixture.snapshot.identity.issuer_id)
    selection = select_terminal_growth(plan, admissions=admissions)
    raw = canonical_bytes(plan)
    ref = ArtifactRefV1(
        artifact_id="terminal-plan:" + sha256_digest(plan),
        content_hash=hashlib.sha256(raw).hexdigest(),
        media_type="application/json",
        role=TERMINAL_GROWTH_PLAN_ROLE,
    )
    fixture.artifacts.put_bytes_with_receipt(ref.artifact_id, raw)
    payload = manifest.model_dump(exclude={"manifest_digest"})
    payload["artifact_refs"] = tuple(
        {x.artifact_id: x for x in (*manifest.artifact_refs, ref)}.values()
    )
    manifest = DataReleaseManifestV1(**payload, manifest_digest=sha256_digest(payload))
    policy = fixture.application.policy_registry.policy(plan.policy_id)
    payload = policy.model_dump(exclude={"policy_digest"})
    payload["issuer_id"] = plan.issuer_id
    payload["source_refs"] = (*policy.source_refs, ref.content_hash)
    market = payload["market_inputs"]
    rate_evidence = next(
        x
        for x in _observed_market_inputs(admissions[0]).evidence
        if x.role == "risk_free_rate"
    )
    market["risk_free_rate"] = rate_evidence.value
    market["terminal_growth"] = selection.value
    market["evidence"] = tuple(
        rate_evidence
        if x["role"] == "risk_free_rate"
        else terminal_growth_evidence(selection)
        if x["role"] == "terminal_growth"
        else x
        for x in market["evidence"]
    )
    policy = PolicyRecordV1(**payload, policy_digest=sha256_digest(payload))
    metadata = replace_metadata(fixture, manifest)
    application = replace(
        fixture.application,
        metadata_store=metadata,
        policy_registry=PolicyRegistry(initial_model_specs(), (policy,)),
        macro_providers=(AnnualAndDailyProvider(),),
        source_use_policy=rate_inputs["policy"],
    )
    return manifest, plan, selection, admissions, policy, application


def replace_metadata(fixture, manifest):
    from types import SimpleNamespace

    return SimpleNamespace(
        get_mapping=fixture.metadata.get_mapping,
        get_data_release_manifest=lambda digest: manifest
        if digest == manifest.manifest_digest
        else None,
    )


def _request(fixture, manifest):
    return ValuationEvidenceReadRequestV1(
        contract_version="fundamental.v1",
        snapshot_id=fixture.snapshot.snapshot_id,
        data_release_manifest_digest=manifest.manifest_digest,
        model_id="fcff_dcf",
    )


def test_formal_preparation_reproduces_terminal_assumption_and_original_traces(
    tmp_path,
):
    fixture = _fixture(tmp_path)
    manifest, plan, selection, admissions, policy, application = _bound(fixture)
    prepared = application.prepare_valuation(_request(fixture, manifest))
    assert prepared.status == "prepared"
    assert prepared.input.assumptions.terminal_growth == selection.value
    assert prepared.quality_status is QualityStatus.PROVISIONAL
    assert "HISTORY_THRESHOLD_UNVALIDATED" in prepared.issue_codes
    evidence = next(
        x
        for x in prepared.assumptions_evidence
        if x.path == "assumptions.terminal_growth"
    )
    assert evidence.source_refs == selection.trace.source_refs
    assert evidence.method == "approved_policy"
    assert evidence.as_of == selection.trace.as_of
    before = {
        p: (p.read_bytes(), p.stat().st_mtime_ns)
        for p in tmp_path.rglob("*")
        if p.is_file()
    }
    assert application.prepare_valuation(_request(fixture, manifest)) == prepared
    assert before == {
        p: (p.read_bytes(), p.stat().st_mtime_ns)
        for p in tmp_path.rglob("*")
        if p.is_file()
    }


@pytest.mark.parametrize(
    "change",
    [
        "value",
        "source",
        "risk_free",
        "rate_method",
        "terminal_method",
        "unpinned",
    ],
)
def test_rehashed_policy_cannot_change_source_bound_terminal_assumption(
    tmp_path, change
):
    fixture = _fixture(tmp_path)
    manifest, plan, selection, admissions, policy, application = _bound(fixture)
    payload = policy.model_dump(exclude={"policy_digest"})
    market = payload["market_inputs"]
    if change == "unpinned":
        payload["source_refs"] = tuple(
            x for x in policy.source_refs if x != sha256_digest(plan)
        )
    else:
        role = (
            "risk_free_rate"
            if change in {"risk_free", "rate_method"}
            else "terminal_growth"
        )
        evidence = next(x for x in market["evidence"] if x["role"] == role)
        if change == "source":
            evidence["content_hash"] = "a" * 64
        elif change in {"rate_method", "terminal_method"}:
            evidence["method"] = (
                "approved_policy" if change == "rate_method" else "observed_source"
            )
        else:
            market[role] += Decimal("0.001")
            evidence["value"] = market[role]
    changed = PolicyRecordV1(**payload, policy_digest=sha256_digest(payload))
    changed_app = replace(
        application, policy_registry=PolicyRegistry(initial_model_specs(), (changed,))
    )
    with pytest.raises(ServiceError) as error:
        changed_app.prepare_valuation(_request(fixture, manifest))
    assert error.value.code == (
        "TERMINAL_PLAN_UNAPPROVED"
        if change == "unpinned"
        else "TERMINAL_POLICY_SOURCE_MISMATCH"
    )


@pytest.mark.parametrize(
    "change,code",
    [
        ("none", None),
        ("changed", "TERMINAL_POLICY_SOURCE_MISMATCH"),
        ("issuer", "POLICY_NOT_FOUND"),
        ("authority", "MARKET_REFERENCE_POLICY_UNAVAILABLE"),
        ("missing", "TERMINAL_PLAN_MISSING"),
        ("missing_ambiguous", "POLICY_AMBIGUOUS"),
        ("missing_foreign", "TERMINAL_PLAN_MISSING"),
    ],
)
def test_independent_canary_uses_the_same_effective_terminal_policy(
    tmp_path, change, code
):
    fixture = _fixture(tmp_path)
    candidate, canary = _reviewed_candidate(fixture)
    fixture.manifest = candidate.manifest
    manifest, plan, selection, admissions, policy, application = _bound(fixture)
    if change in {"missing", "missing_ambiguous", "missing_foreign"}:
        payload = manifest.model_dump(exclude={"manifest_digest"})
        payload["artifact_refs"] = tuple(
            x for x in manifest.artifact_refs if x.role != TERMINAL_GROWTH_PLAN_ROLE
        )
        manifest = DataReleaseManifestV1(
            **payload, manifest_digest=sha256_digest(payload)
        )
        if change == "missing":
            missing_app = replace(
                application, metadata_store=replace_metadata(fixture, manifest)
            )
            with pytest.raises(ServiceError) as error:
                missing_app.prepare_valuation(_request(fixture, manifest))
            assert error.value.code == code
    payload = candidate.verification.model_dump(
        exclude={"signature", "verification_digest"}
    )
    payload["manifest_digest"] = manifest.manifest_digest
    verification = sign_data_release_verification(
        payload, Ed25519PrivateKey.from_private_bytes(b"verifier-key".ljust(32, b"0"))
    )
    registry = application.policy_registry
    if change in {"missing_ambiguous", "missing_foreign"}:
        payload = policy.model_dump(exclude={"policy_digest"})
        payload["policy_id"] = "second-equal-policy"
        if change == "missing_foreign":
            payload["issuer_id"] = "different-issuer"
            payload["model_version"] = "unimplemented-v999"
        second = PolicyRecordV1(**payload, policy_digest=sha256_digest(payload))
        registry = PolicyRegistry(initial_model_specs(), (second, policy))
        missing_app = replace(
            application,
            metadata_store=replace_metadata(fixture, manifest),
            policy_registry=registry,
        )
        with pytest.raises(ServiceError) as error:
            missing_app.prepare_valuation(_request(fixture, manifest))
        assert error.value.code == code
    if change in {"changed", "issuer"}:
        payload = policy.model_dump(exclude={"policy_digest"})
        if change == "issuer":
            payload["issuer_id"] = "different-issuer"
        else:
            payload["market_inputs"]["terminal_growth"] += Decimal("0.001")
            next(
                x
                for x in payload["market_inputs"]["evidence"]
                if x["role"] == "terminal_growth"
            )["value"] = payload["market_inputs"]["terminal_growth"]
        registry = PolicyRegistry(
            initial_model_specs(),
            (PolicyRecordV1(**payload, policy_digest=sha256_digest(payload)),),
        )
    runner = DataReleaseCanaryRunner(
        snapshot_repository=fixture.snapshots,
        fact_repository=fixture.facts,
        mapping_reader=fixture.metadata,
        artifact_reader=canary._artifacts,
        trust_roots=canary._trust_roots,
        policy_registry=None if change == "authority" else registry,
        macro_providers=application.macro_providers,
        source_use_policy=application.source_use_policy,
        quote_providers=default_quote_providers(),
    )
    if code:
        with pytest.raises(DataReleaseError) as error:
            runner.validate(manifest, verification)
        assert error.value.code == code
    else:
        result = runner.validate(manifest, verification)
        assert result.market_policy_checks
        assert runner.validate(manifest, verification) == result


@pytest.mark.parametrize(
    "change,code",
    [
        ("issuer", "TERMINAL_PLAN_CONTEXT_MISMATCH"),
        ("policy_issuer", "TERMINAL_PLAN_ISSUER_POLICY_MISMATCH"),
        ("bytes", "TERMINAL_PLAN_MISMATCH"),
        ("duplicate", "TERMINAL_PLAN_AMBIGUOUS"),
    ],
)
def test_terminal_plan_release_context_and_original_identity_cannot_be_substituted(
    tmp_path, change, code
):
    fixture = _fixture(tmp_path)
    manifest, plan, selection, admissions, policy, application = _bound(fixture)
    snapshot = fixture.snapshot
    if change == "issuer":
        snapshot = snapshot.model_copy(
            update={
                "identity": snapshot.identity.model_copy(
                    update={"issuer_id": "different"}
                )
            }
        )
    elif change == "policy_issuer":
        payload = policy.model_dump(exclude={"policy_digest"})
        payload["issuer_id"] = "different-issuer"
        changed_policy = PolicyRecordV1(**payload, policy_digest=sha256_digest(payload))
        with pytest.raises(DataReleaseError) as error:
            load_release_terminal_growth_selection(
                manifest,
                snapshot=snapshot,
                policy=changed_policy,
                admissions=admissions,
                artifacts=fixture.artifacts,
            )
        assert error.value.code == "TERMINAL_PLAN_ISSUER_POLICY_MISMATCH"
        return
    else:
        refs = manifest.artifact_refs
        ref = next(x for x in refs if x.role == TERMINAL_GROWTH_PLAN_ROLE)
        refs = (
            (*refs, ref.model_copy(update={"artifact_id": "duplicate-terminal-plan"}))
            if change == "duplicate"
            else tuple(
                x.model_copy(update={"content_hash": "f" * 64}) if x == ref else x
                for x in refs
            )
        )
        payload = manifest.model_dump(exclude={"manifest_digest"})
        payload["artifact_refs"] = refs
        manifest = DataReleaseManifestV1(
            **payload, manifest_digest=sha256_digest(payload)
        )
    with pytest.raises(DataReleaseError) as error:
        load_release_terminal_growth_selection(
            manifest,
            snapshot=snapshot,
            policy=policy,
            admissions=admissions,
            artifacts=fixture.artifacts,
        )
    assert error.value.code == code


@pytest.mark.parametrize(
    "change,code",
    [
        ("invalid", "TERMINAL_PLAN_INVALID"),
        ("noncanonical", "TERMINAL_PLAN_NONCANONICAL"),
    ],
)
def test_terminal_plan_requires_canonical_valid_bytes(tmp_path, change, code):
    from test_source_admission_evidence import DictionaryArtifacts

    fixture = _fixture(tmp_path)
    manifest, plan, selection, admissions, policy, application = _bound(fixture)
    raw = b"{}" if change == "invalid" else canonical_bytes(plan) + b"\n"
    refs = tuple(
        x.model_copy(update={"content_hash": hashlib.sha256(raw).hexdigest()})
        if x.role == TERMINAL_GROWTH_PLAN_ROLE
        else x
        for x in manifest.artifact_refs
    )
    payload = manifest.model_dump(exclude={"manifest_digest"})
    payload["artifact_refs"] = refs
    changed = DataReleaseManifestV1(**payload, manifest_digest=sha256_digest(payload))
    reader = DictionaryArtifacts(
        {x.artifact_id: raw for x in refs if x.role == TERMINAL_GROWTH_PLAN_ROLE}
    )
    with pytest.raises(DataReleaseError) as error:
        load_release_terminal_growth_selection(
            changed,
            snapshot=fixture.snapshot,
            policy=policy,
            admissions=admissions,
            artifacts=reader,
        )
    assert error.value.code == code
