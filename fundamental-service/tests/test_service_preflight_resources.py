"""Exercise acceptance resource checks with the installed service dependencies."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).parents[2] / "scripts"))

import acceptance_service_preflight as preflight


@pytest.mark.parametrize("resource", ["taxonomy", "edgar", "xule", "dqc", "catalog"])
@pytest.mark.parametrize("damage", ["missing", "corrupt"])
def test_fresh_runtime_check_rejects_changed_sec_resources(tmp_path, resource, damage):
    from fundamental_service.arelle_parser import _directory_hash

    assets = {}
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("FUNDAMENTAL_")
    }
    root = Path(__file__).parents[2]
    env.update(
        PYTHONPATH=os.pathsep.join(
            str(root / path)
            for path in ("fundamental-service/src", "finance-agent-core")
        ),
        PYTHONDONTWRITEBYTECODE="1",
        FUNDAMENTAL_SERVICE_TOKEN="preflight-test-token",
        FUNDAMENTAL_SERVICE_DATA_ROOT=str(tmp_path / "data"),
        FUNDAMENTAL_SERVICE_DATABASE_URL="postgresql+asyncpg://fixture:fixture@127.0.0.1:9/fixture",
        FUNDAMENTAL_SEC_USER_AGENT="Preflight fixture fixture@example.test",
        FUNDAMENTAL_SEC_TAXONOMY_MANIFEST_ID="fixture-taxonomy",
        FUNDAMENTAL_SEC_TAXONOMY_VERSION="us-gaap-2025",
        FUNDAMENTAL_SEC_SUPPORTED_FILING_YEARS="2026",
        FUNDAMENTAL_SEC_SUPPORTED_FILING_FORMS="10-K",
    )
    for name, prefix in (
        ("taxonomy", "FUNDAMENTAL_SEC_TAXONOMY_CACHE"),
        ("edgar", "FUNDAMENTAL_SEC_EDGAR_PLUGIN"),
        ("xule", "FUNDAMENTAL_SEC_XULE_PLUGIN"),
    ):
        directory = tmp_path / name
        directory.mkdir()
        assets[name] = directory / "fixture.txt"
        assets[name].write_bytes(name.encode())
        env[prefix + "_DIR"] = str(directory)
        env[prefix + "_SHA256"] = _directory_hash(directory)
    for name in ("dqc", "catalog"):
        assets[name] = tmp_path / (name + ".zip")
        assets[name].write_bytes(name.encode())
    env["FUNDAMENTAL_SEC_DQC_RULESET_PATH"] = str(assets["dqc"])
    env["FUNDAMENTAL_SEC_DQC_RULESET_SHA256"] = hashlib.sha256(b"dqc").hexdigest()
    catalog = tmp_path / "catalog.json"
    catalog.write_text(
        json.dumps(
            {
                "bindings": [
                    {
                        "taxonomy_namespace": "http://fasb.org/us-gaap/2025",
                        "path": str(assets["catalog"]),
                        "sha256": hashlib.sha256(b"catalog").hexdigest(),
                    }
                ]
            }
        )
    )
    env["FUNDAMENTAL_SEC_DQC_RULESET_CATALOG_PATH"] = str(catalog)
    command = [sys.executable, "-c", preflight.CONTAINER_SEC_RESOURCES]
    before = subprocess.run(command, env=env, capture_output=True, timeout=30)
    assert before.returncode == 0, before.stderr.decode()
    pins = json.loads(before.stdout)
    assert pins["edgar_plugin_sha256"] == env["FUNDAMENTAL_SEC_EDGAR_PLUGIN_SHA256"]
    if damage == "missing":
        assets[resource].unlink()
    else:
        assets[resource].write_bytes(b"changed after startup")
    after = subprocess.run(command, env=env, capture_output=True, timeout=30)
    assert after.returncode != 0
    assert not after.stdout
    assert b"pinned" in after.stderr
