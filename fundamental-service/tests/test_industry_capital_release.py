from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from fundamental_service.contracts import QualityStatus, ValuationEvidenceReadRequestV1
from fundamental_service.data_releases import (
    ArtifactRefV1,
    DataReleaseError,
    DataReleaseManifestV1,
    sign_data_release_verification,
)
from fundamental_service.damodaran_source import DamodaranReferenceProvider
from fundamental_service.industry_capital import (
    adopt_industry_capital,
    industry_capital_evidence,
)
from fundamental_service.market_reference_evidence import (
    MARKET_REFERENCE_PLAN_ROLE,
    load_release_market_reference_selection,
)
from fundamental_service.market_reference_selection import (
    select_issuer_market_references,
)
from fundamental_service.operations import ServiceError
from fundamental_service.policies import (
    PolicyRecordV1,
    PolicyRegistry,
    initial_model_specs,
)
from fundamental_service.quote_sources import default_quote_providers
from fundamental_service.release_runner import DataReleaseCanaryRunner
from fundamental_service.serialization import canonical_bytes, sha256_digest
from fundamental_service.source_admission import admit_reference_source
from test_industry_capital_policy import capital_inputs, capital_plan
from test_preparation_runner import _fixture, _reviewed_candidate
from test_source_admission_evidence import _packet
from test_terminal_growth_evidence import replace_metadata


def bound(fixture):
    inputs = capital_inputs(fixture.snapshot.valuation_timestamp)
    from quote_provider_fixtures import bind_synthetic_quote_permission

    source_policy = bind_synthetic_quote_permission(fixture, inputs[0]["policy"])
    for item in inputs:
        item["policy"] = source_policy
    admissions = tuple(
        admit_reference_source(DamodaranReferenceProvider(), **item) for item in inputs
    )
    manifest = fixture.manifest
    for item, result in zip(inputs, admissions, strict=True):
        manifest, artifacts, _, _ = _packet(manifest, result=result, inputs=item)
        for name, raw in artifacts.data.items():
            fixture.artifacts.put_bytes_with_receipt(name, raw)
    plan = capital_plan(
        fixture.snapshot.valuation_timestamp, fixture.snapshot.identity.issuer_id
    )
    assumptions = adopt_industry_capital(
        select_issuer_market_references(plan, admissions=admissions)
    )
    raw = canonical_bytes(plan)
    ref = ArtifactRefV1(
        artifact_id="industry-capital-plan-" + sha256_digest(plan),
        content_hash=sha256_digest(plan),
        media_type="application/json",
        role=MARKET_REFERENCE_PLAN_ROLE,
    )
    fixture.artifacts.put_bytes_with_receipt(ref.artifact_id, raw)
    payload = manifest.model_dump(exclude={"manifest_digest"})
    payload["artifact_refs"] = (*manifest.artifact_refs, ref)
    manifest = DataReleaseManifestV1(**payload, manifest_digest=sha256_digest(payload))
    policy = fixture.application.policy_registry.policy(plan.policy_id)
    payload = policy.model_dump(exclude={"policy_digest"})
    payload["issuer_id"] = plan.issuer_id
    payload["source_refs"] = (*policy.source_refs, ref.content_hash)
    market = payload["market_inputs"]
    market.update(assumptions.values)
    evidence = {item.role: item for item in industry_capital_evidence(assumptions)}
    market["evidence"] = tuple(
        evidence.get(item["role"], item) for item in market["evidence"]
    )
    policy = PolicyRecordV1(**payload, policy_digest=sha256_digest(payload))
    application = replace(
        fixture.application,
        metadata_store=replace_metadata(fixture, manifest),
        policy_registry=PolicyRegistry(initial_model_specs(), (policy,)),
        reference_providers=(DamodaranReferenceProvider(),),
        source_use_policy=inputs[0]["policy"],
    )
    return manifest, admissions, policy, application


def request(fixture, manifest):
    return ValuationEvidenceReadRequestV1(
        contract_version="fundamental.v1",
        snapshot_id=fixture.snapshot.snapshot_id,
        data_release_manifest_digest=manifest.manifest_digest,
        model_id="fcff_dcf",
    )


def test_formal_composer_consumes_policy_assumptions_and_retains_actual_source_traces(
    tmp_path,
):
    fixture = _fixture(tmp_path)
    manifest, admissions, policy, application = bound(fixture)
    first = application.prepare_valuation(request(fixture, manifest))
    assert first.status == "prepared"
    assert first.quality_status is QualityStatus.PROVISIONAL
    assert "HISTORY_THRESHOLD_UNVALIDATED" in first.issue_codes
    assert first.input.assumptions.wacc.beta == policy.market_inputs.beta
    assert (
        first.input.assumptions.wacc.pre_tax_cost_of_debt
        == policy.market_inputs.pre_tax_cost_of_debt
    )
    assert (
        first.input.assumptions.wacc.debt_weight
        + first.input.assumptions.wacc.equity_weight
        == 1
    )
    roles = ("beta", "pre_tax_cost_of_debt", "debt_weight", "equity_weight")
    evidence = tuple(
        item
        for item in first.assumptions_evidence
        if item.path.rsplit(".", 1)[-1] in roles
    )
    assert len(evidence) == 4
    assert all(item.method == "approved_policy" for item in evidence)
    selected = load_release_market_reference_selection(
        manifest,
        snapshot=fixture.snapshot,
        policy=policy,
        admissions=admissions,
        artifacts=fixture.artifacts,
    )
    assumptions = adopt_industry_capital(selected)
    for item in evidence:
        role = item.path.rsplit(".", 1)[-1]
        assert item.source_refs == assumptions.traces[role].source_refs
        assert selected.output_digest in item.source_refs
        assert admissions[0].vintage.artifacts[0].content_sha256 in item.source_refs
        assert item.as_of == assumptions.traces[role].as_of
    before = {
        p: (p.read_bytes(), p.stat().st_mtime_ns)
        for p in tmp_path.rglob("*")
        if p.is_file()
    }
    assert application.prepare_valuation(request(fixture, manifest)) == first
    assert before == {
        p: (p.read_bytes(), p.stat().st_mtime_ns)
        for p in tmp_path.rglob("*")
        if p.is_file()
    }


@pytest.mark.parametrize(
    "change,code",
    [
        ("none", None),
        ("value", "INDUSTRY_CAPITAL_POLICY_SOURCE_MISMATCH"),
        ("source", "INDUSTRY_CAPITAL_POLICY_SOURCE_MISMATCH"),
        ("method", "INDUSTRY_CAPITAL_POLICY_SOURCE_MISMATCH"),
        ("missing", "INDUSTRY_CAPITAL_PLAN_MISSING"),
        ("ambiguous", "POLICY_AMBIGUOUS"),
        ("foreign", "POLICY_NOT_FOUND"),
        ("authority", "MARKET_REFERENCE_POLICY_UNAVAILABLE"),
    ],
)
def test_serving_and_independent_canary_reproduce_capital_policy_and_retain_refusals(
    tmp_path, change, code
):
    fixture = _fixture(tmp_path)
    candidate, canary = _reviewed_candidate(fixture)
    fixture.manifest = candidate.manifest
    manifest, _, policy, application = bound(fixture)
    policies = [policy]
    if change in {"missing", "ambiguous"}:
        payload = manifest.model_dump(exclude={"manifest_digest"})
        payload["artifact_refs"] = tuple(
            item
            for item in manifest.artifact_refs
            if item.role != MARKET_REFERENCE_PLAN_ROLE
        )
        manifest = DataReleaseManifestV1(
            **payload, manifest_digest=sha256_digest(payload)
        )
        if change == "ambiguous":
            payload = policy.model_dump(exclude={"policy_digest"})
            payload["policy_id"] = "second-equal-policy"
            policies.append(
                PolicyRecordV1(**payload, policy_digest=sha256_digest(payload))
            )
    elif change in {"value", "source", "method", "foreign"}:
        payload = policy.model_dump(exclude={"policy_digest"})
        if change == "foreign":
            payload["issuer_id"] = "foreign-issuer"
        else:
            item = next(
                item
                for item in payload["market_inputs"]["evidence"]
                if item["role"] == "beta"
            )
            if change == "value":
                payload["market_inputs"]["beta"] += Decimal("0.01")
                item["value"] = payload["market_inputs"]["beta"]
            elif change == "source":
                item["content_hash"] = "a" * 64
            else:
                item["method"] = "observed_source"
        policies = [PolicyRecordV1(**payload, policy_digest=sha256_digest(payload))]
    registry = PolicyRegistry(initial_model_specs(), policies)
    application = replace(
        application,
        metadata_store=replace_metadata(fixture, manifest),
        policy_registry=registry,
    )
    if change != "authority":
        if code:
            with pytest.raises(ServiceError) as caught:
                application.prepare_valuation(request(fixture, manifest))
            assert caught.value.code == code
        else:
            assert (
                application.prepare_valuation(request(fixture, manifest)).status
                == "prepared"
            )
    payload = candidate.verification.model_dump(
        exclude={"signature", "verification_digest"}
    )
    payload["manifest_digest"] = manifest.manifest_digest
    verification = sign_data_release_verification(
        payload, Ed25519PrivateKey.from_private_bytes(b"verifier-key".ljust(32, b"0"))
    )
    runner = DataReleaseCanaryRunner(
        snapshot_repository=fixture.snapshots,
        fact_repository=fixture.facts,
        mapping_reader=fixture.metadata,
        artifact_reader=canary._artifacts,
        trust_roots=canary._trust_roots,
        reference_providers=application.reference_providers,
        source_use_policy=application.source_use_policy,
        policy_registry=None if change == "authority" else registry,
        quote_providers=default_quote_providers(),
    )
    if code:
        with pytest.raises(DataReleaseError) as caught:
            runner.validate(manifest, verification)
        assert caught.value.code == code
    else:
        result = runner.validate(manifest, verification)
        assert result.market_policy_checks
        assert runner.validate(manifest, verification) == result


@pytest.mark.parametrize(
    "change,code",
    [
        ("issuer", "MARKET_REFERENCE_PLAN_CONTEXT_MISMATCH"),
        ("date", "MARKET_REFERENCE_PLAN_CONTEXT_MISMATCH"),
        ("currency", "INDUSTRY_CAPITAL_CURRENCY_UNSUPPORTED"),
        ("scope", "MARKET_REFERENCE_POLICY_ISSUER_MISMATCH"),
        ("unpinned", "MARKET_REFERENCE_PLAN_UNAPPROVED"),
    ],
)
def test_industry_adoption_is_specific_to_authorized_issuer_time_and_currency(
    tmp_path, change, code
):
    fixture = _fixture(tmp_path)
    manifest, admissions, policy, _ = bound(fixture)
    snapshot = fixture.snapshot
    if change in {"issuer", "currency"}:
        identity = snapshot.identity.model_copy(
            update={"issuer_id": "other"} if change == "issuer" else {"currency": "EUR"}
        )
        snapshot = snapshot.model_copy(update={"identity": identity})
    elif change == "date":
        snapshot = snapshot.model_copy(
            update={
                "valuation_timestamp": snapshot.valuation_timestamp + timedelta(days=1)
            }
        )
    else:
        payload = policy.model_dump(exclude={"policy_digest"})
        if change == "scope":
            payload["issuer_id"] = "other"
        else:
            payload["source_refs"] = ("unrelated-policy",)
        policy = PolicyRecordV1(**payload, policy_digest=sha256_digest(payload))
    with pytest.raises(DataReleaseError) as caught:
        load_release_market_reference_selection(
            manifest,
            snapshot=snapshot,
            policy=policy,
            admissions=admissions,
            artifacts=fixture.artifacts,
        )
    assert caught.value.code == code
