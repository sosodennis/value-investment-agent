import hashlib
import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from fundamental_service import history_cohort
from fundamental_service.history_sufficiency_report import Fact, Filing
from fundamental_service.sec_source import SecSourceError


def test_sec_frame_reconstructs_the_fixed_stratified_sample():
    frame = history_cohort.load_frame()
    first = history_cohort.select_sample(frame)
    second = history_cohort.select_sample(history_cohort.load_frame())
    selected_ciks = [row["cik"] for row in first["selected"]]

    assert len(frame["eligible"]) == 3999
    assert len(frame["excluded"]) == 1339
    assert len(selected_ciks) == 100
    assert len(set(selected_ciks)) == 100
    assert first == second
    assert first["sample_by_stratum"] == {
        "agriculture": 1,
        "construction": 2,
        "finance_real_estate": 28,
        "manufacturing": 30,
        "mining": 6,
        "public_administration": 1,
        "retail": 5,
        "services": 15,
        "transport_utilities": 8,
        "unclassified": 1,
        "wholesale": 3,
    }
    assert (
        hashlib.sha256(("\n".join(selected_ciks) + "\n").encode()).hexdigest()
        == "454fb8ec403b38cdaf3aa49072aaa030bd23d8c8a77b28b051d46724ab0c1da9"
    )


def test_stratum_allocation_respects_a_small_stratum_capacity():
    assert history_cohort._stratum_allocation({"rare": 1, "large": 100}, 50) == {
        "large": 49,
        "rare": 1,
    }


def _annual_filing(year: int, accession: str, form: str = "10-K") -> Filing:
    return Filing(
        issuer_id="CIK:0000000001",
        accession=accession,
        form=form,
        period_end=date(year, 12, 31),
        accepted_at=datetime(year + 1, 2, 1, 12, tzinfo=UTC),
    )


def test_measurement_uses_exact_acceptance_time_and_next_original_accession():
    filings = tuple(_annual_filing(year, str(year)) for year in range(2018, 2023))
    decision = filings[-1]
    amendment = _annual_filing(2023, "2023-amendment", "10-K/A")
    following = _annual_filing(2023, "2023-original")
    filings = (*filings, amendment, following)
    facts = []
    for filing in filings[:5]:
        facts.append(
            Fact(
                "revenue",
                filing.accession,
                filing.period_end,
                filing.accepted_at,
                str(filing.period_end.year * 100),
                date(filing.period_end.year, 1, 1),
            )
        )
    facts.extend(
        (
            Fact(
                "revenue",
                "2022-restated-later",
                decision.period_end,
                decision.accepted_at + timedelta(microseconds=1),
                "999999",
                date(2022, 1, 1),
            ),
            Fact(
                "revenue",
                amendment.accession,
                following.period_end,
                amendment.accepted_at,
                "999999",
                date(2023, 1, 1),
            ),
            Fact(
                "revenue",
                following.accession,
                following.period_end,
                following.accepted_at,
                "202300",
                date(2023, 1, 1),
            ),
        )
    )

    result = history_cohort._measure_decision(
        "fcff_dcf", ("revenue",), decision, filings, tuple(facts)
    )
    history_facts = [
        row for row in result["fact_catalog"] if row["period_end"] == "2022-12-31"
    ]
    label = next(
        row
        for row in result["fact_catalog"]
        if row["source_accession"] == following.accession
    )

    assert result["valuation_timestamp"] == "2023-02-01T12:00:00Z"
    assert result["complete_history_periods"] == 5
    assert result["candidate_rule_passes"] is True
    assert result["next_original_filing_accession"] == "2023-original"
    assert [row["source_accession"] for row in history_facts] == ["2022"]
    assert label["value"] == "202300"
    assert all(
        row["source_accession"] not in {"2022-restated-later", "2023-amendment"}
        for row in result["fact_catalog"]
    )


class _FakeAdapter:
    def __init__(self, failing_cik: str):
        self.failing_cik = failing_cik

    def _source(self, source_id: str, uri: str, payload: dict[str, object]):
        content = json.dumps(payload).encode()
        return SimpleNamespace(
            source_id=source_id,
            uri=uri,
            content=content,
            http_status=200,
            available_at=datetime(2026, 11, 9, tzinfo=UTC),
            captured_at=datetime(2026, 11, 9, tzinfo=UTC),
            response_headers=(),
        )

    def capture_submissions(self, cik: str):
        if cik == self.failing_cik:
            raise SecSourceError("SOURCE_UNAVAILABLE", "fixture request failure")
        return self._source(
            "sec-submissions",
            f"https://data.sec.gov/submissions/CIK{cik}.json",
            {
                "cik": cik,
                "filings": {
                    "recent": {
                        "form": ["10-K"],
                        "accessionNumber": [f"{cik}-16-000001"],
                        "filingDate": ["2016-03-01"],
                        "reportDate": ["2015-12-31"],
                        "acceptanceDateTime": ["2016-03-01T10:00:00Z"],
                    },
                    "files": [],
                },
            },
        )

    def capture_company_facts(self, cik: str):
        return self._source(
            "sec-companyfacts",
            f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json",
            {"cik": cik, "entityName": "Fixture Issuer", "facts": {"us-gaap": {}}},
        )


@pytest.mark.parametrize(
    ("archive_cik", "archived_payload_cik", "expected_status"),
    (
        ("0000000001", None, "captured"),
        ("0000000001", "0000000001", "captured"),
        ("0000000002", None, "snapshot_invalid"),
        ("0000000001", "0000000002", "snapshot_invalid"),
    ),
)
def test_capture_validates_archived_submission_identity_from_filename_and_payload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    archive_cik: str,
    archived_payload_cik: str | None,
    expected_status: str,
):
    cik = "0000000001"

    class ArchiveAdapter(_FakeAdapter):
        def __init__(self):
            super().__init__(failing_cik="")

        def capture_submissions(self, requested_cik: str):
            source = super().capture_submissions(requested_cik)
            payload = json.loads(source.content)
            payload["filings"]["files"] = [
                {
                    "name": f"CIK{archive_cik}-submissions-2015.json",
                    "filingTo": "2015-12-31",
                }
            ]
            return self._source(source.source_id, source.uri, payload)

        def capture_json(self, source_id: str, uri: str):
            payload = {
                "filings": {
                    "recent": {
                        "form": [],
                        "accessionNumber": [],
                        "filingDate": [],
                        "reportDate": [],
                        "acceptanceDateTime": [],
                    }
                }
            }
            if archived_payload_cik is not None:
                payload["cik"] = archived_payload_cik
            return self._source(
                source_id,
                uri,
                payload,
            )

    protocol_path = tmp_path / "protocol.json"
    protocol_path.write_text(json.dumps({"scope": "fixture"}), encoding="utf-8")
    frame_path = tmp_path / "frame.json"
    frame_path.write_text("{}", encoding="utf-8")
    capture_path = tmp_path / "cohort" / "capture_manifest.json"
    selected = (
        {
            "cik": cik,
            "issuer_id": f"CIK:{cik}",
            "decision_accession": f"{cik}-16-000001",
            "stratum": "manufacturing",
            "sample_rank": 1,
            "selection_digest": "fixture-selection",
        },
    )
    frame = {
        "sample_size": 1,
        "sample_seed": "fixture-seed",
        "protocol_sha256": "protocol-hash",
        "frame_manifest_sha256": "frame-hash",
        "eligible": [{"cik": cik}],
        "excluded": [],
        "frame_counts": {"fixture": 1},
    }
    sample = {
        "selected": selected,
        "population_by_stratum": {"manufacturing": 1},
        "sample_by_stratum": {"manufacturing": 1},
    }
    monkeypatch.setattr(history_cohort, "load_frame", lambda *args, **kwargs: frame)
    monkeypatch.setattr(history_cohort, "select_sample", lambda _frame: sample)

    result = history_cohort.capture_cohort(
        protocol_path=protocol_path,
        frame_manifest_path=frame_path,
        capture_manifest_path=capture_path,
        adapter=ArchiveAdapter(),
        root=tmp_path,
    )

    assert result["issuers"][0]["capture_status"] == expected_status
    assert result["issuers"][0]["failure_code"] == (
        None if expected_status == "captured" else "INVALID_SOURCE_SNAPSHOT"
    )


def test_capture_failure_keeps_the_preselected_issuer_in_report_denominator(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    protocol_path = tmp_path / "protocol.json"
    protocol_path.write_text(json.dumps({"scope": "fixture"}), encoding="utf-8")
    frame_path = tmp_path / "frame.json"
    frame_path.write_text("{}", encoding="utf-8")
    capture_path = tmp_path / "capture_manifest.json"
    selected = tuple(
        {
            "cik": cik,
            "issuer_id": f"CIK:{cik}",
            "decision_accession": f"{cik}-16-000001",
            "stratum": "manufacturing",
            "sample_rank": position,
            "selection_digest": str(position),
        }
        for position, cik in enumerate(("0000000001", "0000000002"), start=1)
    )
    frame = {
        "protocol_scope": "fixture",
        "sample_size": 2,
        "sample_seed": "fixture-seed",
        "protocol_sha256": "protocol-hash",
        "frame_manifest_sha256": "frame-hash",
        "eligible": [{"cik": cik} for cik in ("0000000001", "0000000002")],
        "excluded": [],
        "frame_counts": {"fixture": 2},
    }
    sample = {
        "selected": selected,
        "population_by_stratum": {"manufacturing": 2},
        "sample_by_stratum": {"manufacturing": 2},
    }
    monkeypatch.setattr(history_cohort, "load_frame", lambda *args, **kwargs: frame)
    monkeypatch.setattr(history_cohort, "select_sample", lambda _frame: sample)

    capture = history_cohort.capture_cohort(
        protocol_path=protocol_path,
        frame_manifest_path=frame_path,
        capture_manifest_path=capture_path,
        adapter=_FakeAdapter("0000000002"),
        root=tmp_path,
    )
    report = history_cohort.build_cohort_report(capture_path, root=tmp_path)
    report_path = tmp_path / "report.json"

    assert [row["cik"] for row in capture["issuers"]] == [
        "0000000001",
        "0000000002",
    ]
    assert [row["capture_status"] for row in capture["issuers"]] == [
        "captured",
        "retrieval_failed",
    ]
    assert report["sampling"]["selected_issuer_clusters"] == 2
    assert report["sampling"]["eligible_issuer_clusters"] == 2
    assert report["sampling"]["excluded_issuer_clusters"] == 0
    assert report["models"]["fcff_dcf"]["issuer_clusters_in_denominator"] == 2
    assert report["issuer_rows"][1]["row_status"] == "excluded_from_measurement"
    assert report["threshold_decision"]["status"] == "underpowered"
    assert "Search results and LLM-extracted values" in report["source_exclusions"]
    assert history_cohort.write_report(report, report_path) is True
    first_bytes = report_path.read_bytes()
    assert history_cohort.write_report(report, report_path) is False
    assert report_path.read_bytes() == first_bytes
