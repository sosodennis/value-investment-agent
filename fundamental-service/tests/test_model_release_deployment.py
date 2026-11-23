import json
from datetime import timedelta
from pathlib import Path

import pytest

from fundamental_service.governance import ModelInventory, ModelReleaseEvidenceV1
from fundamental_service.model_release_deployment import load_model_release_deployment
from fundamental_service.policies import dated_model_specs
from model_release_fixtures import APPROVED, EXPIRES, signed_raw_release


def write_bundle(tmp_path: Path, *, model_index: int = 0):
    model = dated_model_specs()[model_index]
    inventory, evidence, payloads = signed_raw_release(model)
    for artifact_id, payload in payloads.items():
        (tmp_path / artifact_id).write_bytes(payload)
    entry = {
        "evidence": evidence.model_dump(mode="json"),
        "artifact_files": {key: key for key in payloads},
    }
    path = tmp_path / "deployment.json"
    path.write_text(
        json.dumps(
            {"protocol": "fundamental-model-release-deployment-v1", "releases": [entry]}
        )
    )
    return path, inventory, model, evidence, payloads


@pytest.mark.parametrize("index", [0, 1])
def test_only_signed_current_engineering_release_can_activate_without_calibration(
    tmp_path, index
):
    path, inventory, model, evidence, payloads = write_bundle(
        tmp_path, model_index=index
    )
    (active,) = load_model_release_deployment(path, inventory, at=APPROVED)
    assert active.lifecycle == "active"
    assert active.model_version.endswith("-v3")
    assert "calibration_training_end" not in evidence.model_dump()
    assert inventory.advertised(at=APPROVED) == (active,)
    assert inventory.advertised(at=EXPIRES) == ()
    with pytest.raises(ValueError, match="trusted verifier"):
        load_model_release_deployment(path, ModelInventory((model,)), at=APPROVED)
    with pytest.raises(ValueError, match="not current"):
        inventory.promote(model, evidence, artifact_bytes=payloads, at=EXPIRES)
    requiring_calibration = model.model_copy(
        update={"calibration_required_for_promotion": True}
    )
    with pytest.raises(ValueError, match="out-of-sample calibration"):
        ModelInventory((requiring_calibration,)).promote(
            requiring_calibration, evidence, artifact_bytes=payloads, at=APPROVED
        )


@pytest.mark.parametrize(
    "mutation",
    [
        "outside",
        "absolute",
        "symlink",
        "missing",
        "tampered",
        "signature",
        "unknown-model",
        "duplicate",
    ],
)
def test_deployment_rejects_untrusted_or_incomplete_bundle(tmp_path, mutation):
    path, inventory, model, evidence, payloads = write_bundle(tmp_path)
    document = json.loads(path.read_text())
    entry = document["releases"][0]
    artifact_id = next(iter(payloads))
    if mutation == "outside":
        entry["artifact_files"][artifact_id] = "../outside"
    elif mutation == "absolute":
        entry["artifact_files"][artifact_id] = str(tmp_path / artifact_id)
    elif mutation == "symlink":
        (tmp_path / "link").symlink_to(tmp_path.parent)
        entry["artifact_files"][artifact_id] = "link/outside"
    elif mutation == "missing":
        del entry["artifact_files"][artifact_id]
    elif mutation == "tampered":
        (tmp_path / artifact_id).write_bytes(b"tampered")
    elif mutation == "signature":
        (tmp_path / "verification_attestation").write_bytes(b"tampered")
    elif mutation == "unknown-model":
        entry["evidence"]["model_version"] = "fcff_dcf-v999"
    elif mutation == "duplicate":
        document["releases"].append(entry)
    path.write_text(json.dumps(document))
    with pytest.raises(ValueError):
        load_model_release_deployment(path, inventory, at=APPROVED)


def test_calibration_window_cannot_be_partially_supplied(tmp_path):
    _, _, _, evidence, _ = write_bundle(tmp_path)
    payload = evidence.model_dump()
    payload["calibration_training_end"] = APPROVED - timedelta(days=100)
    with pytest.raises(ValueError, match="complete or absent"):
        ModelReleaseEvidenceV1.model_validate(payload)
