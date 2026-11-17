"""Interrupted benchmark attempts retain their failure and missing metrics."""

import importlib.util
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace


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
