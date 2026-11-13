"""Audit frozen annual-label selection without acquiring or replacing evidence."""

from __future__ import annotations

import argparse
import gzip
import json
import platform
import re
import subprocess
from collections import Counter
from datetime import UTC, date, datetime
from pathlib import Path

from fundamental_service.history_sufficiency_report import (
    Filing,
    first_subsequent_original_filing,
)

from analyze_history_study import hash_value, list_value, object_value, text_value
from plan_history_study_precision import (
    MANIFEST_DIGEST,
    ROOT,
    DesignError,
    canonical_bytes,
    digest,
    publish_report,
)


def decode_json(raw: bytes) -> object:
    def unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result = dict(pairs)
        if len(result) != len(pairs):
            raise DesignError("duplicate JSON fields cannot discard label evidence")
        return result

    return json.loads(raw, object_pairs_hook=unique)


def timestamp(value: object) -> datetime:
    result = datetime.fromisoformat(text_value(value).replace("Z", "+00:00"))
    if result.utcoffset() is None:
        raise DesignError("filing availability must include a timezone")
    return result.astimezone(UTC)


def decode_filing(value: object, issuer: str) -> Filing:
    row = object_value(value)
    accession = text_value(row["accession_number"])
    if not re.fullmatch(r"\d{10}-\d{2}-\d{6}", accession):
        raise DesignError("invalid annual filing accession")
    if row["form"] not in ("10-K", "10-K/A"):
        raise DesignError("frozen annual inventory contains a nonannual form")
    return Filing(
        issuer_id=issuer,
        accession=accession,
        form=text_value(row["form"]),
        period_end=date.fromisoformat(text_value(row["report_period_end"])),
        accepted_at=timestamp(row["accepted_at"]),
    )


def filing_identity(filing: Filing) -> dict[str, str]:
    return {
        "accession": filing.accession,
        "form": filing.form,
        "period_end": filing.period_end.isoformat(),
        "accepted_at": filing.accepted_at.isoformat().replace("+00:00", "Z"),
    }


def audit_issuer(
    frozen: dict[str, object], snapshot: dict[str, object]
) -> dict[str, object]:
    issuer = text_value(frozen["issuer_id"])
    if (
        snapshot.get("schema_version") != "issue-359-issuer-snapshot-v1"
        or snapshot.get("issuer_id") != issuer
        or snapshot.get("cik") != issuer[4:]
        or snapshot.get("decision_accession") != frozen["decision_accession"]
    ):
        raise DesignError("snapshot issuer or decision differs from frozen cohort")
    filings = tuple(
        sorted(
            (decode_filing(row, issuer) for row in list_value(snapshot["filings"])),
            key=lambda filing: (
                filing.period_end,
                filing.accepted_at,
                filing.accession,
            ),
        )
    )
    if len({filing.accession for filing in filings}) != len(filings):
        raise DesignError("duplicate or conflicting annual filing accessions")
    decisions = [f for f in filings if f.accession == frozen["decision_accession"]]
    if (
        len(decisions) != 1
        or decisions[0].form != "10-K"
        or decisions[0].accepted_at != timestamp(frozen["decision_at"])
    ):
        raise DesignError(
            "decision original or availability differs from frozen cohort"
        )
    decision = decisions[0]
    later = [
        f
        for f in filings
        if f.period_end > decision.period_end and f.accepted_at > decision.accepted_at
    ]
    label = first_subsequent_original_filing(decision, filings)
    if label is not None:
        ties = [
            f
            for f in later
            if f.form == "10-K"
            and f.period_end == label.period_end
            and f.accepted_at == label.accepted_at
        ]
        if len(ties) != 1:
            raise DesignError("first original has ambiguous equal availability")
    selected_accession = label.accession if label else None
    gap = (label.period_end - decision.period_end).days if label else None
    missing_reason = "no_first_subsequent_original" if label is None else None
    if (
        selected_accession != frozen["label_accession"]
        or gap != frozen["label_period_gap_days"]
        or missing_reason != frozen["label_missing_reason"]
    ):
        raise DesignError("recomputed label selection differs from frozen manifest")
    eligible = frozen["label_horizon_matches_forecast"]
    if (label is None and eligible is not None) or (
        label is not None and not isinstance(eligible, bool)
    ):
        raise DesignError("missing label cannot have a measured horizon result")
    if label is None:
        disposition = (
            "no_later_annual_period_in_snapshot"
            if not later
            else "earliest_later_period_has_no_original"
        )
    else:
        disposition = "eligible_frozen_label" if eligible else "frozen_horizon_mismatch"
    responses = [object_value(v) for v in list_value(snapshot["source_responses"])]
    submissions = [v for v in responses if v.get("source_id") == "sec-submissions"]
    if not submissions:
        raise DesignError("snapshot lacks retained submissions response metadata")
    for response in submissions:
        hash_value(response["response_sha256"])
        text_value(response["uri"])
        if response.get("http_status") != 200:
            raise DesignError("snapshot submissions response was not successful")
    return {
        "issuer_id": issuer,
        "decision": filing_identity(decision),
        "selected_label": filing_identity(label) if label else None,
        "disposition": disposition,
        "label_period_gap_days": gap,
        "frozen_horizon_eligible": eligible,
        "missing_reason": missing_reason,
        "missingness_mechanism": "unestablished_from_normalized_inventory",
        "annual_filings": [filing_identity(f) for f in filings],
        "later_annual_accessions": [f.accession for f in later],
        "retained_submissions_metadata": sorted(
            submissions,
            key=lambda row: (
                text_value(row["uri"]),
                hash_value(row["response_sha256"]),
            ),
        ),
    }


def audit_labels(manifest: object, snapshot_directory: Path) -> dict[str, object]:
    if digest(canonical_bytes(manifest)) != MANIFEST_DIGEST:
        raise DesignError("fixed 100-issuer manifest digest differs")
    frozen = object_value(manifest)
    inventory = object_value(frozen["original_inventory"])
    if digest(canonical_bytes(inventory)) != frozen["original_inventory_digest"]:
        raise DesignError("frozen original inventory digest differs")
    decisions: dict[str, dict[str, object]] = {}
    for value in list_value(frozen["issuer_decisions"]):
        row = object_value(value)
        issuer = text_value(row["issuer_id"])
        if not re.fullmatch(r"CIK:\d{10}", issuer) or issuer in decisions:
            raise DesignError("issuer identities must be unique fixed CIKs")
        decisions[issuer] = row
    snapshots: dict[str, dict[str, object]] = {}
    for value in list_value(inventory["issuers"]):
        row = object_value(value)
        issuer = text_value(row["issuer_id"])
        if issuer in snapshots or issuer not in decisions:
            raise DesignError("snapshot inventory duplicates or substitutes an issuer")
        if any(row[k] != decisions[issuer][k] for k in decisions[issuer] if k in row):
            raise DesignError("snapshot inventory differs from frozen decisions")
        snapshots[issuer] = row
    if len(decisions) != 100 or set(snapshots) != set(decisions):
        raise DesignError("all 100 unique issuer snapshots are required")
    rows = []
    for issuer, decision in sorted(decisions.items()):
        snapshot_digest = hash_value(snapshots[issuer]["snapshot_sha256"])
        packed = (snapshot_directory / f"{issuer[4:]}.json.gz").read_bytes()
        if digest(packed) != snapshot_digest:
            raise DesignError("frozen gzip snapshot digest differs")
        raw = gzip.decompress(packed)
        snapshot = object_value(decode_json(raw))
        rows.append(
            {
                **audit_issuer(decision, snapshot),
                "snapshot_bytes_digest": snapshot_digest,
                "snapshot_content_digest": digest(canonical_bytes(snapshot)),
            }
        )
    counts = dict(
        sorted(Counter(text_value(row["disposition"]) for row in rows).items())
    )
    return {
        "schema_version": "history-study-label-audit.v1",
        "authority": "frozen_normalized_inventory_selection_not_raw_sec_completeness",
        "selection_policy": "existing_first_subsequent_original_filing",
        "horizon_policy": "unchanged_frozen_manifest_eligibility_not_new_tolerance",
        "selected_issuers": len(rows),
        "disposition_counts": counts,
        "maximum_eligible_label_pairs": counts.get("eligible_frozen_label", 0),
        "rows": rows,
        "source_completeness_verified": False,
        "mapping_or_release_approved": False,
        "forecasts_executed": 0,
        "supported_history_threshold": None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("manifest", "snapshot-directory", "output-directory"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--exact-commit", required=True)
    args = parser.parse_args()
    try:
        head = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip()
        dirty = subprocess.check_output(
            ["git", "status", "--porcelain"], cwd=ROOT, text=True
        )
        if head != args.exact_commit or dirty:
            raise DesignError("exact clean implementation commit is required")
        raw = args.manifest.read_bytes()
        manifest = decode_json(raw)
        output = audit_labels(manifest, args.snapshot_directory)
        selection_path = (
            ROOT
            / "fundamental-service/src/fundamental_service/history_sufficiency_report.py"
        )
        inputs = {
            "issue": 376,
            "exact_commit": head,
            "manifest_bytes_digest": digest(raw),
            "manifest_digest": digest(canonical_bytes(manifest)),
            "tool_digest": digest(Path(__file__).read_bytes()),
            "selection_tool_digest": digest(selection_path.read_bytes()),
            "publication_tool_digest": digest(
                (ROOT / "scripts/plan_history_study_precision.py").read_bytes()
            ),
            "decoding_tool_digest": digest(
                (ROOT / "scripts/analyze_history_study.py").read_bytes()
            ),
            "lock_digest": digest((ROOT / "fundamental-service/uv.lock").read_bytes()),
            "snapshot_digests": [
                object_value(row)["snapshot_bytes_digest"]
                for row in list_value(output["rows"])
            ],
            "runtime": {
                "python": platform.python_version(),
                "implementation": platform.python_implementation(),
                "machine": platform.machine(),
                "system": platform.system(),
            },
        }
        report = {
            "inputs": inputs,
            "input_digest": digest(canonical_bytes(inputs)),
            "output": output,
            "output_digest": digest(canonical_bytes(output)),
        }
        result = publish_report(args.output_directory, report)
        print(
            json.dumps(
                {
                    **result,
                    "input_digest": report["input_digest"],
                    "output_digest": report["output_digest"],
                },
                sort_keys=True,
            )
        )
    except (
        OSError,
        ValueError,
        KeyError,
        EOFError,
        subprocess.CalledProcessError,
    ) as error:
        parser.exit(2, f"history-study label audit failed: {error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
