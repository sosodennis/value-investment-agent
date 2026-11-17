#!/usr/bin/env python3
"""Measure the complete issuer flow through authenticated result retrieval.

The manifest and all outputs live outside Git. A failed calculation, mismatched
scenario or failed API read is retained as a failure, never a fast sample.
This driver neither supplies financial inputs nor authorizes calculations.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

API_RETRIEVAL = """
import hashlib,json,sys,urllib.parse
from datetime import UTC,datetime,timedelta
from pathlib import Path
from fundamental_service.automatic_caller import DeploymentAutomaticCaller
from fundamental_service.automatic_valuation import AutomaticValuationResponseV1
from fundamental_service.serialization import sha256_digest
v=json.loads(Path(sys.argv[1]).read_bytes());e=v['automatic_execution']
caller=DeploymentAutomaticCaller.from_env();rows=[]
def read(ref):
 raw=caller._request('/v1/artifacts/'+urllib.parse.quote(ref['artifact_id'],safe='')+'/content',{},method='GET',caller_id=sys.argv[2],organization_id=sys.argv[3],deadline_at=datetime.now(UTC)+timedelta(seconds=5))
 if hashlib.sha256(raw).hexdigest()!=ref['content_hash']:
  raise ValueError('retrieved artifact hash differs')
 rows.append({'artifact_id':ref['artifact_id'],'content_hash':ref['content_hash']})
 return json.loads(raw)
execution=read(e['execution_publication']['artifact'])
if execution['input_digest']!=e['decision']['input_digest']:
 raise ValueError('retrieved exact input differs')
if execution['result_digest']!=sha256_digest(AutomaticValuationResponseV1.model_validate_json(json.dumps(e)).calculation):
 raise ValueError('retrieved calculation digest differs')
for ref in e['calculation']['artifact_references']:
 artifact=read(ref)
 if ref['artifact_type']=='uncertainty_evidence':
  base=artifact['report']['base'];result=e['calculation']['base']
  if {k:v for k,v in base.items() if k not in {'artifact_references','correlation_id'}}!={k:v for k,v in result.items() if k not in {'artifact_references','correlation_id'}}:
   raise ValueError('retrieved numerical provenance differs')
  if not all(item in result['artifact_references'] for item in base['artifact_references']):
   raise ValueError('retrieved source provenance differs')
print(json.dumps({'authenticated':True,'input_digest':execution['input_digest'],'result_digest':execution['result_digest'],'provenance_equal':True,'artifacts':rows}))
"""


def numerical_projection(calculation: dict[str, Any]) -> dict[str, Any]:
    """Compare reported numbers, statuses and assumptions across delivery IDs."""

    def one(result: dict[str, Any]) -> dict[str, Any]:
        return {
            key: result[key]
            for key in (
                "intrinsic_value",
                "per_share_value",
                "calculation_status",
                "quality_status",
            )
        } | {
            "assumptions": {
                key: value
                for key, value in result["assumptions"].items()
                if key != "trace"
            },
            "nodes": [
                {
                    key: value
                    for key, value in node.items()
                    if key not in {"trace", "inputs"}
                }
                for node in result["nodes"]
            ],
        }

    return {
        "base": one(calculation["base"]),
        "scenarios": [one(value) for value in calculation["scenario_results"]],
        "status": calculation["status"],
    }


def stable_signature(flow: dict[str, Any]) -> dict[str, Any]:
    execution = flow["automatic_execution"]
    return {
        "lineage": {
            name: {key: value for key, value in record.items() if key != "wrote"}
            for name, record in flow["lineage"].items()
        },
        "preparation": flow["preparation"]["artifact"],
        "calculation": execution["calculation"],
        "publications": {
            name: execution[name + "_publication"]["artifact"]
            for name in ("policy", "preparation", "decision", "execution")
        },
    }


def require_reuse(flow: dict[str, Any]) -> None:
    dispositions = [record["wrote"] for record in flow["lineage"].values()]
    dispositions.extend(
        flow["automatic_execution"][name + "_publication"]["wrote"]
        for name in ("policy", "preparation", "decision", "execution")
    )
    if any(value is not False for value in dispositions):
        raise ValueError("replay wrote new lineage or calculation artifacts")


def statistics(container: str) -> dict[str, int]:
    lines = subprocess.check_output(
        [
            "docker",
            "exec",
            container,
            "sh",
            "-c",
            "cat /sys/fs/cgroup/cpu.stat /sys/fs/cgroup/memory.current /sys/fs/cgroup/memory.peak",
        ],
        text=True,
        timeout=10,
    ).splitlines()
    return {
        "cpu_us": int(
            next(line.split()[1] for line in lines if line.startswith("usage_usec "))
        ),
        "memory_current": int(lines[-2]),
        "memory_peak": int(lines[-1]),
    }


def run(manifest_path: Path, label: str) -> bool:
    if not label.replace("-", "").replace("_", "").isalnum():
        raise ValueError(
            "label must contain only letters, digits, dashes or underscores"
        )
    raw = manifest_path.read_bytes()
    manifest = json.loads(raw)
    directory = Path(manifest["output_directory"])
    directory.mkdir(parents=True, exist_ok=True)
    stdout = directory / (label + ".stdout")
    stderr = directory / (label + ".stderr")
    receipt_path = directory / (label + "-receipt.json")
    if any(path.exists() for path in (stdout, stderr, receipt_path)):
        raise FileExistsError("benchmark attempts must never overwrite evidence")
    compose = manifest["compose_command"]
    container = manifest["container"]
    inspected = json.loads(subprocess.check_output(["docker", "inspect", container]))[0]
    selected = subprocess.check_output(
        [*compose, "ps", "-q", "fundamental-service"], text=True, timeout=30
    ).splitlines()
    if selected != [inspected["Id"]]:
        raise ValueError("Compose service differs from manifest container")
    container = inspected["Id"]
    execute = ["docker", "exec", "-i", container]
    actual_image = inspected["Image"]
    if actual_image != manifest["image"]:
        raise ValueError("running image differs from benchmark manifest")
    resources = manifest["resources"]
    if (
        inspected["HostConfig"]["NanoCpus"] != int(resources["cpus"] * 1_000_000_000)
        or inspected["HostConfig"]["Memory"] != resources["memory_bytes"]
    ):
        raise ValueError("running CPU or memory limit differs from manifest")
    command = inspected["Config"]["Cmd"]
    workers = command[command.index("--workers") + 1] if "--workers" in command else "1"
    environment = dict(value.split("=", 1) for value in inspected["Config"]["Env"])
    if (
        int(workers) != resources["workers"]
        or int(environment.get("WEB_CONCURRENCY", "1")) != resources["workers"]
    ):
        raise ValueError("running worker count differs from manifest")
    reference = json.loads(Path(manifest["reference_flow"]).read_bytes())
    before = statistics(container)
    samples = [before]
    stop = threading.Event()
    sampling_errors: list[str] = []

    def sample() -> None:
        while not stop.wait(2):
            try:
                samples.append(statistics(container))
            except (OSError, subprocess.SubprocessError, ValueError) as error:
                sampling_errors.append(type(error).__name__)

    thread = threading.Thread(target=sample, daemon=True)
    thread.start()
    receipt: dict[str, Any] = {
        "label": label,
        "success": False,
        "workload": manifest["workload"],
        "side": manifest["side"],
        "manifest_sha256": hashlib.sha256(raw).hexdigest(),
        "image": actual_image,
        "container_id": container,
        "delivery_sha": manifest["delivery_sha"],
        "seed_manifest": manifest["seed_manifest"],
        "resources": manifest["resources"],
        "host_load_before": os.getloadavg(),
        "timed_boundary": "issuer CLI start through authenticated numerical/provenance API retrieval",
    }
    start = time.monotonic()
    try:
        with stdout.open("xb") as out, stderr.open("xb") as err:
            result = subprocess.run(
                [
                    *execute,
                    *manifest["issuer_arguments"],
                ],
                stdout=out,
                stderr=err,
                timeout=manifest["driver_timeout_seconds"],
                check=False,
            )
        receipt["exit_code"] = result.returncode
        if result.returncode:
            raise RuntimeError("issuer command failed; see retained stderr")
        flow = json.loads(stdout.read_bytes())
        if flow["status"] != "calculated":
            raise ValueError("issuer flow did not calculate")
        api = subprocess.check_output(
            [
                *execute,
                "python",
                "-c",
                API_RETRIEVAL,
                manifest["container_output_directory"] + "/" + stdout.name,
                manifest["caller_id"],
                manifest["organization_id"],
            ],
            timeout=30,
        )
        receipt["wall_seconds"] = time.monotonic() - start
        (directory / (label + "-api.json")).write_bytes(api)
        if (
            flow["effective_valuation_timestamp"]
            != manifest["effective_valuation_timestamp"]
        ):
            raise ValueError("effective valuation date drifted")
        calculation = flow["automatic_execution"]["calculation"]
        if numerical_projection(calculation) != numerical_projection(
            reference["automatic_execution"]["calculation"]
        ):
            raise ValueError("numerical results, statuses or assumptions differ")
        if manifest["workload"] == "C":
            require_reuse(flow)
            if stable_signature(flow) != stable_signature(reference):
                raise ValueError("fixed-input replay signature differs")
        receipt.update(
            success=True,
            authenticated_api=json.loads(api),
            result_hash=calculation["result_hash"],
            arithmetic_all_scenarios_equal=True,
        )
    except (
        OSError,
        subprocess.SubprocessError,
        ValueError,
        KeyError,
        RuntimeError,
    ) as error:
        receipt["failure"] = type(error).__name__ + ": " + str(error)
    finally:
        receipt.setdefault("wall_seconds", time.monotonic() - start)
        stop.set()
        thread.join(timeout=12)
        after: dict[str, int] | None
        try:
            after = statistics(container)
            samples.append(after)
        except (OSError, subprocess.SubprocessError, ValueError) as error:
            after = None
            sampling_errors.append("final:" + type(error).__name__)
            receipt["success"] = False
            receipt.setdefault("failure", "final container statistics unavailable")
        receipt.update(
            cpu_seconds=(after["cpu_us"] - before["cpu_us"]) / 1e6
            if after is not None
            else None,
            max_sampled_cgroup_memory_bytes=max(
                row["memory_current"] for row in samples
            ),
            cgroup_peak_bytes=after["memory_peak"] if after is not None else None,
            memory_scope="sampled cgroup usage and container lifetime peak; neither is process RSS",
            sampling_errors=sampling_errors,
            host_load_after=os.getloadavg(),
        )
        receipt_path.write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt), flush=True)
    return bool(receipt["success"])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--label", required=True)
    arguments = parser.parse_args()
    return 0 if run(arguments.manifest, arguments.label) else 1


if __name__ == "__main__":
    raise SystemExit(main())
