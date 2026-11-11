from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from fundamental_service import history_replay_inputs as replay_inputs
from fundamental_service.contracts import SourceRole
from fundamental_service.history_mapping_audit import MappingAuditError
from fundamental_service.sec_source import SecEdgarSourceAdapter, SecSourceError
from fundamental_service.serialization import canonical_bytes, sha256_digest
from fundamental_service.snapshots import CapturedSource


SAMPLE_CIK = "0001539778"
DECISION = "0001477932-16-007985"
LABEL = "0001477932-17-000569"


def _raw(cik: str) -> dict[str, object]:
    facts = []
    for accession, year, value in (
        (DECISION, 2015, 731815),
        (LABEL, 2016, 1276883),
        (LABEL, 2015, 999999),
    ):
        facts.append(
            {
                "accn": accession,
                "form": "10-K",
                "start": f"{year - 1}-10-01",
                "end": f"{year}-09-30",
                "val": value,
                "fp": "FY",
            }
        )
    return {
        "cik": int(cik),
        "facts": {"us-gaap": {"Revenues": {"units": {"USD": facts}}}},
    }


def _install_source(
    monkeypatch: pytest.MonkeyPatch, calls: list[str], *, failed: str | None = None
) -> None:
    def capture(_self: SecEdgarSourceAdapter, cik: str) -> CapturedSource:
        calls.append(cik)
        if cik == failed:
            raise SecSourceError("SEC_HTTP_403", "fixture failure")
        return CapturedSource(
            source_id="sec-companyfacts",
            uri=f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json",
            role=SourceRole.FACTS,
            content=canonical_bytes(_raw(cik)),
            media_type="application/json",
            http_status=200,
            available_at=datetime(2026, 11, 10, tzinfo=UTC),
            captured_at=datetime(2026, 11, 10, tzinfo=UTC),
        )

    monkeypatch.setattr(SecEdgarSourceAdapter, "capture_company_facts", capture)
    monkeypatch.setenv("FUNDAMENTAL_SEC_USER_AGENT", "Fixture tests tests@example.com")


def _manifest_path(result: dict[str, object]) -> Path:
    manifest = replay_inputs._object(result["manifest"], "manifest result")
    return Path(replay_inputs._text(manifest["path"], "manifest path"))


def test_repeat_capture_makes_no_requests_or_replacements(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    _install_source(monkeypatch, calls)
    first = replay_inputs.capture_sources(output_directory=tmp_path)
    assert (
        first["selected_issuers"]
        == first["captured_issuers"]
        == first["downloads"]
        == 100
    )
    original = {path: path.read_bytes() for path in tmp_path.rglob("*.gz")}

    def reject_replace(*args: object) -> None:
        raise AssertionError("unchanged capture must not replace artifacts")

    monkeypatch.setattr(replay_inputs.os, "replace", reject_replace)
    repeat = replay_inputs.capture_sources(output_directory=tmp_path)

    assert repeat["downloads"] == 0
    assert repeat["wrote"] is False
    assert repeat["manifest"] == {
        **replay_inputs._object(first["manifest"], "manifest"),
        "wrote": False,
    }
    assert len(calls) == len(set(calls)) == 100
    assert original == {path: path.read_bytes() for path in original}


def test_resume_after_capture_before_manifest_does_not_download_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    _install_source(monkeypatch, calls)
    writer = replay_inputs._write_content_addressed

    def interrupt_manifest(*args: object) -> None:
        raise OSError("fixture interruption after durable source capture")

    monkeypatch.setattr(replay_inputs, "_write_content_addressed", interrupt_manifest)
    with pytest.raises(OSError, match="interruption"):
        replay_inputs.capture_sources(output_directory=tmp_path)
    monkeypatch.setattr(replay_inputs, "_write_content_addressed", writer)
    resumed = replay_inputs.capture_sources(output_directory=tmp_path)
    assert resumed["downloads"] == 0
    assert len(calls) == 100
    assert resumed["captured_issuers"] == 100


def test_review_package_retains_failure_without_retry_and_excludes_future_restatement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    failed_cik = "0000021344"
    _install_source(monkeypatch, calls, failed=failed_cik)
    result = replay_inputs.capture_sources(output_directory=tmp_path)
    assert result["captured_issuers"] == 99
    package = replay_inputs.build_review_package(
        source_manifest_path=_manifest_path(result)
    )
    repeat = replay_inputs.build_review_package(
        source_manifest_path=_manifest_path(result)
    )
    assert sha256_digest(package) == sha256_digest(repeat)
    assert package["supported_history_threshold"] is None
    assert package["approved_mapping_count"] == 0
    rows = [
        replay_inputs._object(row, "issuer")
        for row in replay_inputs._array(package["issuer_rows"], "issuers")
    ]
    assert len(rows) == 100
    assert rows == sorted(
        rows, key=lambda row: (str(row["decision_at"]), str(row["cik"]))
    )
    failed = next(row for row in rows if row["cik"] == failed_cik)
    assert (
        replay_inputs._object(failed["source_record"], "source")["failure_code"]
        == "SEC_HTTP_403"
    )
    assert all(
        replay_inputs._object(row, "field")["missing_reason"] == "SOURCE_CAPTURE_FAILED"
        for row in replay_inputs._array(failed["field_rows"], "fields")
    )
    sample = next(row for row in rows if row["cik"] == SAMPLE_CIK)
    assert sample["first_subsequent_original_accession"] == LABEL
    sample_fields = [
        replay_inputs._object(row, "field")
        for row in replay_inputs._array(sample["field_rows"], "fields")
    ]
    candidates = [
        replay_inputs._object(fact, "fact")
        for row in sample_fields
        for fact in replay_inputs._array(row["candidate_facts"], "candidates")
    ]
    assert {fact["value"] for fact in candidates} == {"731815", "1276883"}
    assert all(fact["source_fact_id"] is None for fact in candidates)
    assert all(fact["candidate_fact_id"] for fact in candidates)
    assert replay_inputs.capture_sources(output_directory=tmp_path)["downloads"] == 0
    assert len(calls) == 100


def test_candidate_audit_keeps_unit_duration_and_value_conflicts() -> None:
    raw = _raw(SAMPLE_CIK)
    concepts = replay_inputs._object(
        replay_inputs._object(raw["facts"], "facts")["us-gaap"], "concepts"
    )
    concepts["SalesRevenueNet"] = {
        "units": {
            "USD": [
                {
                    "accn": DECISION,
                    "form": "10-K",
                    "start": "2014-10-01",
                    "end": "2015-09-30",
                    "val": 123,
                },
                {
                    "accn": DECISION,
                    "form": "10-K",
                    "start": "invalid",
                    "end": "2015-09-30",
                    "val": 456,
                },
            ],
            "shares": [
                {
                    "accn": DECISION,
                    "form": "10-K",
                    "start": "2014-10-01",
                    "end": "2015-09-30",
                    "val": 789,
                },
            ],
        }
    }
    candidates = replay_inputs._field_candidates(
        raw,
        field="revenue",
        cik=SAMPLE_CIK,
        accession=DECISION,
        period_end=date(2015, 9, 30),
        source_hash="a" * 64,
        available_at="2016-01-12T19:35:54Z",
        duration=True,
        amendment=False,
    )
    assert len(candidates) == 4
    assert {row["value"] for row in candidates if not row["rejection_reasons"]} == {
        "731815",
        "123",
    }
    assert {
        reason
        for row in candidates
        for reason in replay_inputs._array(row["rejection_reasons"], "reasons")
    } == {"UNIT_MISMATCH", "INVALID_PERIOD_START"}


def test_review_writer_reuses_every_issuer_and_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    _install_source(monkeypatch, calls)
    sources = tmp_path / "sources"
    captured = replay_inputs.capture_sources(output_directory=sources)
    package = replay_inputs.build_review_package(
        source_manifest_path=_manifest_path(captured)
    )
    output = tmp_path / "review"
    first = replay_inputs.write_review_package(package, output)
    original = {path: path.read_bytes() for path in output.rglob("*.gz")}

    def reject_replace(*args: object) -> None:
        raise AssertionError("unchanged review must not replace artifacts")

    monkeypatch.setattr(replay_inputs.os, "replace", reject_replace)
    repeated = replay_inputs.write_review_package(package, output)
    assert first["wrote"] is True
    assert repeated["wrote"] is False
    assert first["input_digest"] == repeated["input_digest"]
    assert first["output_digest"] == repeated["output_digest"]
    assert len(original) == 101
    assert original == {path: path.read_bytes() for path in original}


def test_point_in_time_cover_shares_retain_dates_and_reject_future_instants() -> None:
    raw: dict[str, object] = {
        "facts": {
            "dei": {
                "EntityCommonStockSharesOutstanding": {
                    "units": {
                        "shares": [
                            {
                                "accn": DECISION,
                                "form": "10-K",
                                "end": "2016-01-10",
                                "val": 1000,
                            },
                            {
                                "accn": DECISION,
                                "form": "10-K",
                                "end": "2017-01-10",
                                "val": 2000,
                            },
                        ]
                    }
                }
            }
        }
    }
    candidates = replay_inputs._field_candidates(
        raw,
        field="common_shares_outstanding",
        cik=SAMPLE_CIK,
        accession=DECISION,
        period_end=date(2015, 9, 30),
        source_hash="a" * 64,
        available_at="2016-01-12T19:35:54Z",
        duration=False,
        amendment=False,
        point_in_time=True,
    )
    assert len(candidates) == 2
    eligible = [row for row in candidates if not row["rejection_reasons"]]
    assert [(row["value"], row["period_end"], row["concept"]) for row in eligible] == [
        ("1000", "2016-01-10", "dei:EntityCommonStockSharesOutstanding")
    ]
    assert next(row for row in candidates if row["value"] == "2000")[
        "rejection_reasons"
    ] == ["FUTURE_INSTANT"]


def test_stored_source_tampering_is_rejected_without_redownload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    _install_source(monkeypatch, calls)
    result = replay_inputs.capture_sources(output_directory=tmp_path)
    package = replay_inputs.build_review_package(
        source_manifest_path=_manifest_path(result)
    )
    issuer = replay_inputs._object(
        replay_inputs._array(package["issuer_rows"], "issuers")[0], "issuer"
    )
    source = replay_inputs._object(issuer["source_record"], "source")
    index = tmp_path / "source_index" / f"{source['source_key']}.bundle.gz"
    index.write_bytes(b"not gzip")
    with pytest.raises((OSError, MappingAuditError)):
        replay_inputs.build_review_package(source_manifest_path=_manifest_path(result))
    assert len(calls) == 100
