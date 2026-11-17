"""Interrupted benchmark attempts retain their failure and missing metrics."""

import importlib.util
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.mark.parametrize(
    "failure",
    (
        None,
        "artifact hash",
        "exact input",
        "calculation digest",
        "numerical provenance",
        "source provenance",
    ),
)
def test_optimized_api_verifier_preserves_every_integrity_check(tmp_path, failure):
    path = Path(__file__).parents[1] / "benchmarks" / "fundamental_flow.py"
    spec = importlib.util.spec_from_file_location("full_flow_benchmark", path)
    benchmark = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(benchmark)

    def encode(value):
        return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()

    def digest(value):
        return hashlib.sha256(encode(value)).hexdigest()

    base = {
        "per_share_value": "123.45",
        "artifact_references": ["source"],
        "correlation_id": "stored",
    }
    uncertainty = {"report": {"base": base}}
    if failure == "numerical provenance":
        base["per_share_value"] = "999"
    if failure == "source provenance":
        base["artifact_references"] = ["unbound source"]
    uncertainty_ref = {
        "artifact_id": "uncertainty",
        "content_hash": digest(uncertainty),
        "artifact_type": "uncertainty_evidence",
    }
    calculation = {
        "base": {
            "per_share_value": "123.45",
            "artifact_references": ["source"],
            "correlation_id": "current",
        },
        "artifact_references": [uncertainty_ref],
    }
    execution = {"input_digest": "a" * 64, "result_digest": digest(calculation)}
    if failure == "exact input":
        execution["input_digest"] = "b" * 64
    if failure == "calculation digest":
        execution["result_digest"] = "0" * 64
    reference = {"artifact_id": "execution", "content_hash": digest(execution)}
    if failure == "artifact hash":
        reference["content_hash"] = "0" * 64
    flow = {
        "automatic_execution": {
            "execution_publication": {"artifact": reference},
            "decision": {"input_digest": "a" * 64},
            "calculation": calculation,
        }
    }
    source = tmp_path / "flow.json"
    source.write_bytes(encode(flow))
    responses = [encode(execution).decode(), encode(uncertainty).decode()]
    bootstrap = f"""
import hashlib,json,sys,types
from types import SimpleNamespace
responses=iter({responses!r})
caller=types.ModuleType('fundamental_service.automatic_caller')
caller.DeploymentAutomaticCaller=type('Caller',(),{{'from_env':classmethod(lambda cls:cls()),'_request':lambda *a,**kw:next(responses).encode()}})
model=types.ModuleType('fundamental_service.automatic_valuation')
model.AutomaticValuationResponseV1=type('Response',(),{{'model_validate_json':staticmethod(lambda raw:SimpleNamespace(calculation=json.loads(raw)['calculation']))}})
serialization=types.ModuleType('fundamental_service.serialization')
serialization.sha256_digest=lambda value:hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()
sys.modules.update({{'fundamental_service':types.ModuleType('fundamental_service'),caller.__name__:caller,model.__name__:model,serialization.__name__:serialization}})
exec({benchmark.API_RETRIEVAL!r})
"""
    result = subprocess.run(
        [sys.executable, "-O", "-c", bootstrap, str(source), "caller", "org"],
        capture_output=True,
        text=True,
    )
    if failure is None:
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout)["provenance_equal"] is True
    else:
        assert result.returncode != 0
        assert f"retrieved {failure} differs" in result.stderr
        assert not result.stdout


def test_container_exit_does_not_erase_failed_attempt(tmp_path, monkeypatch):
    path = Path(__file__).parents[1] / "benchmarks" / "fundamental_flow.py"
    spec = importlib.util.spec_from_file_location("full_flow_benchmark", path)
    benchmark = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(benchmark)
    reference = tmp_path / "reference.json"
    reference.write_text("{}")
    manifest = {
        "workload": "A",
        "side": "candidate",
        "delivery_sha": "a" * 40,
        "image": "sha256:image",
        "compose_command": ["docker", "compose"],
        "container": "isolated-service",
        "output_directory": str(tmp_path),
        "reference_flow": str(reference),
        "resources": {"cpus": 1, "memory_bytes": 3221225472, "workers": 1},
        "seed_manifest": {"digest": "b" * 64},
        "issuer_arguments": ["fundamental-prepare-issuer"],
        "driver_timeout_seconds": 930,
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest))
    container = {
        "Image": manifest["image"],
        "HostConfig": {"NanoCpus": 1000000000, "Memory": 3221225472},
        "Config": {"Cmd": ["uvicorn"], "Env": []},
    }
    monkeypatch.setattr(
        benchmark.subprocess,
        "check_output",
        lambda *a, **kw: json.dumps([container]).encode(),
    )
    monkeypatch.setattr(
        benchmark.subprocess, "run", lambda *a, **kw: SimpleNamespace(returncode=137)
    )
    calls = []

    def stats(_):
        calls.append(True)
        if len(calls) > 1:
            raise subprocess.CalledProcessError(1, ["docker", "exec"])
        return {"cpu_us": 100, "memory_current": 1024, "memory_peak": 2048}

    monkeypatch.setattr(benchmark, "statistics", stats)
    assert benchmark.run(manifest_path, "interrupted") is False
    receipt = json.loads((tmp_path / "interrupted-receipt.json").read_bytes())
    assert receipt["success"] is False and receipt["exit_code"] == 137
    assert "issuer command failed" in receipt["failure"]
    assert receipt["cpu_seconds"] is None and receipt["cgroup_peak_bytes"] is None
    assert receipt["sampling_errors"] == ["final:CalledProcessError"]
    assert receipt["max_sampled_cgroup_memory_bytes"] == 1024
