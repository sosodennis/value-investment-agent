"""Automatic model metadata follows coherent released conditional recipes."""

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
            "fundamental_service.valuation_release_inputs.initial_model_specs",
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
