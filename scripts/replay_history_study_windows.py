"""Replay explicit trailing history arms from frozen conditional evidence."""

from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from pathlib import Path
from typing import Literal

from pydantic import Field

from fundamental_service.contracts import StrictModel
from fundamental_service.operating_label_contracts import OperatingComparisonRequestV1
from fundamental_service.operating_labels import replay_operating_comparison
from fundamental_service.operating_scenario_contracts import OperatingScenarioRequestV1
from fundamental_service.operating_scenarios import replay_operating_scenarios
from fundamental_service.serialization import canonical_bytes, sha256_digest

import export_history_study_evidence as exporter
from analyze_history_study import ROOT, WINDOWS, DesignError, read_document
from plan_history_study_precision import digest, publish_report


class WindowSeedIndex(StrictModel):
    schema_version: Literal["history-study-window-seeds.v1"]
    fixed_manifest_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    runtime: exporter.RuntimePins
    seeds: tuple[exporter.FileReference, ...] = Field(min_length=1, max_length=100)


def trailing_request(
    seed: OperatingComparisonRequestV1, years: int
) -> OperatingComparisonRequestV1:
    """Select periods and existing allocations without changing financial policy."""
    if years not in WINDOWS or len(seed.decision.periods) < years:
        raise DesignError("requested complete history window is unavailable")
    periods = seed.decision.periods[-years:]
    scenarios = tuple(
        scenario.model_copy(
            update={
                "continuing_capex_fractions": {
                    period.fiscal_year: scenario.continuing_capex_fractions[
                        period.fiscal_year
                    ]
                    for period in periods
                }
            }
        )
        for scenario in seed.decision.scenarios
    )
    decision = OperatingScenarioRequestV1.model_validate_json(
        canonical_bytes(
            seed.decision.model_copy(
                update={"periods": periods, "scenarios": scenarios}
            )
        )
    )
    return OperatingComparisonRequestV1.model_validate_json(
        canonical_bytes(
            seed.model_copy(
                update={
                    "decision": decision,
                    "decision_input_digest": sha256_digest(decision),
                }
            )
        )
    )


def prepare_windows(
    manifest: object, index: WindowSeedIndex, directory: Path
) -> tuple[dict[str, object], dict[str, object]]:
    """Verify every generated arm before publishing any output artifact."""
    if (
        sha256_digest(manifest) != exporter.MANIFEST_DIGEST
        or index.fixed_manifest_digest != exporter.MANIFEST_DIGEST
    ):
        raise DesignError("fixed 100-issuer manifest digest differs")
    if index.runtime != exporter.runtime_pins():
        raise DesignError("installed runtime differs from frozen pins")
    artifacts: dict[str, object] = {}
    entries = []
    windows = []
    issuers: set[str] = set()
    for reference in sorted(index.seeds, key=lambda item: item.sha256):
        seed = OperatingComparisonRequestV1.model_validate_json(
            exporter.read_evidence(reference, directory)
        )
        issuer = f"CIK:{seed.decision.source.identity.issuer_id}"
        if issuer in issuers:
            raise DesignError("one longest-history seed is required per issuer")
        issuers.add(issuer)
        for years in WINDOWS:
            if len(seed.decision.periods) < years:
                windows.append(
                    {
                        "issuer_id": issuer,
                        "years": years,
                        "status": "unavailable",
                        "issue_codes": ["HISTORY_WINDOW_EVIDENCE_MISSING"],
                        "seed_digest": reference.sha256,
                    }
                )
                continue
            request = trailing_request(seed, years)
            values = {
                "request": request,
                "forecast": replay_operating_scenarios(request.decision),
                "comparison": replay_operating_comparison(request),
            }
            references = {}
            for kind, value in values.items():
                raw = canonical_bytes(value)
                content_digest = digest(raw)
                artifacts[content_digest] = json.loads(raw)
                references[kind] = exporter.FileReference(
                    path=f"{content_digest}.json", sha256=content_digest
                )
            entries.append(exporter.EvidenceEntry(**references))
            windows.append(
                {
                    "issuer_id": issuer,
                    "years": years,
                    "status": "replayed_conditional_evidence",
                    "fiscal_years": [p.fiscal_year for p in request.decision.periods],
                    "seed_digest": reference.sha256,
                    "artifact_digests": entries[-1].identity(),
                }
            )
    evidence_index = exporter.EvidenceIndex(
        schema_version="history-study-evidence-index.v1",
        fixed_manifest_digest=index.fixed_manifest_digest,
        runtime=index.runtime,
        entries=tuple(sorted(entries, key=lambda item: item.request.sha256)),
    )
    with tempfile.TemporaryDirectory(prefix="history-window-validation-") as temporary:
        stage = Path(temporary)
        for content_digest, value in artifacts.items():
            (stage / f"{content_digest}.json").write_bytes(canonical_bytes(value))
        validation = exporter.export_evidence(manifest, evidence_index, stage)
    output = {
        "schema_version": "history-study-window-replay.v1",
        "windows": sorted(
            windows, key=lambda row: (str(row["issuer_id"]), int(str(row["years"])))
        ),
        "evidence_index": json.loads(canonical_bytes(evidence_index)),
        "evidence_index_digest": sha256_digest(evidence_index),
        "arm_summaries": validation["arm_summaries"],
        "export_output_digest": sha256_digest(validation),
        "represented_issuers": validation["represented_issuers"],
        "independent_conditional_issuers": validation[
            "independent_conditional_issuers"
        ],
        "complete_exact_study_cases": 0,
        "supported_history_threshold": None,
        "authority": "unreviewed_conditional_arithmetic_not_trusted_release",
    }
    return output, artifacts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("manifest", "seed-index", "output-directory"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--exact-commit", required=True)
    args = parser.parse_args()
    try:
        head = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip()
        if head != args.exact_commit or subprocess.check_output(
            ["git", "status", "--porcelain"], cwd=ROOT, text=True
        ):
            raise DesignError("exact clean implementation commit is required")
        index = WindowSeedIndex.model_validate_json(
            canonical_bytes(read_document(args.seed_index))
        )
        output, artifacts = prepare_windows(
            read_document(args.manifest), index, args.seed_index.parent
        )
        inputs = {
            "issue": 377,
            "exact_commit": head,
            "fixed_manifest_digest": index.fixed_manifest_digest,
            "seed_digests": sorted(reference.sha256 for reference in index.seeds),
            "runtime": index.runtime,
            "tool_digest": digest(Path(__file__).read_bytes()),
            "exporter_digest": digest(
                (ROOT / "scripts/export_history_study_evidence.py").read_bytes()
            ),
            "publication_tool_digest": digest(
                (ROOT / "scripts/plan_history_study_precision.py").read_bytes()
            ),
        }
        report = {
            "inputs": inputs,
            "input_digest": sha256_digest(inputs),
            "output": output,
            "output_digest": sha256_digest(output),
        }
        publications = [
            publish_report(args.output_directory, value)
            for _, value in sorted(artifacts.items())
        ]
        index_receipt = publish_report(args.output_directory, output["evidence_index"])
        report_receipt = publish_report(
            args.output_directory, json.loads(canonical_bytes(report))
        )
        print(
            json.dumps(
                {
                    **report_receipt,
                    "wrote": any(
                        receipt["wrote"]
                        for receipt in [*publications, index_receipt, report_receipt]
                    ),
                    "evidence_index_digest": output["evidence_index_digest"],
                    "input_digest": report["input_digest"],
                    "output_digest": report["output_digest"],
                },
                sort_keys=True,
            )
        )
    except (
        OSError,
        ValueError,
        ArithmeticError,
        subprocess.CalledProcessError,
    ) as error:
        parser.exit(2, f"history-window replay failed: {error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
