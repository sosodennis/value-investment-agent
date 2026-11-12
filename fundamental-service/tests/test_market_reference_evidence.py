from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
import hashlib

import pytest

from fundamental_service.application.service import ServiceError
from fundamental_service.contracts import ValuationEvidenceReadRequestV1
from fundamental_service.data_releases import (
    ArtifactRefV1,
    DataReleaseError,
    DataReleaseManifestV1,
)
from fundamental_service.market_reference_evidence import (
    MARKET_REFERENCE_PLAN_ROLE,
    load_release_market_reference_selection,
)
from fundamental_service.market_reference_selection import (
    IssuerMarketReferencePlanV1,
    MarketReferenceSelectionPolicyV1,
)
from fundamental_service.policies import (
    PolicyRecordV1,
    PolicyRegistry,
    initial_model_specs,
)
from fundamental_service.serialization import canonical_bytes, sha256_digest
from test_preparation_runner import _fixture, _reviewed_candidate
from test_source_admission import _reference_policy, _source, _terms
from fundamental_service.source_admission import admit_reference_source
from fundamental_service.damodaran_source import DamodaranReferenceProvider
from test_source_admission_evidence import _packet


def _bound(fixture):
    valuation_at = fixture.snapshot.valuation_timestamp
    source = replace(_source(), captured_at=valuation_at - timedelta(days=1))
    inputs = dict(
        metric="country.equity_risk_premium",
        sources=(source,),
        terms=(_terms(),),
        valuation_at=valuation_at,
        policy=_reference_policy(),
    )
    admission = admit_reference_source(DamodaranReferenceProvider(), **inputs)
    manifest, artifacts, _, _ = _packet(
        fixture.manifest, result=admission, inputs=inputs
    )
    plan = IssuerMarketReferencePlanV1(
        issuer_id=fixture.snapshot.identity.issuer_id,
        policy_id="fcff_dcf-us-gaap-public-v3",
        valuation_at=valuation_at,
        selections=(
            MarketReferenceSelectionPolicyV1(
                policy_version="explicit-country-row-v1",
                metric="country.equity_risk_premium",
                population="countries",
                subject_kind="country",
                subject="United States",
                maximum_age_days=730,
            ),
        ),
    )
    raw = canonical_bytes(plan)
    ref = ArtifactRefV1(
        artifact_id="issuer-reference-plan-" + sha256_digest(plan),
        content_hash=hashlib.sha256(raw).hexdigest(),
        media_type="application/json",
        role=MARKET_REFERENCE_PLAN_ROLE,
    )
    artifacts.data[ref.artifact_id] = raw
    payload = manifest.model_dump(exclude={"manifest_digest"})
    payload["artifact_refs"] = (*manifest.artifact_refs, ref)
    manifest = DataReleaseManifestV1(**payload, manifest_digest=sha256_digest(payload))
    policy = fixture.application.policy_registry.policy("fcff_dcf-us-gaap-public-v3")
    payload = policy.model_dump(exclude={"policy_digest"})
    payload["issuer_id"] = plan.issuer_id
    payload["source_refs"] = (*policy.source_refs, ref.content_hash)
    original = admission.vintage.artifacts[0]
    row = next(x for x in admission.vintage.rows if x.subject == "United States")
    market = payload["market_inputs"]
    market["equity_risk_premium"] = row.value
    observed = next(x for x in market["evidence"] if x["role"] == "equity_risk_premium")

    observed.update(
        method="observed_source",
        value=row.value,
        source_id=original.source_id,
        source_uri=original.uri,
        content_hash=original.content_sha256,
        source_version=original.source_version,
        terms_reference=original.terms_reference,
        as_of=datetime.combine(
            admission.vintage.source_updated_on, datetime.min.time(), UTC
        ),
        available_at=admission.vintage.available_at,
        captured_at=admission.vintage.captured_at,
        rationale="Explicit deployment-pinned country reference policy fixture",
    )
    policy = PolicyRecordV1(**payload, policy_digest=sha256_digest(payload))
    return manifest, artifacts, admission, plan, ref, policy


def _load(fixture, manifest, artifacts, admission, policy):
    return load_release_market_reference_selection(
        manifest,
        snapshot=fixture.snapshot,
        policy=policy,
        admissions=(admission,),
        artifacts=artifacts,
    )


def test_release_plan_reproduces_exact_issuer_date_reference_and_remains_unchanged(
    tmp_path,
):
    fixture = _fixture(tmp_path)
    manifest, artifacts, admission, plan, ref, policy = _bound(fixture)
    before = dict(artifacts.data)
    first = _load(fixture, manifest, artifacts, admission, policy)
    assert first.status == "selected"
    assert first.plan == plan
    assert _load(fixture, manifest, artifacts, admission, policy) == first
    assert artifacts.data == before


@pytest.mark.parametrize(
    "change,code",
    [
        ("unapproved", "MARKET_REFERENCE_PLAN_UNAPPROVED"),
        ("duplicate", "MARKET_REFERENCE_PLAN_AMBIGUOUS"),
        ("bytes", "MARKET_REFERENCE_PLAN_MISMATCH"),
        ("issuer", "MARKET_REFERENCE_PLAN_CONTEXT_MISMATCH"),
        ("policy_issuer", "MARKET_REFERENCE_POLICY_ISSUER_MISMATCH"),
        ("timestamp", "MARKET_REFERENCE_PLAN_CONTEXT_MISMATCH"),
        ("noncanonical", "MARKET_REFERENCE_PLAN_NONCANONICAL"),
        ("invalid", "MARKET_REFERENCE_PLAN_INVALID"),
    ],
)
def test_release_reference_plan_refusals_are_explicit(tmp_path, change, code):
    fixture = _fixture(tmp_path)
    manifest, artifacts, admission, plan, ref, policy = _bound(fixture)
    if change == "unapproved":
        policy = fixture.application.policy_registry.policy(
            "fcff_dcf-us-gaap-public-v3"
        )
    elif change == "policy_issuer":
        payload = policy.model_dump(exclude={"policy_digest"})
        payload["issuer_id"] = "different-issuer"
        policy = PolicyRecordV1(**payload, policy_digest=sha256_digest(payload))
    elif change == "duplicate":
        duplicate = ref.model_copy(update={"artifact_id": "duplicate-plan"})
        manifest = manifest.model_copy(
            update={"artifact_refs": (*manifest.artifact_refs, duplicate)}
        )
    elif change == "bytes":
        artifacts.data[ref.artifact_id] = b"{}"
    else:
        if change == "issuer":
            plan = plan.model_copy(update={"issuer_id": "different-issuer"})
        elif change == "timestamp":
            plan = plan.model_copy(
                update={"valuation_at": plan.valuation_at + timedelta(microseconds=1)}
            )
        raw = canonical_bytes(plan)
        if change == "noncanonical":
            raw += b"\n"
        elif change == "invalid":
            raw = b"{}"
        artifacts.data[ref.artifact_id] = raw
        ref = ref.model_copy(update={"content_hash": hashlib.sha256(raw).hexdigest()})
        manifest = manifest.model_copy(
            update={
                "artifact_refs": tuple(
                    ref if x.role == MARKET_REFERENCE_PLAN_ROLE else x
                    for x in manifest.artifact_refs
                )
            }
        )
        payload = policy.model_dump(exclude={"policy_digest"})
        payload["source_refs"] = (*policy.source_refs, ref.content_hash)
        policy = PolicyRecordV1(**payload, policy_digest=sha256_digest(payload))
    with pytest.raises(DataReleaseError) as error:
        _load(fixture, manifest, artifacts, admission, policy)
    assert error.value.code == code


def test_serving_preparation_consumes_the_pinned_reference_plan_and_exact_erp(tmp_path):
    fixture = _fixture(tmp_path)
    manifest, artifacts, admission, plan, ref, policy = _bound(fixture)
    for name, content in artifacts.data.items():
        fixture.artifacts.put_bytes_with_receipt(name, content)
    previous_lookup = fixture.metadata.get_data_release_manifest
    fixture.metadata.get_data_release_manifest = (
        lambda digest: manifest
        if digest == manifest.manifest_digest
        else previous_lookup(digest)
    )
    app = replace(
        fixture.application,
        policy_registry=PolicyRegistry(initial_model_specs(), (policy,)),
        source_use_policy=_reference_policy(),
        reference_providers=(DamodaranReferenceProvider(),),
    )
    request = ValuationEvidenceReadRequestV1(
        contract_version="fundamental.v1",
        snapshot_id=fixture.snapshot.snapshot_id,
        data_release_manifest_digest=manifest.manifest_digest,
        model_id="fcff_dcf",
    )
    prepared = app.prepare_valuation(request)
    assert (
        prepared.input.assumptions.wacc.equity_risk_premium
        == policy.market_inputs.equity_risk_premium
    )
    assert app.prepare_valuation(request) == prepared
    payload = policy.model_dump(exclude={"policy_digest"})
    payload["market_inputs"]["equity_risk_premium"] += Decimal("0.01")
    evidence = next(
        x
        for x in payload["market_inputs"]["evidence"]
        if x["role"] == "equity_risk_premium"
    )
    evidence["value"] = payload["market_inputs"]["equity_risk_premium"]
    changed = PolicyRecordV1(**payload, policy_digest=sha256_digest(payload))
    app = replace(
        app, policy_registry=PolicyRegistry(initial_model_specs(), (changed,))
    )
    with pytest.raises(ServiceError) as error:
        app.prepare_valuation(request)
    assert error.value.code == "MARKET_REFERENCE_POLICY_SOURCE_MISMATCH"


@pytest.mark.parametrize("change", ["none", "missing_registry", "changed_erp"])
def test_release_canary_checks_the_same_policy_authority_and_source_value(
    tmp_path, change
):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from fundamental_service.data_releases import sign_data_release_verification
    from fundamental_service.release_runner import DataReleaseCanaryRunner
    from fundamental_service.quote_sources import default_quote_providers

    fixture = _fixture(tmp_path)
    candidate, base_canary = _reviewed_candidate(fixture)
    fixture.manifest = candidate.manifest
    manifest, artifacts, admission, plan, ref, policy = _bound(fixture)
    for name, content in artifacts.data.items():
        fixture.artifacts.put_bytes_with_receipt(name, content)
    payload = candidate.verification.model_dump(
        exclude={"signature", "verification_digest"}
    )
    payload["manifest_digest"] = manifest.manifest_digest
    verification = sign_data_release_verification(
        payload,
        Ed25519PrivateKey.from_private_bytes(b"verifier-key".ljust(32, b"0")),
    )
    if change == "changed_erp":
        payload = policy.model_dump(exclude={"policy_digest"})
        market = payload["market_inputs"]
        market["equity_risk_premium"] += Decimal("0.01")
        next(x for x in market["evidence"] if x["role"] == "equity_risk_premium")[
            "value"
        ] = market["equity_risk_premium"]
        policy = PolicyRecordV1(**payload, policy_digest=sha256_digest(payload))
    runner = DataReleaseCanaryRunner(
        snapshot_repository=fixture.snapshots,
        fact_repository=fixture.facts,
        mapping_reader=fixture.metadata,
        artifact_reader=base_canary._artifacts,
        trust_roots=base_canary._trust_roots,
        reference_providers=(DamodaranReferenceProvider(),),
        source_use_policy=_reference_policy(),
        policy_registry=None
        if change == "missing_registry"
        else PolicyRegistry(initial_model_specs(), (policy,)),
        quote_providers=default_quote_providers(),
    )
    if change == "none":
        first = runner.validate(manifest, verification)
        assert runner.validate(manifest, verification) == first
    else:
        with pytest.raises(DataReleaseError) as error:
            runner.validate(manifest, verification)
        assert error.value.code == (
            "MARKET_REFERENCE_POLICY_UNAVAILABLE"
            if change == "missing_registry"
            else "MARKET_REFERENCE_POLICY_SOURCE_MISMATCH"
        )
