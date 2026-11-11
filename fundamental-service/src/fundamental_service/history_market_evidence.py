"""Freeze historical macro evidence for review without creating policy approval."""

from __future__ import annotations

import argparse
import csv
import gzip
import io
import json
import os
import sys
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .history_mapping_audit import (
    DEFAULT_COHORT_MANIFEST,
    ROOT,
    MappingAuditError,
    _array,
    _decision_targets,
    _filings,
    _load_snapshot_for,
    _object,
    _read_json,
    _selected_issuers,
    _text,
    _timestamp,
)
from .history_replay import (
    _ensure_tracked_tree_clean,
    _resolve_commit,
    _runtime_pins,
    _write_content_addressed,
)
from .history_replay_inputs import DEFAULT_DIRECTORY, _digest, _write_immutable
from .public_source import PublicSourceAdapter
from .serialization import canonical_bytes, sha256_digest
from .snapshots import SnapshotError
from .valuation_requirements import valuation_requirements_profile

SOURCE_PROFILE = "alfred-dgs10-prior-day-vintage-v1"
TERMS_REFERENCE = "https://fred.stlouisfed.org/terms-of-use/"
DEFAULT_OUTPUT = DEFAULT_DIRECTORY.parent / "issue-361-market-evidence-v1"


def _uri(vintage: date) -> str:
    return (
        "https://alfred.stlouisfed.org/graph/alfredgraph.csv?id=DGS10"
        f"&cosd={vintage - timedelta(days=14)}&coed={vintage}"
        f"&vintage_date={vintage}"
    )


def _observation(content: bytes, vintage: date) -> dict[str, str]:
    column = f"DGS10_{vintage:%Y%m%d}"
    reader = csv.DictReader(io.StringIO(content.decode("utf-8-sig")))
    if reader.fieldnames != ["observation_date", column]:
        raise MappingAuditError("ALFRED response does not match the requested vintage")
    observations: dict[date, Decimal] = {}
    for row in reader:
        if None in row or None in row.values():
            raise MappingAuditError("ALFRED response has an invalid CSV row")
        observed = date.fromisoformat(row["observation_date"])
        if not vintage - timedelta(days=14) <= observed <= vintage:
            raise MappingAuditError(
                "ALFRED observation is outside the requested period"
            )
        if row[column] in {"", "."}:
            continue
        try:
            value = Decimal(row[column])
        except InvalidOperation as error:
            raise MappingAuditError("ALFRED observation is not numeric") from error
        if not value.is_finite():
            raise MappingAuditError("ALFRED observation must be finite")
        if observed in observations and observations[observed] != value:
            raise MappingAuditError("ALFRED observation has conflicting values")
        observations[observed] = value
    if not observations:
        raise MappingAuditError("ALFRED response contains no rate observation")
    latest = max(observations)
    return {
        "series_id": "DGS10",
        "vintage_date": vintage.isoformat(),
        "observation_date": latest.isoformat(),
        "source_value": str(observations[latest]),
        "source_unit": "percent_per_annum",
        "value": str(observations[latest] / Decimal("100")),
        "unit": "decimal_rate_per_annum",
        "as_of": datetime.combine(latest, time(), UTC).isoformat(),
        "available_at": datetime.combine(
            vintage + timedelta(days=1), time(), UTC
        ).isoformat(),
        "availability_basis": "end_of_requested_alfred_vintage_day",
    }


def capture_market_evidence(
    *, source_manifest_path: Path, output_directory: Path = DEFAULT_OUTPUT
) -> dict[str, object]:
    """Capture each fixed vintage once, including failures, and retain every issuer."""

    manifest = _object(
        json.loads(gzip.decompress(source_manifest_path.read_bytes())), "SEC inputs"
    )
    input_digest = sha256_digest(manifest)
    if input_digest != source_manifest_path.name.removesuffix(".json.gz"):
        raise MappingAuditError("SEC input manifest digest mismatch")
    if manifest.get("cohort_digest") != _digest(DEFAULT_COHORT_MANIFEST.read_bytes()):
        raise MappingAuditError("SEC inputs differ from the fixed cohort")
    records = [
        _object(row, "SEC issuer")
        for row in _array(manifest.get("issuer_records"), "SEC issuers")
    ]
    ciks = [_text(row.get("cik"), "CIK") for row in records]
    if len(set(ciks)) != len(records) or not records:
        raise MappingAuditError("SEC issuer identities must be nonempty and unique")
    selected = _selected_issuers(_read_json(DEFAULT_COHORT_MANIFEST, "fixed cohort"))
    by_cik = {row["cik"]: row for row in records}
    if set(by_cik) != {row["cik"] for row in selected}:
        raise MappingAuditError("SEC inputs changed the fixed issuer denominator")
    for issuer in selected:
        snapshot = _load_snapshot_for(ROOT, issuer)
        decision, _, _, _ = _decision_targets(
            _filings(snapshot, _text(issuer.get("issuer_id"), "issuer_id")),
            _text(issuer.get("decision_accession"), "decision_accession"),
        )
        row = by_cik[issuer["cik"]]
        if (
            row.get("decision_accession") != decision.accession
            or _timestamp(row.get("decision_at"), "decision_at") != decision.accepted_at
        ):
            raise MappingAuditError("SEC input changed a fixed decision")
    vintages = {
        _timestamp(row.get("decision_at"), "decision_at").date() - timedelta(days=1)
        for row in records
    }
    downloads = 0
    wrote_sources = False
    receipts: dict[date, dict[str, object]] = {}
    source_candidates: dict[date, dict[str, str] | None] = {}
    adapter = None
    for vintage in sorted(vintages):
        uri = _uri(vintage)
        key = sha256_digest({"source_profile": SOURCE_PROFILE, "uri": uri})
        path = output_directory / "source_index" / f"{key}.bundle.gz"
        if path.exists():
            receipt_bytes, content = gzip.decompress(path.read_bytes()).split(b"\n", 1)
            receipt = _object(json.loads(receipt_bytes), "macro receipt")
        else:
            if adapter is None:
                adapter = PublicSourceAdapter(
                    user_agent=os.environ.get("FUNDAMENTAL_SEC_USER_AGENT", ""),
                    max_attempts=1,
                )
            downloads += 1
            available_at = datetime.combine(vintage + timedelta(days=1), time(), UTC)
            try:
                source = adapter.capture(
                    "alfred-vintage", uri, available_at=available_at
                )
                content = source.content
                captured_at = source.captured_at or datetime.now(UTC)
                failure_code = None
                status = "captured"
            except SnapshotError as error:
                content = b""
                captured_at = datetime.now(UTC)
                failure_code = error.code
                status = "failed"
            receipt = {
                "source_key": key,
                "source_profile": SOURCE_PROFILE,
                "source_id": "alfred-vintage",
                "source_uri": uri,
                "terms_reference": TERMS_REFERENCE,
                "vintage_date": vintage.isoformat(),
                "captured_at": captured_at.isoformat(),
                "status": status,
                "failure_code": failure_code,
                "response_sha256": _digest(content),
                "response_bytes": len(content),
            }
            wrote_sources |= _write_immutable(
                path, gzip.compress(canonical_bytes(receipt) + b"\n" + content, mtime=0)
            )
        if (
            receipt.get("source_key") != key
            or receipt.get("source_uri") != uri
            or receipt.get("source_profile") != SOURCE_PROFILE
            or receipt.get("response_sha256") != _digest(content)
            or receipt.get("response_bytes") != len(content)
            or receipt.get("status") not in {"captured", "failed"}
        ):
            raise MappingAuditError(
                "immutable macro source identity or digest mismatch"
            )
        parse_failure = None
        candidate = None
        if receipt["status"] == "captured":
            try:
                candidate = _observation(content, vintage)
            except (ValueError, UnicodeError):
                parse_failure = "SOURCE_PAYLOAD_INVALID"
        source_candidates[vintage] = candidate
        receipts[vintage] = {
            **receipt,
            "bundle_digest": _digest(path.read_bytes()),
            "parse_failure_code": parse_failure,
            "observation": candidate,
        }
    roles = valuation_requirements_profile("fcff_dcf").market_policy_input_roles
    issuer_rows = []
    for row in sorted(
        records, key=lambda row: (str(row["decision_at"]), str(row["cik"]))
    ):
        decision_at = _timestamp(row["decision_at"], "decision_at")
        vintage = decision_at.date() - timedelta(days=1)
        candidate = source_candidates[vintage]
        issuer_rows.append(
            {
                "cik": row["cik"],
                "decision_accession": row["decision_accession"],
                "decision_at": row["decision_at"],
                "source_key": receipts[vintage]["source_key"],
                "roles": {
                    role: {
                        "status": "unapproved_source_candidate"
                        if role == "risk_free_rate" and candidate is not None
                        else "historical_policy_review_required",
                        "candidate": candidate if role == "risk_free_rate" else None,
                    }
                    for role in roles
                },
            }
        )
    report = {
        "schema_version": "history-market-evidence-v1",
        "runtime": _runtime_pins(_resolve_commit()),
        "input_digest": input_digest,
        "cohort_digest": manifest["cohort_digest"],
        "source_profile": SOURCE_PROFILE,
        "source_records": [receipts[vintage] for vintage in sorted(vintages)],
        "issuer_rows": issuer_rows,
        "selected_issuer_count": len(issuer_rows),
        "approved_policy_count": 0,
        "approval_basis": None,
        "threshold_ground_truth": "SEC first subsequent original annual filing only",
        "supported_history_threshold": None,
    }
    artifact = _write_content_addressed(output_directory, "review", report)
    return {
        "input_digest": input_digest,
        "output_digest": artifact["sha256"],
        "artifact": artifact,
        "downloads": downloads,
        "selected_issuer_count": len(issuer_rows),
        "source_count": len(receipts),
        "observed_candidate_count": sum(
            value is not None for value in source_candidates.values()
        ),
        "wrote": wrote_sources or artifact["wrote"],
    }


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-manifest", type=Path, required=True)
    parser.add_argument("--output-directory", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    try:
        _ensure_tracked_tree_clean(str(Path(__file__).resolve().relative_to(ROOT)))
        result = capture_market_evidence(
            source_manifest_path=args.source_manifest,
            output_directory=args.output_directory,
        )
        print(
            json.dumps(
                {"commit_sha": _resolve_commit(), "command_result": "exit 0", **result},
                sort_keys=True,
            )
        )
        return 0
    except (OSError, ValueError, SnapshotError) as error:
        print(f"historical market evidence failed: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(_main())
