"""Offline, content-addressed publication of a pinned operating scenario replay."""

import argparse
import hashlib
import json
import platform
import subprocess
from importlib.metadata import version
from pathlib import Path

from .operating_scenario_contracts import OperatingScenarioRequestV1
from .operating_scenarios import replay_operating_scenarios
from .replay import ArtifactStore
from .serialization import sha256_digest


def publish_scenario_replay(
    request: OperatingScenarioRequestV1,
    *,
    artifacts: ArtifactStore,
    execution: dict[str, object],
) -> dict[str, object]:
    """Reuse the existing locked, fsynced temporary-file/atomic-rename store."""
    request = request.model_copy(
        update={
            "facts": tuple(
                sorted(
                    request.facts, key=lambda fact: (fact.fact_id, sha256_digest(fact))
                )
            )
        }
    )
    result = replay_operating_scenarios(request)
    values = (
        ("input", request),
        ("mapping", request.mappings),
        ("forecast", result),
        (
            "report",
            {
                "protocol": "operating-scenario-report-v1",
                "execution": execution,
                "input_digest": result.input_digest,
                "output_digest": result.output_digest,
                "mapping_digest": request.mapping_manifest_digest,
                "result": result,
            },
        ),
    )
    publications = {}
    for kind, value in values:
        digest = sha256_digest(value)
        receipt = artifacts.put_with_receipt(
            f"operating-scenario-{kind}-{digest}",
            value,
            dependency_hashes=(result.input_digest, request.mapping_manifest_digest),
        )
        publications[kind] = {
            "artifact_id": receipt.artifact.artifact_id,
            "digest": receipt.artifact.content_hash,
            "wrote": receipt.wrote,
        }
    return {
        "input_digest": result.input_digest,
        "output_digest": result.output_digest,
        "wrote": any(publication["wrote"] for publication in publications.values()),
        "publications": publications,
        "scenario_results": len(result.results),
        "provisional_scenarios": sum(
            item.status == "provisional_scenario" for item in result.results
        ),
        "abstained": sum(item.status == "abstained" for item in result.results),
        "supported_history_threshold": None,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--implementation-commit", required=True)
    args = parser.parse_args()
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    if revision != args.implementation_commit:
        parser.error("implementation commit differs from the executing checkout")
    if subprocess.check_output(["git", "status", "--porcelain"], text=True).strip():
        parser.error("exact-commit replay requires a clean checkout")
    lock_path = Path(__file__).resolve().parents[2] / "uv.lock"
    execution: dict[str, object] = {
        "exact_commit": revision,
        "python": platform.python_version(),
        "packages": {
            name: version(name)
            for name in ("pydantic", "arelle-release", "cryptography")
        },
        "uv_lock_digest": hashlib.sha256(lock_path.read_bytes()).hexdigest(),
        "command": [
            "python",
            "-m",
            "fundamental_service.operating_scenario_runner",
            *(
                str(value)
                for value in (
                    "--request",
                    args.request,
                    "--artifacts",
                    args.artifacts,
                    "--implementation-commit",
                    revision,
                )
            ),
        ],
    }
    request = OperatingScenarioRequestV1.model_validate_json(args.request.read_bytes())
    receipt = publish_scenario_replay(
        request, artifacts=ArtifactStore(args.artifacts), execution=execution
    )
    print(json.dumps(receipt, sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
