from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from fundamental_service.app import create_app
from fundamental_service.data_releases import (
    ActiveDataReleaseV1,
    ActiveDataReleaseWithManifestV1,
    AutomaticValuationModelV1,
)
from fundamental_service.testsupport import auth_headers, make_internal_envelope
from fundamental_service.valuation_release_inputs import automatic_release_model
from test_conditional_capital_release import _conditional_fixture
from test_conditional_reinvestment_composer import _fixture as _joint_fixture
from test_conditional_reinvestment_release import _fixture as _forward_fixture
from test_valuation_release_inputs import _manifest_with, _valuation_fixture


def _read_active(fixture, manifest, *, advertised=None):
    active = ActiveDataReleaseWithManifestV1(
        active=ActiveDataReleaseV1(
            profile_id=manifest.profile_id,
            manifest_digest=manifest.manifest_digest,
            revision=1,
            activated_at=manifest.created_at,
        ),
        manifest=manifest,
        automatic_model=advertised,
    )
    metadata = SimpleNamespace(
        get_active_data_release_with_manifest=lambda profile_id: (
            active if profile_id == manifest.profile_id else None
        )
    )
    client = TestClient(
        create_app(metadata_store=metadata, config=fixture.application.config)
    )
    return client.request(
        "GET",
        f"/v1/data/releases/{manifest.profile_id}",
        headers=auth_headers(),
        json=make_internal_envelope({}),
    )


@pytest.mark.parametrize(
    "build", (_conditional_fixture, _joint_fixture, _forward_fixture)
)
def test_conditional_release_exposes_one_exact_recipe_model(tmp_path, build):
    fixture = build(tmp_path)
    binding = automatic_release_model(fixture.manifest)
    assert binding == AutomaticValuationModelV1(
        model_id="fcff_dcf", model_version="fcff_dcf-v2"
    )


def test_active_conditional_metadata_overwrites_stale_advertised_binding(tmp_path):
    fixture = _joint_fixture(tmp_path)
    response = _read_active(
        fixture,
        fixture.manifest,
        advertised=AutomaticValuationModelV1(
            model_id="transition_fcff_dcf", model_version="transition_fcff_dcf-v2"
        ),
    )
    assert response.status_code == 200, response.text
    result = response.json()["result"]
    assert result["automatic_model"] == {
        "model_id": "fcff_dcf",
        "model_version": "fcff_dcf-v2",
    }
    assert result["manifest"] == fixture.manifest.model_dump(mode="json")
    assert result["active"]["manifest_digest"] == fixture.manifest.manifest_digest


def test_ordinary_release_omits_automatic_model_even_if_advertised(tmp_path):
    fixture = _valuation_fixture(tmp_path)
    assert automatic_release_model(fixture.manifest) is None
    response = _read_active(
        fixture,
        fixture.manifest,
        advertised=AutomaticValuationModelV1(
            model_id="fcff_dcf", model_version="fcff_dcf-v2"
        ),
    )
    assert response.status_code == 200, response.text
    assert "automatic_model" not in response.json()["result"]


@pytest.mark.parametrize(
    "fault,code",
    (
        ("model", "DATA_RELEASE_AUTOMATIC_MODEL_MISMATCH"),
        ("mapping", "DATA_RELEASE_AUTOMATIC_MODEL_MISMATCH"),
        ("executable_version", "DATA_RELEASE_AUTOMATIC_MODEL_MISMATCH"),
        ("snapshot", "DATA_RELEASE_REINVESTMENT_UNBOUND"),
        ("fact", "DATA_RELEASE_CONDITIONAL_CAPITAL_UNBOUND"),
        ("fields", "DATA_RELEASE_VALUATION_INPUT_POLICY_MISMATCH"),
    ),
)
def test_incoherent_or_unbound_conditional_release_refuses_metadata(
    tmp_path, monkeypatch, fault, code
):
    fixture = _joint_fixture(tmp_path)
    manifest = fixture.manifest
    capital = manifest.conditional_capital_policies[0]
    forward = manifest.conditional_reinvestment_policies[0]
    if fault == "model":
        capital = capital.model_copy(
            update={
                "model_id": "transition_fcff_dcf",
                "model_version": "transition_fcff_dcf-v2",
            }
        )
    elif fault == "mapping":
        capital = capital.model_copy(update={"mapping_version": "other-mapping"})
    elif fault == "executable_version":
        monkeypatch.setattr(
            "fundamental_service.valuation_release_inputs.executable_model_specs",
            lambda: (),
        )
    elif fault == "snapshot":
        forward = forward.model_copy(update={"snapshot_manifest_digest": "f" * 64})
    elif fault == "fact":
        role, observation = next(iter(capital.observations.items()))
        capital = capital.model_copy(
            update={
                "observations": capital.observations
                | {role: observation.model_copy(update={"fact_digest": "f" * 64})}
            }
        )
    changes = {
        "conditional_capital_policies": (capital,),
        "conditional_reinvestment_policies": (forward,),
    }
    if fault == "fields":
        changes["required_fields"] = manifest.required_fields[:-1]
    manifest = _manifest_with(manifest, **changes)
    response = _read_active(fixture, manifest)
    assert response.status_code == 503, response.text
    assert response.json()["error"]["code"] == code
    assert "automatic_model" not in response.json()


def _dated_joint_fixture(tmp_path):
    from dataclasses import replace
    from fundamental_service.conditional_capital_contracts import (
        ConditionalCapitalPolicyV1,
    )
    from fundamental_service.conditional_reinvestment import (
        bind_conditional_reinvestment_recipe,
    )
    from fundamental_service.conditional_reinvestment_contracts import (
        ConditionalReinvestmentRecipeV1,
    )
    from fundamental_service.conditional_reinvestment_release import (
        REINVESTMENT_ASSUMPTION_ROLE,
        reinvestment_assumption_document,
    )
    from fundamental_service.data_releases import ArtifactRefV1
    from fundamental_service.policies import (
        PolicyRecordV1,
        PolicyRegistry,
        executable_model_specs,
    )
    from fundamental_service.serialization import sha256_digest

    fixture = _joint_fixture(tmp_path)
    fixture.capital_policy = ConditionalCapitalPolicyV1.model_validate(
        fixture.capital_policy.model_dump() | {"model_version": "fcff_dcf-v3"}
    )
    recipe = ConditionalReinvestmentRecipeV1.model_validate(
        fixture.forward_policy.recipe.model_dump() | {"model_version": "fcff_dcf-v3"}
    )
    record = fixture.artifacts.put_bytes_with_receipt(
        "dated-forward-assumptions",
        reinvestment_assumption_document(recipe),
        media_type="application/json",
    ).artifact
    recipe = ConditionalReinvestmentRecipeV1.model_validate(
        recipe.model_dump()
        | {
            "assumption_document_uri": f"artifact://{record.artifact_id}",
            "assumption_document_digest": record.content_hash,
        }
    )
    fixture.forward_policy = bind_conditional_reinvestment_recipe(
        recipe, fixture.stored, snapshot=fixture.snapshot
    ).policy
    fixture.manifest = _manifest_with(
        fixture.manifest,
        conditional_capital_policies=(fixture.capital_policy,),
        conditional_reinvestment_policies=(fixture.forward_policy,),
        artifact_refs=(
            *[
                ref
                for ref in fixture.manifest.artifact_refs
                if ref.role != REINVESTMENT_ASSUMPTION_ROLE
            ],
            ArtifactRefV1(
                artifact_id=record.artifact_id,
                content_hash=record.content_hash,
                media_type=record.media_type,
                role=REINVESTMENT_ASSUMPTION_ROLE,
            ),
        ),
    )
    policies = []
    for policy in fixture.application.policy_registry.policies():
        payload = policy.model_dump(exclude={"policy_digest"}) | {
            "model_version": f"{policy.model_id}-v3",
            "policy_id": policy.policy_id + "-dated",
            "policy_version": policy.policy_version + "-dated",
        }
        policies.append(PolicyRecordV1(**payload, policy_digest=sha256_digest(payload)))
    fixture.application = replace(
        fixture.application,
        policy_registry=PolicyRegistry(executable_model_specs(), policies),
    )
    return fixture


@pytest.mark.parametrize("dated", [False, True])
def test_signed_release_selects_its_exact_model_before_public_preparation(
    tmp_path, dated
):
    from fundamental_service.contracts import ValuationInputV1
    from fundamental_service.serialization import canonical_bytes
    from test_preparation_runner import _reviewed_candidate
    from test_valuation_release_inputs import _client, _prepare

    fixture = _dated_joint_fixture(tmp_path) if dated else _joint_fixture(tmp_path)
    candidate, canary = _reviewed_candidate(fixture)
    canary.validate(candidate.manifest, candidate.verification)
    response = _prepare(_client(fixture), fixture, candidate)
    assert response.status_code == 200, response.text
    result = response.json()["result"]
    assert result["status"] == "prepared", result["issue_codes"]
    expected_version = "fcff_dcf-v3" if dated else "fcff_dcf-v2"
    assert (
        result["model_version"] == result["input"]["model_version"] == expected_version
    )
    request = ValuationInputV1.model_validate_json(canonical_bytes(result["input"]))
    timeline = request.assumptions.forecast.timeline
    assert (timeline is not None) == dated
    if dated:
        assert timeline.source_period_end.isoformat() == "2025-12-31"
        assert [period.period_end.year for period in timeline.periods] == [
            2026,
            2027,
            2028,
            2029,
            2030,
        ]
