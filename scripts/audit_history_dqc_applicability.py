"""Audit retained historical DQC findings without changing publication decisions."""

from __future__ import annotations

import argparse
import base64
import collections
import fcntl
import gzip
import hashlib
import json
import os
import platform
import re
import subprocess
import tempfile
from datetime import UTC, date, datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

CHECKPOINT_PATH = (
    "docs/acceptance/issue-361-marker62-evidence-v1/checkpoint/"
    "066b9d02ee2d855dbc3ebf688c97b571ea709401f8dff4795d48023ea2147d4f.json.gz"
)
CHECKPOINT_DIGEST = "066b9d02ee2d855dbc3ebf688c97b571ea709401f8dff4795d48023ea2147d4f"
GUIDANCE_URL = "https://xbrl.us/data-quality/rules-guidance/"
MONTHS = {
    name: number
    for number, name in enumerate(
        (
            "Jan",
            "Feb",
            "Mar",
            "Apr",
            "May",
            "Jun",
            "Jul",
            "Aug",
            "Sep",
            "Oct",
            "Nov",
            "Dec",
        ),
        1,
    )
}


def canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


class GuidanceText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.suppressed = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("style", "script"):
            self.suppressed += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in ("style", "script"):
            self.suppressed -= 1

    def handle_data(self, data: str) -> None:
        if not self.suppressed:
            self.parts.append(data)


def rule_effective_dates(html: str) -> dict[str, str]:
    parser = GuidanceText()
    parser.feed(html)
    text = re.sub(r"\s+", " ", " ".join(parser.parts))
    result: dict[str, str] = {}
    pattern = r"DQC_(\d{4}) Approved:.*? Effective: ([A-Za-z]+ \d{1,2}, \d{4})"
    for family, text_date in re.findall(pattern, text):
        month, day, year = text_date.replace(",", "").split()
        parsed = date(int(year), MONTHS[month[:3]], int(day)).isoformat()
        if family in result and result[family] != parsed:
            raise ValueError(f"conflicting official effective dates: {family}")
        result[family] = parsed
    if not result:
        raise ValueError("no rule effective dates found in the official guidance")
    return dict(sorted(result.items()))


def classify_finding(
    finding: dict[str, Any], accepted_at: str, dates: dict[str, str]
) -> dict[str, Any]:
    code = str(finding["code"])
    match = re.match(r"^DQC\.US\.(\d{4})(?:\.|$)", code)
    effective = dates.get(match[1]) if match else None
    if not match:
        applicability = "non_dqc_requires_owner_diagnosis"
    elif effective is None:
        applicability = "unknown_rule_effective_date"
    else:
        accepted = datetime.fromisoformat(accepted_at.replace("Z", "+00:00"))
        if accepted.utcoffset() is None:
            raise ValueError("filing acceptance must include a timezone")
        filed_day = accepted.astimezone(UTC).date()
        effective_day = date.fromisoformat(effective)
        applicability = (
            "pre_effective_no_historical_compliance_claim"
            if filed_day < effective_day
            else "effective_date_boundary_requires_review"
            if filed_day == effective_day
            else "family_effective_exact_revision_requires_review"
        )
    return {
        "original_finding": finding,
        "rule_family": match[1] if match else None,
        "family_effective_date": effective,
        "historical_compliance_applicability": applicability,
        "financial_materiality": "not_adjudicated",
        "publication_approved": False,
    }


class EvidenceReader:
    def __init__(self, root: Path, repository: Path, revision: str) -> None:
        if re.fullmatch(r"[0-9a-f]{40}", revision) is None:
            raise ValueError("archive revision must be an exact commit SHA")
        self.root = root.resolve()
        self.repository = repository
        self.revision = revision

    def _read(self, path: str, expected_digest: str) -> bytes:
        relative = Path(path)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("evidence path must stay within its source root")
        local = self.root / relative
        if not local.resolve().is_relative_to(self.root):
            raise ValueError("evidence symlink escapes its source root")
        raw = (
            local.read_bytes()
            if local.exists()
            else subprocess.check_output(
                ["git", "-C", str(self.repository), "show", f"{self.revision}:{path}"]
            )
        )
        payload = gzip.decompress(raw)
        if digest(payload) != expected_digest:
            raise ValueError(f"retained evidence digest mismatch: {path}")
        return payload

    def document(self, reference: dict[str, Any]) -> dict[str, Any]:
        if reference["storage"] == "canonical-json-gzip":
            raw = self._read(reference["path"], reference["sha256"])
        elif reference["storage"] == "canonical-json-chunks":
            pieces = []
            offset = 0
            for item in reference["chunks"]:
                if item["offset"] != offset:
                    raise ValueError("evidence chunks are not in contiguous order")
                chunk = json.loads(self._read(item["path"], item["sha256"]))
                part = base64.b64decode(chunk["content_base64"], validate=True)
                if digest(part) != item["content_sha256"] or len(part) != item["bytes"]:
                    raise ValueError("evidence chunk content does not match its pin")
                pieces.append(part)
                offset += len(part)
            raw = b"".join(pieces)
        else:
            raise ValueError("unknown retained evidence storage format")
        if len(raw) != reference["bytes"] or digest(raw) != reference["sha256"]:
            raise ValueError("reconstructed evidence differs from its descriptor")
        result = json.loads(raw)
        if not isinstance(result, dict):
            raise ValueError("evidence document must be an object")
        if canonical_bytes(result) != raw:
            raise ValueError("retained evidence is not canonically serialized")
        return result


def audit(reader: EvidenceReader, dates: dict[str, str]) -> dict[str, Any]:
    checkpoint = json.loads(reader._read(CHECKPOINT_PATH, CHECKPOINT_DIGEST))
    references = checkpoint["inputs"]["roots"]["originals"]
    if len({ref["original_path"] for ref in references}) != len(references):
        raise ValueError("retained evidence descriptors repeat a path")
    documents = {ref["original_path"]: reader.document(ref) for ref in references}
    document_digests = {ref["original_path"]: ref["sha256"] for ref in references}
    inventory = next(v for k, v in documents.items() if k.startswith("inventory/"))
    rejection_index = next(
        v for k, v in documents.items() if k.startswith("rejection_index/")
    )
    rejection_by_id = {
        row["artifact_id"]: documents[f"rejections/{row['sha256']}.json.gz"]
        for row in rejection_index["rejections"]
    }
    results = {
        (v["inputs"]["target"]["issuer_id"], v["inputs"]["target"]["accession"]): (
            v,
            document_digests[k],
        )
        for k, v in documents.items()
        if k.startswith("results/")
    }
    targets = inventory["targets"]
    if len(targets) != 589 or len(inventory["issuers"]) != 100:
        raise ValueError("the fixed 100-issuer / 589-filing inventory changed")
    if len(results) != len(targets):
        raise ValueError("filing results are missing or duplicated")
    if sum(k.startswith("results/") for k in documents) != len(results):
        raise ValueError("retained results repeat a filing identity")
    rows = []
    failure_counts: collections.Counter[str] = collections.Counter()
    finding_counts: collections.Counter[str] = collections.Counter()
    blocking_filings: collections.Counter[str] = collections.Counter()
    pre_effective_roles: collections.Counter[str] = collections.Counter()
    only_pre_effective = 0
    for target in sorted(
        targets,
        key=lambda t: (
            t["valuation_timestamp"],
            t["issuer_id"],
            t["accepted_at"],
            t["accession"],
        ),
    ):
        result, result_digest = results[(target["issuer_id"], target["accession"])]
        if result["inputs"]["target"] != target:
            raise ValueError("result target differs from frozen inventory")
        output = result["output"]
        if digest(canonical_bytes(result["inputs"])) != result["input_digest"]:
            raise ValueError("result input digest differs from recorded inputs")
        if digest(canonical_bytes(output)) != result["output_digest"]:
            raise ValueError("result output digest differs from recorded output")
        findings = []
        rejection = rejection_by_id.get(output.get("evidence_ref"))
        if rejection is not None:
            findings = rejection["integrity_evidence"]["findings"]
        elif output.get("code") == "PARSER_VALIDATION_BLOCKED":
            raise ValueError("parser rejection is missing its original findings")
        classified = [
            classify_finding(f, target["accepted_at"], dates) for f in findings
        ]
        blocking = [f for f in classified if f["original_finding"]["blocks"]]
        pre_only = bool(blocking) and all(
            f["historical_compliance_applicability"]
            == "pre_effective_no_historical_compliance_claim"
            for f in blocking
        )
        only_pre_effective += pre_only
        if pre_only:
            pre_effective_roles[target["role"]] += 1
        blocking_filings.update({str(f["original_finding"]["code"]) for f in blocking})
        failure_counts[str(output.get("code") or output["status"])] += 1
        finding_counts.update(
            f["historical_compliance_applicability"] for f in classified
        )
        rows.append(
            {
                "target": target,
                "original_result_digest": result_digest,
                "original_status": output["status"],
                "original_failure_code": output.get("code"),
                "original_output_digest": result["output_digest"],
                "original_sources": output.get("sources", []),
                "findings": classified,
                "all_original_blockers_pre_effective": pre_only,
                "canonical_publication_approved": False,
            }
        )
    missing_labels = sum(i["label_accession"] is None for i in inventory["issuers"])
    issuers = []
    for issuer in inventory["issuers"]:
        decision = next(
            t
            for t in targets
            if t["issuer_id"] == issuer["issuer_id"] and t["role"] == "decision"
        )
        label = next(
            (
                t
                for t in targets
                if t["issuer_id"] == issuer["issuer_id"] and t["role"] == "label"
            ),
            None,
        )
        gap = (
            (
                date.fromisoformat(label["period_end"])
                - date.fromisoformat(decision["period_end"])
            ).days
            if label
            else None
        )
        issuers.append(
            {
                **issuer,
                "label_period_gap_days": gap,
                "label_horizon_matches_forecast": 300 <= gap <= 380
                if gap is not None
                else None,
            }
        )
    horizon_mismatches = sum(
        i["label_horizon_matches_forecast"] is False for i in issuers
    )
    return {
        "filing_count": len(rows),
        "issuer_count": len(inventory["issuers"]),
        "failure_counts": dict(sorted(failure_counts.items())),
        "finding_applicability_counts": dict(sorted(finding_counts.items())),
        "blocking_filing_counts_by_finding_code": dict(
            sorted(blocking_filings.items())
        ),
        "filings_with_only_pre_effective_blockers": only_pre_effective,
        "only_pre_effective_blocker_filings_by_role": dict(
            sorted(pre_effective_roles.items())
        ),
        "missing_original_labels": missing_labels,
        "label_horizon_mismatches": horizon_mismatches,
        "maximum_complete_label_pairs_after_horizon_checks": len(issuers)
        - missing_labels
        - horizon_mismatches,
        "absolute_label_pair_ceiling_before_horizon_checks": len(inventory["issuers"])
        - missing_labels,
        "rows": rows,
        "issuers": issuers,
        "supported_history_threshold": None,
        "canonical_publication_approved": False,
        "limitation": "Family dates do not certify the exact rule revision or financial materiality. No release or forecast is approved by this audit.",
    }


def write_report(directory: Path, report: dict[str, Any]) -> dict[str, Any]:
    raw = canonical_bytes(report)
    report_digest = digest(raw)
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / f"{report_digest}.json"
    with (directory / ".report.lock").open("ab") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        return _write_locked(destination, raw, report_digest)


def _write_locked(destination: Path, raw: bytes, report_digest: str) -> dict[str, Any]:
    if destination.exists():
        if destination.read_bytes() != raw:
            raise ValueError("existing content-addressed report is corrupt")
        return {"report_digest": report_digest, "wrote": False}
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=destination.parent, delete=False
        ) as output:
            temporary_path = Path(output.name)
            output.write(raw)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary_path, destination)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    return {"report_digest": report_digest, "wrote": True}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--archive-repository", type=Path, required=True)
    parser.add_argument("--archive-commit", required=True)
    parser.add_argument("--guidance-html", type=Path, required=True)
    parser.add_argument("--guidance-sha256", required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    args = parser.parse_args()
    repository_root = Path(
        subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"], text=True
        ).strip()
    ).resolve()
    if args.output_directory.resolve().is_relative_to(repository_root):
        raise ValueError("generated research evidence must be outside the Git worktree")
    guidance = args.guidance_html.read_bytes()
    if digest(guidance) != args.guidance_sha256:
        raise ValueError("official guidance digest differs from its pin")
    dates = rule_effective_dates(guidance.decode("utf-8"))
    inputs = {
        "protocol": "fixed100-dqc-applicability-audit-v1",
        "checkpoint_digest": CHECKPOINT_DIGEST,
        "source_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True
        ).strip(),
        "script_sha256": digest(Path(__file__).read_bytes()),
        "archive_commit": args.archive_commit,
        "guidance_url": GUIDANCE_URL,
        "guidance_sha256": args.guidance_sha256,
        "rule_family_effective_dates": dates,
        "date_comparison": "UTC filing date; date-only boundary is unresolved; exact revision and materiality remain unadjudicated",
        "runtime": {
            "python": platform.python_version(),
            "implementation": platform.python_implementation(),
        },
    }
    output = audit(
        EvidenceReader(
            args.evidence_root, args.archive_repository, args.archive_commit
        ),
        dates,
    )
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
                **receipt,
                "input_digest": report["input_digest"],
                "output_digest": report["output_digest"],
                "summary": {
                    k: v
                    for k, v in output.items()
                    if k
                    not in {"rows", "issuers", "blocking_filing_counts_by_finding_code"}
                },
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
