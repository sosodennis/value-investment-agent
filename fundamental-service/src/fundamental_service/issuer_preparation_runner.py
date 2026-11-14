"""Prepare SEC sources from an issuer and valuation date using service owners."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from time import monotonic

from .annual_discovery import AnnualDiscoveryParametersV1
from .current_preparation import CurrentSourcePreparationPublicationV1
from .data_releases import ArtifactRefV1
from .original_preparation import OriginalSecuritySelectionV1
from .original_source_plan import (
    AutomaticSourcePlanConfigurationV1,
    OriginalSourcePlanEvidenceV1,
)
from .source_plan_contracts import SOURCE_PREPARATION_PLAN
from .replay import ArtifactRecordV1
from .serialization import canonical_bytes


def _run_module(
    module: str, arguments: list[str], *, timeout_seconds: float
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-c",
            "import importlib\nimport sys\n"
            "raise SystemExit(importlib.import_module(sys.argv[1]).main(sys.argv[2:]))",
            module,
            *arguments,
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
    )


def _run_child(
    module: str, arguments: list[str], *, timeout_seconds: float
) -> dict[str, object]:
    try:
        result = _run_module(module, arguments, timeout_seconds=timeout_seconds)
    except subprocess.TimeoutExpired as error:
        raise RuntimeError(
            f"{module} exceeded the issuer preparation deadline"
        ) from error
    if result.returncode:
        raise RuntimeError(
            f"{module} failed with exit {result.returncode}: {result.stderr.strip()}"
        )
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise RuntimeError(f"{module} returned invalid JSON") from error
    if not isinstance(value, dict):
        raise RuntimeError(f"{module} returned a non-object result")
    return value


def _append_path_argument(arguments: list[str], flag: str, path: Path | None) -> None:
    if path is not None:
        arguments.extend((flag, str(path)))


def _timeout_seconds(value: str) -> int:
    try:
        seconds = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("timeout must be an integer") from error
    if not 1 <= seconds <= 900:
        raise argparse.ArgumentTypeError("timeout must be between 1 and 900 seconds")
    return seconds


def _remaining_seconds(deadline: float) -> float:
    remaining = deadline - monotonic()
    if remaining <= 0:
        raise TimeoutError("issuer preparation exceeded its total timeout")
    return remaining


def _execute(args: argparse.Namespace) -> dict[str, object]:
    deadline = monotonic() + args.timeout_seconds
    parameters = AnnualDiscoveryParametersV1(
        cik=args.cik.zfill(10),
        valuation_timestamp=datetime.fromisoformat(args.valuation_timestamp),
        declared_source_revision=args.source_revision,
        original_count=args.original_count,
        lookback_days=args.lookback_days,
    )
    configuration = AutomaticSourcePlanConfigurationV1.model_validate_json(
        args.source_plan_configuration.read_bytes()
    )
    if configuration.digest != args.configuration_digest:
        raise ValueError("source-plan configuration digest differs")
    if args.current and (
        configuration.issuer_market_policy_template is None
        or configuration.issuer_market_policy_template.source_plan_template is None
    ):
        raise ValueError("current issuer preparation requires public-source templates")
    selection = OriginalSecuritySelectionV1(
        ticker=args.ticker,
        share_class=args.share_class,
    )

    discovery_arguments = [
        "--cik",
        parameters.cik,
        "--valuation-timestamp",
        parameters.valuation_timestamp.isoformat(),
        "--source-revision",
        parameters.declared_source_revision,
        "--original-count",
        str(parameters.original_count),
        "--lookback-days",
        str(parameters.lookback_days),
        "--timeout-seconds",
        str(max(1, int(_remaining_seconds(deadline)))),
        "--prepare-originals",
        "--source-plan-configuration",
        str(args.source_plan_configuration),
        "--configuration-digest",
        args.configuration_digest,
    ]
    if selection.ticker is not None:
        discovery_arguments.extend(("--ticker", selection.ticker))
    if selection.share_class is not None:
        discovery_arguments.extend(("--share-class", selection.share_class))
    if args.validation_profile_id is not None:
        discovery_arguments.extend(
            ("--validation-profile-id", args.validation_profile_id)
        )

    discovery = _run_child(
        "fundamental_service.annual_discovery_runner",
        discovery_arguments,
        timeout_seconds=_remaining_seconds(deadline),
    )
    evidence_value = discovery.get("evidence")
    if not isinstance(evidence_value, dict):
        raise RuntimeError("annual discovery omitted source-plan evidence")
    evidence = OriginalSourcePlanEvidenceV1.model_validate_json(
        json.dumps(evidence_value)
    )
    if evidence.request.runtime_source_revision != parameters.declared_source_revision:
        raise ValueError("compiled source plan runtime revision differs")
    if evidence.request.configuration != configuration:
        raise ValueError("compiled source plan configuration differs")
    if discovery.get("input_digest") != evidence.request.digest:
        raise ValueError("compiled source plan request digest differs")
    if discovery.get("output_digest") != evidence.digest:
        raise ValueError("compiled source plan output digest differs")
    if not isinstance(discovery.get("wrote"), bool):
        raise ValueError("source-plan publication omitted its write disposition")
    lineage = discovery.get("lineage")
    if (
        not isinstance(lineage, dict)
        or not {
            "annual_discovery",
            "original_preparation",
            "source_plan_compilation",
        }
        <= lineage.keys()
    ):
        raise ValueError("issuer preparation omitted stage lineage")
    annual_stage = lineage["annual_discovery"]
    original_stage = lineage["original_preparation"]
    compilation_stage = lineage["source_plan_compilation"]
    if not all(
        isinstance(stage, dict)
        and isinstance(stage.get("artifact_id"), str)
        and isinstance(stage.get("input_digest"), str)
        and isinstance(stage.get("output_digest"), str)
        and isinstance(stage.get("wrote"), bool)
        for stage in (annual_stage, original_stage, compilation_stage)
    ):
        raise ValueError("issuer preparation stage lineage is malformed")
    if (
        original_stage.get("source_artifact_id") != annual_stage["artifact_id"]
        or original_stage.get("source_digest") != annual_stage["output_digest"]
        or original_stage["artifact_id"]
        != evidence.request.original_preparation.artifact_id
        or original_stage["output_digest"]
        != evidence.request.original_preparation.content_hash
        or compilation_stage.get("source_artifact_id") != original_stage["artifact_id"]
        or compilation_stage.get("source_digest") != original_stage["output_digest"]
        or compilation_stage["artifact_id"] != evidence.artifact_id
        or compilation_stage["input_digest"] != evidence.request.digest
        or compilation_stage["output_digest"] != evidence.digest
        or compilation_stage["wrote"] != discovery["wrote"]
    ):
        raise ValueError("issuer preparation stage lineage does not join")

    shared = {
        "protocol": "fundamental-issuer-preparation-flow-v1",
        "original_preparation_artifact_id": evidence.request.original_preparation.artifact_id,
        "source_plan_compilation_artifact_id": evidence.artifact_id,
        "source_plan_compilation_digest": evidence.digest,
        "source_plan_request_digest": evidence.request.digest,
        "source_plan_ref": evidence.plan_ref,
        "source_plan_issue_codes": evidence.issue_codes,
        "source_plan_wrote": discovery["wrote"],
        "lineage": lineage,
    }
    if evidence.plan is None:
        return {**shared, "status": "blocked", "preparation": None}
    if not args.actor.strip() or not args.organization.strip():
        raise ValueError("issuer preparation requires an actor and organization")
    if args.machine_private_key is None:
        raise ValueError("automatic source preparation requires a machine private key")

    plan = SOURCE_PREPARATION_PLAN.validate_python(evidence.plan)
    plan_ref = evidence.plan_ref
    if plan_ref is None:
        raise ValueError("compiled plan omitted its retained reference")
    if (
        plan.digest != plan_ref.content_hash
        or plan.source_revision != parameters.declared_source_revision
        or plan.model_id != configuration.model_id
        or any(
            request.cik != parameters.cik
            or request.valuation_timestamp != parameters.valuation_timestamp
            for request in plan.ingestions
        )
    ):
        raise ValueError("compiled plan does not match the issuer request")

    with tempfile.TemporaryDirectory(prefix="fundamental-issuer-plan-") as folder:
        plan_path = Path(folder) / "source-plan.json"
        temporary_plan_path = Path(folder) / "source-plan.json.tmp"
        temporary_plan_path.write_bytes(canonical_bytes(plan))
        os.replace(temporary_plan_path, plan_path)
        preparation_arguments = [
            "--plan",
            str(plan_path),
            "--plan-digest",
            plan.digest,
            "--runtime-source-revision",
            parameters.declared_source_revision,
            "--actor",
            args.actor,
            "--organization",
            args.organization,
            "--timeout-seconds",
            str(max(1, int(_remaining_seconds(deadline)))),
            "--machine-private-key",
            str(args.machine_private_key),
        ]
        if args.current:
            preparation_arguments.append("--current")
        for flag, path in (
            ("--candidate", args.candidate),
            ("--approval", args.approval),
            ("--market-policy-authorization", args.market_policy_authorization),
        ):
            _append_path_argument(preparation_arguments, flag, path)
        if args.market_policy_authorization_digest is not None:
            preparation_arguments.extend(
                (
                    "--market-policy-authorization-digest",
                    args.market_policy_authorization_digest,
                )
            )
        preparation = _run_child(
            "fundamental_service.preparation_runner",
            preparation_arguments,
            timeout_seconds=_remaining_seconds(deadline),
        )
    effective_plan_ref = plan_ref
    effective_lineage = dict(lineage)
    current_fields: dict[str, object] = {}
    if args.current:
        current = CurrentSourcePreparationPublicationV1.model_validate_json(
            canonical_bytes(preparation)
        )
        selected = current.current_selection
        if selected.request.template != plan:
            raise ValueError("current source selection differs from the compiled plan")
        effective_lineage["current_source_selection"] = {
            "artifact_id": selected.artifact_id,
            "input_digest": selected.request.digest,
            "output_digest": selected.digest,
            "wrote": current.current_selection_publication.wrote,
            "source_artifact_id": plan_ref.artifact_id,
            "source_digest": plan.digest,
        }
        current_fields["current_source_issue_codes"] = selected.issue_codes
        if selected.plan is None:
            acquisitions = current.source_acquisitions_publication
            if acquisitions is not None:
                effective_lineage["source_acquisition"] = {
                    "artifact_id": acquisitions.artifact.artifact_id,
                    "input_digest": plan.digest,
                    "output_digest": acquisitions.artifact.content_hash,
                    "wrote": acquisitions.wrote,
                    "source_artifact_id": plan_ref.artifact_id,
                    "source_digest": plan.digest,
                }
                current_fields["source_acquisitions"] = acquisitions
            return {
                **shared,
                **current_fields,
                "lineage": effective_lineage,
                "status": "blocked",
                "preparation": None,
            }
        plan = selected.plan
        effective_plan_ref = ArtifactRefV1(
            artifact_id=f"source-preparation-plan:{plan.digest}",
            content_hash=plan.digest,
            media_type="application/json",
            role=plan.protocol,
        )
        current_fields["effective_source_plan_ref"] = effective_plan_ref
        current_fields["effective_valuation_timestamp"] = plan.ingestions[
            0
        ].valuation_timestamp
    publication = preparation.get("artifact")
    if not isinstance(publication, dict):
        raise RuntimeError("source preparation omitted its artifact receipt")
    publication_record = ArtifactRecordV1.model_validate_json(json.dumps(publication))
    if plan.digest not in publication_record.dependency_hashes or not isinstance(
        preparation.get("wrote"), bool
    ):
        raise ValueError("source preparation receipt does not reference its plan")
    complete_lineage = {
        **effective_lineage,
        "source_preparation": {
            "artifact_id": publication_record.artifact_id,
            "input_digest": plan.digest,
            "output_digest": publication_record.content_hash,
            "wrote": preparation["wrote"],
            "source_artifact_id": effective_plan_ref.artifact_id,
            "source_digest": plan.digest,
        },
    }
    return {
        **shared,
        **current_fields,
        "lineage": complete_lineage,
        "status": "preparation_attempted",
        "preparation": preparation,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cik", required=True)
    parser.add_argument("--valuation-timestamp", required=True)
    parser.add_argument(
        "--current",
        action="store_true",
        help="capture configured public sources, then freeze the current valuation cutoff",
    )
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--source-plan-configuration", type=Path, required=True)
    parser.add_argument("--configuration-digest", required=True)
    parser.add_argument("--original-count", type=int, default=2)
    parser.add_argument("--lookback-days", type=int, default=3650)
    parser.add_argument("--timeout-seconds", type=_timeout_seconds, default=120)
    parser.add_argument("--ticker")
    parser.add_argument("--share-class")
    parser.add_argument(
        "--validation-profile-id",
        choices=("sec-efm-us-dqc-v31.0.3", "sec-efm-us-dqc-v1.0.0-historical"),
    )
    parser.add_argument("--actor")
    parser.add_argument("--organization")
    parser.add_argument("--machine-private-key", type=Path)
    parser.add_argument("--candidate", type=Path)
    parser.add_argument("--approval", type=Path)
    parser.add_argument("--market-policy-authorization", type=Path)
    parser.add_argument("--market-policy-authorization-digest")
    args = parser.parse_args(argv)
    try:
        if (args.market_policy_authorization is None) != (
            args.market_policy_authorization_digest is None
        ):
            raise ValueError("market-policy authorization requires its exact digest")
        result = _execute(args)
    except (OSError, RuntimeError, TypeError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 2
    print(canonical_bytes(result).decode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
