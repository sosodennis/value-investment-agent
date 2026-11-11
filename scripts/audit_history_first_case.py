"""Freeze a real-case evidence packet without approving mappings or forecasts."""

from __future__ import annotations

import argparse
import collections
import json
import platform
import subprocess
from datetime import datetime
from pathlib import Path

from audit_history_dqc_applicability import canonical_bytes, digest, write_report

PROTOCOL = "fixed100-first-case-diagnostic-v1"
SELECTION = (
    "ascending decision_at then issuer_id; original passed/unpublished decision, "
    "first subsequent original annual label within frozen horizon, and at least "
    "one passed original history filing available before origin; no outcome ranking"
)
PASSED = frozenset({"validation_passed_unpublished", "parsed_without_blockers"})


def timestamp(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.utcoffset() is None:
        raise ValueError("filing timestamps must carry a timezone")
    return result


def identity(target: dict) -> tuple[str, str, str]:
    return target["issuer_id"], target["accession"], target["valuation_timestamp"]


def unique_rows(rows: list[dict]) -> dict:
    indexed = {identity(row["target"]): row for row in rows}
    if len(indexed) != len(rows):
        raise ValueError("filing evidence repeats a frozen target")
    return indexed


def audit(baseline: dict, subset: dict) -> dict:
    """Retain every case and select a diagnostic packet before numerical outcomes."""
    original = unique_rows(baseline["rows"])
    updated = unique_rows(subset["rows"])
    issuers = {issuer["issuer_id"]: issuer for issuer in baseline["issuers"]}
    if (
        len(original) != baseline["filing_count"]
        or len(issuers) != baseline["issuer_count"]
        or len(issuers) != len(baseline["issuers"])
        or {key[0] for key in original} != set(issuers)
        or len(updated) != subset["filing_count"]
    ):
        raise ValueError("declared filing/issuer inventory differs from evidence")
    for key, row in updated.items():
        if (
            key not in original
            or original[key]["target"] != row["target"]
            or original[key]["original_failure_code"] != "SOURCE_ARCHIVE_SIZE_MISMATCH"
        ):
            raise ValueError("subset does not bind an original source-size refusal")
        if row["status"] not in {
            "parsed_without_blockers",
            "parsed_with_blockers",
            "parser_refused",
            "selection_refused",
        }:
            raise ValueError("unknown subset parser status")

    rows_by_issuer: dict[str, list[dict]] = collections.defaultdict(list)
    for key, row in original.items():
        newer = updated.get(key)
        status = newer["status"] if newer else row["original_status"]
        rows_by_issuer[key[0]].append(
            {
                "target": row["target"],
                "original_status": row["original_status"],
                "original_failure_code": row["original_failure_code"],
                "original_result_digest": row["original_result_digest"],
                "original_output_digest": row["original_output_digest"],
                "current_status": status,
                "current_failure_code": newer.get("failure_code")
                if newer
                else row["original_failure_code"],
                "current_result_digest": newer.get("report_digest")
                if newer
                else row["original_result_digest"],
                "source_diagnostic_passed": status in PASSED,
                "canonical_publication_approved": False,
            }
        )

    cases = []
    for issuer_id, issuer in issuers.items():
        filings = sorted(
            rows_by_issuer[issuer_id],
            key=lambda row: (
                timestamp(row["target"]["accepted_at"]),
                row["target"]["accession"],
            ),
        )
        decisions = [r for r in filings if r["target"]["role"] == "decision"]
        labels = [r for r in filings if r["target"]["role"] == "label"]
        if len(decisions) != 1 or len(labels) > 1:
            raise ValueError("issuer must retain one decision and at most one label")
        decision = decisions[0]
        target = decision["target"]
        origin = timestamp(issuer["decision_at"])
        if (
            issuer["decision_accession"] != target["accession"]
            or origin != timestamp(target["valuation_timestamp"])
            or timestamp(target["accepted_at"]) > origin
        ):
            raise ValueError("decision does not bind the frozen issuer origin")
        label = labels[0] if labels else None
        if issuer["label_accession"] != (
            label["target"]["accession"] if label else None
        ):
            raise ValueError("label does not bind the frozen first original accession")
        history = [r for r in filings if r["target"]["role"] == "history"]
        if any(timestamp(r["target"]["accepted_at"]) > origin for r in history):
            raise ValueError("history input is available after the decision")
        if any(
            r["target"]["role"] not in {"decision", "history", "label"} for r in filings
        ):
            raise ValueError("unknown frozen filing role")
        if label and timestamp(label["target"]["accepted_at"]) <= origin:
            raise ValueError("out-of-sample label must be available after the decision")
        passed_history = [
            r
            for r in history
            if r["source_diagnostic_passed"] and r["target"]["form"] == "10-K"
        ]
        reasons = []
        if not decision["source_diagnostic_passed"]:
            reasons.append("DECISION_SOURCE_NOT_PASSED")
        if target["form"] != "10-K":
            reasons.append("DECISION_ORIGINAL_REQUIRED")
        if label is None:
            reasons.append("FIRST_ORIGINAL_LABEL_MISSING")
        else:
            if not label["source_diagnostic_passed"]:
                reasons.append("LABEL_SOURCE_NOT_PASSED")
            if label["target"]["form"] != "10-K":
                reasons.append("LABEL_ORIGINAL_REQUIRED")
        if issuer["label_horizon_matches_forecast"] is not True:
            reasons.append("LABEL_HORIZON_NOT_ELIGIBLE")
        if not passed_history:
            reasons.append("PASSED_ORIGINAL_HISTORY_UNAVAILABLE")
        cases.append(
            {
                "issuer_id": issuer_id,
                "decision_at": issuer["decision_at"],
                "decision_accession": issuer["decision_accession"],
                "label_accession": issuer["label_accession"],
                "label_horizon_matches_forecast": issuer[
                    "label_horizon_matches_forecast"
                ],
                "diagnostic_packet_eligible": not reasons,
                "ineligibility_reasons": sorted(reasons),
                "passed_original_history_accessions": [
                    r["target"]["accession"] for r in passed_history
                ],
                "filings": filings,
                "forecast_ready": False,
                "canonical_publication_approved": False,
            }
        )
    cases.sort(key=lambda case: (timestamp(case["decision_at"]), case["issuer_id"]))
    eligible = [case for case in cases if case["diagnostic_packet_eligible"]]
    return {
        "protocol": PROTOCOL,
        "selection_rule": SELECTION,
        "issuer_count": len(cases),
        "filing_count": len(original),
        "eligible_diagnostic_case_count": len(eligible),
        "selected_case": eligible[0] if eligible else None,
        "cases": cases,
        "status_counts": dict(
            sorted(
                collections.Counter(
                    row["current_status"] for case in cases for row in case["filings"]
                ).items()
            )
        ),
        "canonical_forecasts_executed": 0,
        "supported_history_threshold": None,
        "limitations": (
            "An overlay of different retained validation batches, not a fresh full "
            "cohort execution. A diagnostic packet is not three complete model "
            "periods, reviewed mapping, release, approval or forecast readiness. "
            "Keep the selected case after discovering its gaps; do not substitute "
            "a case based on forecast values/errors. Labels are evidence for later "
            "evaluation only and cannot fill origin inputs."
        ),
    }


def verified_report(path: Path, expected: str) -> dict:
    raw = path.read_bytes()
    if digest(raw) != expected:
        raise ValueError("evidence report differs from its pinned digest")
    value = json.loads(raw)
    if (
        canonical_bytes(value) != raw
        or digest(canonical_bytes(value["inputs"])) != value["input_digest"]
        or digest(canonical_bytes(value["output"])) != value["output_digest"]
    ):
        raise ValueError(
            "evidence report is not canonical or has invalid payload digests"
        )
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-report", type=Path, required=True)
    parser.add_argument("--baseline-sha256", required=True)
    parser.add_argument("--subset-report", type=Path, required=True)
    parser.add_argument("--subset-sha256", required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    args = parser.parse_args()
    baseline = verified_report(args.baseline_report, args.baseline_sha256)
    subset = verified_report(args.subset_report, args.subset_sha256)
    if (baseline["output"]["issuer_count"], baseline["output"]["filing_count"]) != (
        100,
        589,
    ):
        raise ValueError("the fixed 100-issuer / 589-filing inventory changed")
    repository = Path(
        subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"], text=True
        ).strip()
    )
    if args.output_directory.resolve().is_relative_to(repository.resolve()):
        raise ValueError("generated research evidence must be outside the Git worktree")
    inputs = {
        "protocol": PROTOCOL,
        "selection_rule": SELECTION,
        "source_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True
        ).strip(),
        "script_digest": digest(Path(__file__).read_bytes()),
        "serialization_source_digest": digest(
            Path(__file__).with_name("audit_history_dqc_applicability.py").read_bytes()
        ),
        "baseline_report_digest": args.baseline_sha256,
        "subset_report_digest": args.subset_sha256,
        "runtime": {"python": platform.python_version()},
    }
    output = audit(baseline["output"], subset["output"])
    report = {
        "inputs": inputs,
        "input_digest": digest(canonical_bytes(inputs)),
        "output": output,
        "output_digest": digest(canonical_bytes(output)),
    }
    receipt = write_report(args.output_directory, report)
    print(
        json.dumps(
            {
                "report": receipt,
                "input_digest": report["input_digest"],
                "output_digest": report["output_digest"],
                "issuer_count": output["issuer_count"],
                "filing_count": output["filing_count"],
                "eligible_diagnostic_case_count": output[
                    "eligible_diagnostic_case_count"
                ],
                "selected_issuer": output["selected_case"]["issuer_id"]
                if output["selected_case"]
                else None,
                "canonical_forecasts_executed": 0,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
