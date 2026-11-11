"""Retain findings while auditing historical applicability and artifact reuse."""

from __future__ import annotations

import base64
import gzip
import importlib.util
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[1] / "audit_history_dqc_applicability.py"
SPEC = importlib.util.spec_from_file_location("dqc_audit", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)


def test_extracts_official_dates_without_script_content() -> None:
    html = """<script>DQC_9999 Approved: x Effective: Jan 1, 2000</script>
    <p>DQC_0001 Approved: December 15, 2016 Effective: Mar 28, 2017</p>
    <p>DQC_0015 Approved: x Effective: Jan 1, 2016</p>"""
    assert audit.rule_effective_dates(html) == {
        "0001": "2017-03-28",
        "0015": "2016-01-01",
    }


@pytest.mark.parametrize(
    ("accepted_at", "expected"),
    [
        ("2016-12-31T23:59:59Z", "pre_effective_no_historical_compliance_claim"),
        ("2017-01-01T00:00:00Z", "effective_date_boundary_requires_review"),
        ("2017-01-02T00:00:00Z", "family_effective_exact_revision_requires_review"),
    ],
)
def test_classification_retains_blocking_findings(
    accepted_at: str, expected: str
) -> None:
    finding = {"code": "DQC.US.0013.1", "blocks": True, "severity": "error"}
    result = audit.classify_finding(finding, accepted_at, {"0013": "2017-01-01"})
    assert result["original_finding"] == finding
    assert result["historical_compliance_applicability"] == expected
    assert result["publication_approved"] is False
    assert result["financial_materiality"] == "not_adjudicated"


def test_unknown_and_non_dqc_findings_remain_unresolved() -> None:
    for code, classification in [
        ("DQC.US.9999.1", "unknown_rule_effective_date"),
        ("IOerror", "non_dqc_requires_owner_diagnosis"),
    ]:
        result = audit.classify_finding(
            {"code": code, "blocks": True}, "2016-01-01T00:00:00Z", {}
        )
        assert result["historical_compliance_applicability"] == classification
        assert result["publication_approved"] is False


def test_report_repeat_preserves_existing_bytes_and_mtime(tmp_path: Path) -> None:
    report = {"inputs": {"cohort": "fixed"}, "output": {"threshold": None}}
    first = audit.write_report(tmp_path, report)
    destination = tmp_path / f"{first['report_digest']}.json"
    before = destination.stat().st_mtime_ns
    assert first["wrote"] is True
    assert audit.write_report(tmp_path, report) == {**first, "wrote": False}
    assert destination.stat().st_mtime_ns == before
    destination.write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="corrupt"):
        audit.write_report(tmp_path, report)


def test_concurrent_identical_reports_have_only_one_writer(tmp_path: Path) -> None:
    report = {"cohort": "fixed", "threshold": None}
    with ThreadPoolExecutor(max_workers=4) as executor:
        receipts = list(
            executor.map(lambda _: audit.write_report(tmp_path, report), range(12))
        )
    assert sum(r["wrote"] for r in receipts) == 1
    assert len({r["report_digest"] for r in receipts}) == 1
    assert len(list(tmp_path.glob("*.json"))) == 1
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        ".report.lock",
        receipts[0]["report_digest"] + ".json",
    ]


def test_chunked_evidence_checks_each_layer(tmp_path: Path) -> None:
    raw = audit.canonical_bytes({"retained": "facts"})
    chunk = audit.canonical_bytes({"content_base64": base64.b64encode(raw).decode()})
    (tmp_path / "chunk.gz").write_bytes(gzip.compress(chunk, mtime=0))
    ref = {
        "storage": "canonical-json-chunks",
        "sha256": audit.digest(raw),
        "bytes": len(raw),
        "chunks": [
            {
                "path": "chunk.gz",
                "sha256": audit.digest(chunk),
                "offset": 0,
                "content_sha256": audit.digest(raw),
                "bytes": len(raw),
            }
        ],
    }
    reader = audit.EvidenceReader(tmp_path, tmp_path, "a" * 40)
    assert reader.document(ref) == json.loads(raw)
    ref["chunks"][0]["content_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="chunk content"):
        reader.document(ref)


def test_missing_retained_evidence_is_not_silently_dropped(tmp_path: Path) -> None:
    reader = audit.EvidenceReader(tmp_path, tmp_path, "a" * 40)
    with pytest.raises(ValueError, match="source root"):
        reader._read("../outside.gz", "0" * 64)
    with pytest.raises(ValueError, match="exact commit"):
        audit.EvidenceReader(tmp_path, tmp_path, "main")
