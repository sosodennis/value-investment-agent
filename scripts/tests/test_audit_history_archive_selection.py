"""Archive research retains both failed cases and missing capture receipts."""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path
from zipfile import ZipFile

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))

from audit_history_archive_selection import audit
from audit_history_dqc_applicability import canonical_bytes, digest, write_report


def fixture(root: Path) -> dict:
    accession = "0000766704-14-000006"
    primary = "hcn-20131231.xml"
    base = (
        f"https://www.sec.gov/Archives/edgar/data/766704/{accession.replace('-', '')}"
    )
    direct = b"<xbrl>100</xbrl>"
    buffer = io.BytesIO()
    with ZipFile(buffer, "w") as zipped:
        zipped.writestr(primary, b"<xbrl>\n100</xbrl>")
        zipped.writestr("hcn.xsd", b"<schema/>")
    archive = buffer.getvalue()
    index = canonical_bytes(
        {
            "directory": {
                "item": [
                    {"name": primary, "size": str(len(direct))},
                    {"name": f"{accession}-xbrl.zip", "size": str(len(archive))},
                    {"name": "hcn.xsd", "size": "9"},
                ]
            }
        }
    )
    sources = []
    for name, content, media in (
        ("index.json", index, "application/json"),
        (primary, direct, "text/xml"),
        (f"{accession}-xbrl.zip", archive, "application/zip"),
    ):
        hashed = digest(content)
        path = (
            root
            / hashed[:2]
            / (hashed + (".json" if media == "application/json" else ".bin"))
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        sources.append(
            {
                "accession": accession,
                "available_at": "2014-02-21T21:43:00Z",
                "content_hash": hashed,
                "form": "SEC-FILING-INDEX" if name == "index.json" else "10-K",
                "media_type": media,
                "uri": f"{base}/{name}",
            }
        )
    return {
        "target": {
            "cik": "0000766704",
            "accession": accession,
            "accepted_at": "2014-02-21T21:43:00Z",
            "valuation_timestamp": "2016-02-18T22:23:14Z",
        },
        "original_result_digest": "a" * 64,
        "sources": sources,
        "relation": "canonical_xml_different",
    }


def test_full_inventory_retains_refusal_unknown_receipts_and_reuses_artifacts(
    tmp_path: Path,
) -> None:
    source = fixture(tmp_path / "content")
    failed = json.loads(json.dumps(source))
    failed["target"]["cik"] = "0000000001"
    output = audit({"output": {"rows": [source, failed]}}, tmp_path / "content")
    assert output["filing_count"] == 2
    assert output["status_counts"] == {"refused": 1, "selected_for_validation": 1}
    selected = next(row for row in output["rows"] if "selection" in row)
    assert selected["original_source_comparison"] == source
    assert selected["selection"]["direct"]["http_status"] is None
    assert "CAPTURE_HTTP_RECEIPTS_UNAVAILABLE" in selected["selection"]["discrepancies"]
    assert selected["publication_approved"] is False
    first = write_report(tmp_path / "reports", output)
    path = tmp_path / "reports" / f"{first['report_digest']}.json"
    before = (path.read_bytes(), path.stat().st_mtime_ns)
    repeated = audit({"output": {"rows": [failed, source]}}, tmp_path / "content")
    assert repeated == output
    assert write_report(tmp_path / "reports", repeated) == first | {"wrote": False}
    assert (path.read_bytes(), path.stat().st_mtime_ns) == before


def test_corrupt_source_and_duplicate_target_do_not_disappear(tmp_path: Path) -> None:
    source = fixture(tmp_path)
    descriptor = source["sources"][1]
    hashed = descriptor["content_hash"]
    (tmp_path / hashed[:2] / (hashed + ".bin")).write_bytes(b"corrupt")
    output = audit({"output": {"rows": [source]}}, tmp_path)
    assert output["filing_count"] == 1
    assert output["failure_counts"] == {"SOURCE_EVIDENCE_INVALID": 1}
    with pytest.raises(ValueError, match="repeats a frozen target"):
        audit({"output": {"rows": [source, source]}}, tmp_path)
