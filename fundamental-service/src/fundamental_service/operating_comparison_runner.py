"""Offline content-addressed conditional labels, errors and execution receipts."""

import argparse
import hashlib
import json
import platform
import subprocess
from importlib.metadata import version
from pathlib import Path

from .operating_label_contracts import OperatingComparisonRequestV1
from .operating_labels import replay_operating_comparison
from .operating_scenarios import replay_operating_scenarios
from .replay import ArtifactStore
from .serialization import sha256_digest


def publish_operating_comparison(
    request: OperatingComparisonRequestV1,
    *,
    artifacts: ArtifactStore,
    execution: dict[str, object],
) -> dict[str, object]:
    result = replay_operating_comparison(request)
    forecast = replay_operating_scenarios(request.decision)
    assert forecast.output_digest == result.forecast_output_digest
    publications = {}
    for kind, value in (
        ("input", request),
        (
            "mapping",
            {"decision": request.decision.mappings, "label": request.label.mappings},
        ),
        ("forecast", forecast),
        ("label", result.labels),
        ("comparison", result),
        (
            "report",
            {
                "protocol": "operating-comparison-report-v1",
                "execution": execution,
                "input_digest": result.input_digest,
                "output_digest": result.output_digest,
                "result": result,
            },
        ),
    ):
        digest = sha256_digest(value)
        publication = artifacts.put_with_receipt(
            f"operating-comparison-{kind}-{digest}",
            value,
            dependency_hashes=(
                result.input_digest,
                result.decision_input_digest,
                result.label_input_digest,
            ),
        )
        publications[kind] = {
            "artifact_id": publication.artifact.artifact_id,
            "digest": publication.artifact.content_hash,
            "wrote": publication.wrote,
        }
    by_model = {}
    for model in request.decision.model_versions:
        rows = tuple(row for row in result.comparisons if row.model_id == model)
        complete = tuple(
            row for row in rows if row.status == "provisional_conditional_comparison"
        )
        by_model[model] = {
            "retained_comparison_rows": len(rows),
            "conditional_comparisons": len(complete),
            "abstained": len(rows) - len(complete),
            "independent_issuers_with_conditional_comparison": int(bool(complete)),
            "sampled_signed_error_min": str(
                min(
                    row.signed_error for row in complete if row.signed_error is not None
                )
            )
            if complete
            else None,
            "sampled_signed_error_max": str(
                max(
                    row.signed_error for row in complete if row.signed_error is not None
                )
            )
            if complete
            else None,
            "issue_codes": sorted({code for row in rows for code in row.issue_codes}),
        }
    return {
        "input_digest": result.input_digest,
        "output_digest": result.output_digest,
        "forecast_output_digest": result.forecast_output_digest,
        "label_input_digest": result.label_input_digest,
        "publications": publications,
        "wrote": any(row["wrote"] for row in publications.values()),
        "conditional_labels": sum(
            row.status == "provisional_conditional_label" for row in result.labels
        ),
        "abstained_labels": sum(row.status == "abstained" for row in result.labels),
        "models": by_model,
        "independent_issuer_count": result.independent_issuer_count,
        "complete_exact_study_cases": 0,
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
    request = OperatingComparisonRequestV1.model_validate_json(
        args.request.read_bytes()
    )
    lock = Path(__file__).resolve().parents[2] / "uv.lock"
    execution: dict[str, object] = {
        "exact_commit": revision,
        "python": platform.python_version(),
        "packages": {
            name: version(name)
            for name in ("pydantic", "arelle-release", "cryptography")
        },
        "uv_lock_digest": hashlib.sha256(lock.read_bytes()).hexdigest(),
        "command": [
            "python",
            "-m",
            "fundamental_service.operating_comparison_runner",
            "--request",
            str(args.request),
            "--artifacts",
            str(args.artifacts),
            "--implementation-commit",
            revision,
        ],
    }
    receipt = publish_operating_comparison(
        request, artifacts=ArtifactStore(args.artifacts), execution=execution
    )
    print(json.dumps(receipt, sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
