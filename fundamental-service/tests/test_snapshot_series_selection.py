"""A selected SEC ticker resolves only to its active released canonical class."""

from datetime import timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from fundamental_service.app import create_app
from fundamental_service.contracts import SourceSnapshotV1
from fundamental_service.data_releases import (
    ActiveDataReleaseV1,
    ActiveDataReleaseWithManifestV1,
)
from fundamental_service.serialization import canonical_bytes, sha256_digest
from fundamental_service.snapshots import FilesystemSnapshotRepository
from fundamental_service.testsupport import auth_headers, make_internal_envelope
from test_api import _canonical_fact, _release_manifest_for
from test_valuation_preparation import _snapshot
from test_valuation_release_inputs import _manifest_with


def _case(tmp_path):
    snapshot = _snapshot(
        "series",
        parser_version="arelle-release==2.47.4",
        taxonomy_manifest_id="taxonomy-v1",
    )
    snapshot = _snapshot_with(
        snapshot,
        share_class="Common stock, $0.00000625 par value per share",
        issuer_name="Canonical Filing Name",
    )
    facts = (_canonical_fact("fact-revenue", "revenue"),)
    facts = tuple(
        fact.model_copy(
            update={
                "issuer_id": snapshot.identity.issuer_id,
                "security_id": snapshot.identity.security_id,
            }
        )
        for fact in facts
    )
    manifest = _release_manifest_for(snapshot, facts)
    snapshots = FilesystemSnapshotRepository(tmp_path / "snapshots")
    snapshots.publish(snapshot)
    state = SimpleNamespace(manifest=manifest)

    def active(profile):
        if state.manifest is None or profile != state.manifest.profile_id:
            return None
        return ActiveDataReleaseWithManifestV1(
            active=ActiveDataReleaseV1(
                profile_id=state.manifest.profile_id,
                manifest_digest=state.manifest.manifest_digest,
                revision=1,
                activated_at=snapshot.valuation_timestamp,
            ),
            manifest=state.manifest,
        )

    metadata = SimpleNamespace(get_active_data_release_with_manifest=active)
    fact_repository = SimpleNamespace(
        get={fact.fact_id: fact for fact in facts}.__getitem__
    )
    app = create_app(
        snapshot_repository=snapshots,
        fact_repository=fact_repository,
        metadata_store=metadata,
    )
    client = TestClient(app)
    identity = snapshot.identity.model_copy(
        update={
            "issuer_name": "Resolver Display Name",
            "share_class": snapshot.identity.security_id,
        }
    )
    request = {
        "contract_version": "fundamental.v1",
        "identity": identity.model_dump(mode="json"),
        "identity_selection_policy": "sec-ticker-series-v1",
        "release_profile_id": manifest.profile_id,
        "valuation_timestamp": snapshot.valuation_timestamp.isoformat(),
        "source_selection_policy": "pit-v1",
        "coverage_profile": "automatic-fcff-v1",
        "required_fields": ["revenue"],
    }
    return SimpleNamespace(
        snapshot=snapshot,
        snapshots=snapshots,
        facts=facts,
        state=state,
        request=request,
        app=app,
        client=client,
    )


def _snapshot_with(snapshot, **identity_changes):
    payload = snapshot.model_dump(exclude={"manifest_digest", "snapshot_id"})
    payload["identity"] = snapshot.identity.model_copy(update=identity_changes)
    return SourceSnapshotV1(
        snapshot_id="snapshot-" + sha256_digest(payload)[:20],
        manifest_digest=sha256_digest(payload),
        **payload,
    )


def _resolve(case, request=None):
    return case.client.post(
        "/v1/data/snapshots/resolve",
        headers=auth_headers(),
        json=make_internal_envelope(request or case.request),
    )


def test_series_returns_immutable_canonical_identity_while_exact_mode_stays_exact(
    tmp_path,
):
    case = _case(tmp_path)
    before = canonical_bytes(case.snapshot)
    first = _resolve(case)
    assert first.status_code == 200, first.text
    result = first.json()["result"]
    assert result["identity"] == case.snapshot.identity.model_dump(mode="json")
    assert result["identity_selection_policy"] == "sec-ticker-series-v1"
    assert result["snapshot_id"] == case.snapshot.snapshot_id
    assert result["data_release_manifest_digest"] == case.state.manifest.manifest_digest
    assert result["historical_facts"] == [fact.fact_id for fact in case.facts]
    assert _resolve(case).json()["result"] == result
    exact = {**case.request, "identity_selection_policy": "exact-identity-v1"}
    assert _resolve(case, exact).status_code == 404
    exact["identity"] = case.snapshot.identity.model_dump(mode="json")
    selected = _resolve(case, exact)
    assert selected.status_code == 200, selected.text
    assert selected.json()["result"]["identity_selection_policy"] == "exact-identity-v1"
    assert (
        "fundamental_service_cache_miss_total 3"
        in case.app.state.metrics.render_prometheus()
    )
    assert canonical_bytes(case.snapshots.get(case.snapshot.snapshot_id)) == before


@pytest.mark.parametrize(
    "field,value",
    (
        ("issuer_id", "OTHER"),
        ("security_id", "OTHER"),
        ("currency", "EUR"),
        ("domicile", "GB"),
        ("reporting_basis", "ifrs"),
        ("share_class", "Class B"),
    ),
)
def test_series_refuses_wrong_semantic_identity_and_explicit_class(
    tmp_path, field, value
):
    case = _case(tmp_path)
    request = {**case.request, "identity": {**case.request["identity"], field: value}}
    if field == "security_id":
        request["identity"]["share_class"] = value
    response = _resolve(case, request)
    assert response.status_code == (422 if field == "share_class" else 404), (
        response.text
    )
    assert "result" not in response.json()


def test_series_requires_active_release_and_point_in_time_candidate(tmp_path):
    case = _case(tmp_path)
    early = {
        **case.request,
        "valuation_timestamp": (
            case.snapshot.valuation_timestamp - timedelta(seconds=1)
        ).isoformat(),
    }
    assert _resolve(case, early).status_code == 404
    no_profile = {
        key: value for key, value in case.request.items() if key != "release_profile_id"
    }
    response = _resolve(case, no_profile)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "SERIES_RELEASE_REQUIRED"
    case.state.manifest = None
    response = _resolve(case)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "DATA_RELEASE_NOT_ACTIVE"


def test_series_never_selects_unreleased_snapshot_and_refuses_multiple_classes(
    tmp_path,
):
    case = _case(tmp_path)
    other = _snapshot_with(case.snapshot, share_class="Other canonical Class B")
    case.snapshots.publish(other)
    assert _resolve(case).json()["result"]["snapshot_id"] == case.snapshot.snapshot_id
    second_ref = _release_manifest_for(other, case.facts).snapshot_refs[0]
    case.state.manifest = _manifest_with(
        case.state.manifest,
        snapshot_refs=(*case.state.manifest.snapshot_refs, second_ref),
    )
    response = _resolve(case)
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "SERIES_IDENTITY_AMBIGUOUS"


@pytest.mark.parametrize("fault", ("snapshot", "fact"))
def test_series_preserves_release_hash_and_fact_binding_gates(tmp_path, fault):
    case = _case(tmp_path)
    reference = case.state.manifest.snapshot_refs[0]
    if fault == "snapshot":
        reference = reference.model_copy(update={"manifest_digest": "f" * 64})
    else:
        reference = reference.model_copy(
            update={
                "facts": (
                    reference.facts[0].model_copy(update={"fact_digest": "f" * 64}),
                )
            }
        )
    if fault == "fact":
        reference = reference.model_copy(
            update={"fact_set_digest": sha256_digest(reference.facts)}
        )
    case.state.manifest = _manifest_with(
        case.state.manifest, snapshot_refs=(reference,)
    )
    response = _resolve(case)
    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == (
        "DATA_RELEASE_SNAPSHOT_MISMATCH"
        if fault == "snapshot"
        else "DATA_RELEASE_FACT_MISMATCH"
    )
