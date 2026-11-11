"""Apply the owning archive-selection boundary to every retained size refusal."""

from __future__ import annotations

import argparse
import collections
import json
import platform
import subprocess
from datetime import datetime
from importlib.metadata import version
from pathlib import Path

from fundamental_service.contracts import SourceRole
from fundamental_service.historical_source import (
    HistoricalSourceInput,
    select_historical_archive,
)
from fundamental_service.snapshots import SnapshotError

from audit_history_dqc_applicability import canonical_bytes, digest, write_report
from audit_history_source_integrity import read_source


def _capture(root: Path, descriptor: dict, *, index: bool) -> HistoricalSourceInput:
    return HistoricalSourceInput(
        uri=descriptor["uri"],
        role=SourceRole.REFERENCE if index else SourceRole.FILING,
        content=read_source(root, descriptor),
        available_at=datetime.fromisoformat(
            descriptor["available_at"].replace("Z", "+00:00")
        ),
        accession_number=descriptor["accession"],
        form=descriptor["form"],
    )


def audit(report: dict, root: Path) -> dict:
    rows = []
    seen: set[bytes] = set()
    for original in sorted(
        report["output"]["rows"], key=lambda row: canonical_bytes(row["target"])
    ):
        target = original["target"]
        key = canonical_bytes(target)
        if key in seen:
            raise ValueError("source inventory repeats a frozen target")
        seen.add(key)
        row = {
            "target": target,
            "original_result_digest": original["original_result_digest"],
            "original_source_comparison": original,
            "selection_status": "refused",
            "publication_approved": False,
        }
        try:
            descriptors = original["sources"]
            if len(descriptors) != 3:
                raise ValueError(
                    "expected retained index, direct and archive descriptors"
                )
            index, direct, archive = (
                _capture(root, source, index=i == 0)
                for i, source in enumerate(descriptors)
            )
            entries = json.loads(index.content)["directory"]["item"]
            dts = tuple(
                sorted(
                    item["name"]
                    for item in entries
                    if isinstance(item, dict)
                    and isinstance(item.get("name"), str)
                    and item["name"].endswith(
                        (
                            ".xsd",
                            "_cal.xml",
                            "_def.xml",
                            "_lab.xml",
                            "_pre.xml",
                            "_ref.xml",
                        )
                    )
                )
            )
            selected = select_historical_archive(
                cik=target["cik"],
                accession=target["accession"],
                accepted_at=datetime.fromisoformat(
                    target["accepted_at"].replace("Z", "+00:00")
                ),
                valuation_timestamp=datetime.fromisoformat(
                    target["valuation_timestamp"].replace("Z", "+00:00")
                ),
                primary_document=direct.uri.rsplit("/", 1)[-1],
                archive_index=index,
                direct_response=direct,
                archive=archive,
                dts_filenames=dts,
            )
            evidence = selected.evidence.model_dump(mode="json")
            row.update(
                {
                    "selection_status": "selected_for_validation",
                    "selection": evidence,
                    "selection_digest": digest(canonical_bytes(evidence)),
                }
            )
        except SnapshotError as error:
            row.update({"failure_code": error.code, "reason": error.message})
        except OSError:
            row.update({"failure_code": "SOURCE_CONTENT_UNAVAILABLE"})
        except (ValueError, KeyError, TypeError) as error:
            row.update(
                {"failure_code": "SOURCE_EVIDENCE_INVALID", "reason": str(error)}
            )
        rows.append(row)
    return {
        "filing_count": len(rows),
        "independent_issuer_count": len({row["target"]["cik"] for row in rows}),
        "status_counts": dict(
            sorted(collections.Counter(row["selection_status"] for row in rows).items())
        ),
        "failure_counts": dict(
            sorted(
                collections.Counter(
                    row["failure_code"] for row in rows if "failure_code" in row
                ).items()
            )
        ),
        "rows": rows,
        "canonical_forecasts_executed": 0,
        "supported_history_threshold": None,
        "canonical_publication_approved": False,
        "limitation": "Selection binds caller-supplied frozen metadata and retained bytes. HTTP receipts absent from the archived descriptors stay null with a discrepancy; acceptance metadata is not independently certified here. Local DTS candidates come from indexed schema/linkbase filenames; full DTS, parser, representation semantics, applicability, mappings and release checks remain required. Original failures are retained, not reclassified as validation passes.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-report", type=Path, required=True)
    parser.add_argument("--source-report-sha256", required=True)
    parser.add_argument("--content-root", type=Path, required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    args = parser.parse_args()
    raw = args.source_report.read_bytes()
    if digest(raw) != args.source_report_sha256:
        raise ValueError("source report differs from its pin")
    report = json.loads(raw)
    if report["output_digest"] != digest(canonical_bytes(report["output"])):
        raise ValueError("source report output digest is invalid")
    if report["input_digest"] != digest(canonical_bytes(report["inputs"])):
        raise ValueError("source report input digest is invalid")
    repository = Path(
        subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"], text=True
        ).strip()
    )
    if args.output_directory.resolve().is_relative_to(repository.resolve()):
        raise ValueError("generated research evidence must be outside the Git worktree")
    source_root = repository / "fundamental-service/src/fundamental_service"
    inputs = {
        "protocol": "fixed100-original-archive-selection-audit-v1",
        "source_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True
        ).strip(),
        "source_report_sha256": args.source_report_sha256,
        "source_digests": {
            str(path.relative_to(repository)): digest(path.read_bytes())
            for path in (
                Path(__file__).resolve(),
                *(
                    source_root / name
                    for name in (
                        "historical_source.py",
                        "sec_archive.py",
                        "serialization.py",
                        "snapshots.py",
                        "contracts.py",
                    )
                ),
                repository / "scripts/audit_history_source_integrity.py",
                repository / "scripts/audit_history_dqc_applicability.py",
                repository / "fundamental-service/uv.lock",
            )
        },
        "runtime": {
            "python": platform.python_version(),
            "pydantic": version("pydantic"),
        },
    }
    output = audit(report, args.content_root)
    result = {
        "inputs": inputs,
        "input_digest": digest(canonical_bytes(inputs)),
        "output": output,
        "output_digest": digest(canonical_bytes(output)),
    }
    print(
        json.dumps(
            {
                **write_report(args.output_directory, result),
                "input_digest": result["input_digest"],
                "output_digest": result["output_digest"],
                "summary": {
                    key: value for key, value in output.items() if key != "rows"
                },
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
