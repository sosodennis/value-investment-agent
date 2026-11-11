"""Official assertion semantics must not silently change release decisions."""

from __future__ import annotations

import gzip
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))

import audit_history_dqc_conformance as replay


@pytest.fixture
def matcher(tmp_path: Path):
    root = tmp_path / "DQC_0001"
    root.mkdir()
    path = root / "variation.xml"
    path.write_text("""<testcase xmlns="http://xbrl.org/2008/conformance">
    <variation id="expected"><data><instance readMeFirst="true">fixture.xml</instance></data>
      <results blockedMessageCodes="DQC.US.0001.ignored">
        <error severity="error" count="2">DQC.US.0001.target</error>
      </results></variation>
    <variation id="strict"><data><instance readMeFirst="true">fixture.xml</instance></data>
      <results><error severity="error" count="1">DQC.US.0001.target</error>
        <result match="all"/></results></variation>
    <variation id="valid"><data><instance readMeFirst="true">fixture.xml</instance></data>
      <results/></variation></testcase>""")
    value = replay.OfficialMatcher([path])
    try:
        yield value
    finally:
        value.close()


def _finding(code: str, severity: str = "error") -> dict:
    return {
        "code": f"DQC.US.0001.{code}",
        "severity": "warning",
        "rule_severity": severity,
        "message": "retained original finding",
    }


def test_expected_count_uses_official_default_and_preserves_extra_findings(matcher):
    findings = [_finding("target"), _finding("target"), _finding("additional")]
    result = matcher.compare("expected", findings)
    assert result["official_status"] == "pass"
    assert result["expected_count"] == 2
    assert result["match_all"] is False
    assert result["actual_counts"] == {
        "DQC.US.0001.target": 2,
        "DQC.US.0001.additional": 1,
    }
    assert len(findings) == 3
    assert matcher.cases[0]["instance"] == "DQC_0001/fixture.xml"


@pytest.mark.parametrize("count", [0, 1, 3])
def test_wrong_declared_count_still_fails(matcher, count):
    assert (
        matcher.compare("expected", [_finding("target")] * count)["official_status"]
        == "fail"
    )


def test_explicit_match_all_and_no_error_expectations_remain_strict(matcher):
    result = matcher.compare("strict", [_finding("target"), _finding("additional")])
    assert result["official_status"] == "fail" and result["match_all"]
    assert matcher.compare("valid", [])["official_status"] == "pass"
    assert (
        matcher.compare("valid", [_finding("additional")])["official_status"] == "fail"
    )


def test_original_severity_not_edgar_releveled_warning_drives_capture(matcher):
    assert (
        matcher.compare("expected", [_finding("target")] * 2)["official_status"]
        == "pass"
    )
    warnings = [_finding("target", "warning")] * 2
    assert matcher.compare("expected", warnings)["official_status"] == "fail"
    unknown = [_finding("target", None)] * 2
    assert matcher.compare("expected", unknown)["unknown_original_severity_count"] == 2


@pytest.mark.parametrize(
    "changes",
    [
        {"all_modules_completed": False},
        {"returned_modules": replay.MODULES[:-1]},
        {"unsupported_namespaces": ["http://fasb.org/us-gaap/2011-01-31"]},
        {"runtime_errors": ["rule exception"]},
        {"network_attempt_count": 1},
    ],
)
def test_matching_assertion_cannot_hide_incomplete_execution(changes):
    record = {
        "case": {"id": "case"},
        "index": 0,
        "passed": False,
        "success": True,
        "all_modules_completed": True,
        "returned_modules": replay.MODULES,
        "network_attempt_count": 0,
        **changes,
    }
    result = replay.assess(
        record, {"official_status": "pass", "unknown_original_severity_count": 0}
    )
    assert result["passed"] is False
    assert result["original_passed"] is False


def _store(root: Path, kind: str, document: dict) -> str:
    content = replay.canonical_bytes(document)
    sha256 = replay.digest(content)
    folder = root / kind
    folder.mkdir(exist_ok=True)
    (folder / f"{sha256}.json.gz").write_bytes(gzip.compress(content, mtime=0))
    return sha256


def test_full_inventory_replay_retains_failures_and_reuses_artifact(
    matcher, tmp_path, monkeypatch
):
    original_input = {
        "official_source_commit": replay.SOURCE_COMMIT,
        "official_archive_sha256": replay.SUITE_SHA256,
        "cases_digest": replay.digest(replay.canonical_bytes(matcher.cases)),
        "declared_count": len(matcher.cases),
    }
    input_digest = _store(tmp_path, "input", original_input)
    monkeypatch.setattr(replay, "INPUT_SHA256", input_digest)
    for shard in range(4):
        refs = []
        for index, case in enumerate(matcher.cases):
            if index % 4 != shard:
                continue
            findings = [_finding("target")] * (2 if case["id"] == "expected" else 1)
            record = {
                "case": case,
                "index": index,
                "input_digest": input_digest,
                "passed": False,
                "success": True,
                "all_modules_completed": True,
                "returned_modules": list(replay.MODULES),
                "network_attempt_count": 0,
                "findings": findings,
            }
            refs.append(
                {
                    "index": index,
                    "case_id": case["id"],
                    "passed": False,
                    "digest": _store(tmp_path, "cases", record),
                }
            )
        _store(
            tmp_path,
            "shards",
            {
                "input_digest": input_digest,
                "sample_only": False,
                "shard_count": 4,
                "shard_index": shard,
                "network_attempt_count": 0,
                "cache_unchanged": True,
                "results": refs,
                "executed_count": len(refs),
                "passed_count": 0,
            },
        )
    monkeypatch.setattr(
        replay,
        "SHARD_SHA256",
        frozenset(
            path.name.removesuffix(".json.gz")
            for path in (tmp_path / "shards").glob("*.gz")
        ),
    )
    output = replay.audit(tmp_path, matcher)
    assert output["declared_count"] == 3
    assert output["execution_and_assertion_passed_count"] == 2
    assert output["remaining_failure_cases"] == ["valid"]
    assert all("original_record_digest" in row for row in output["rows"])
    assert not output["fresh_rule_execution"]
    assert not output["canonical_publication_approved"]
    report_dir = tmp_path / "reports"
    first = replay.write_report(report_dir, output)
    path = report_dir / f"{first['report_digest']}.json"
    before = path.stat().st_mtime_ns
    second = replay.write_report(report_dir, replay.audit(tmp_path, matcher))
    assert first["wrote"] and not second["wrote"]
    assert first["report_digest"] == second["report_digest"]
    assert path.stat().st_mtime_ns == before
    first_shard = next((tmp_path / "shards").glob("*.gz"))
    first_shard.unlink()
    with pytest.raises(ValueError, match="four unique shards"):
        replay.audit(tmp_path, matcher)


def test_corrupt_evidence_and_online_attempts_fail_closed(tmp_path):
    sha256 = _store(tmp_path, "cases", {"original": "evidence"})
    path = tmp_path / "cases" / f"{sha256}.json.gz"
    path.write_bytes(gzip.compress(b"{}", mtime=0))
    with pytest.raises(ValueError, match="digest/canonical"):
        replay.read_evidence(tmp_path, "cases", sha256)
    with replay.offline_attempts() as attempts:
        with pytest.raises(OSError, match="offline"):
            replay.socket.socket().connect(("127.0.0.1", 9))
    assert attempts == [1]
