"""Historical SEC submission shards must establish the proxy lookup window."""

import json
from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from fundamental_service.operations import ServiceError
from fundamental_service.replay import ArtifactStore
from fundamental_service.sec_source import (
    SecEdgarSourceAdapter,
    SecRequestPolicy,
    _SecResponse,
)
from fundamental_service.serialization import canonical_bytes
from fundamental_service.snapshots import FilesystemContentStore
from fundamental_service.source_acquisition import SecAcquisitionUseCase
from fundamental_service.sec_submissions import SecSubmissionsV1

CIK = "0000320193"
FILENAME = f"CIK{CIK}-submissions-001.json"
AT = datetime(2026, 11, 13, tzinfo=UTC)
ANNUAL = "0000320193-26-000123"
PROXY = "0000320193-26-000010"


def rows(*, accession=PROXY, form="DEF 14A", document="proxy.htm", day="2026-04-01"):
    return {
        "accessionNumber": [accession],
        "filingDate": [day],
        "acceptanceDateTime": [day + "T12:00:00Z"],
        "form": [form],
        "primaryDocument": [document],
        "isXBRL": [0],
    }


def setup_case(tmp_path, *, files=True, mutate=None):
    reference = {
        "name": FILENAME,
        "filingCount": 1,
        "filingFrom": "2026-04-01",
        "filingTo": "2026-04-01",
    }
    filings = {
        "recent": rows(
            accession=ANNUAL, form="10-K", document="annual.htm", day="2026-10-01"
        )
    }
    if files:
        filings["files"] = [reference]
    data = {"cik": CIK, "filings": filings}
    history = rows()
    if mutate:
        mutate(data, history)
    calls = []

    class Provider(SecEdgarSourceAdapter):
        def _request(self, uri, *, deadline_at=None):
            calls.append(uri)
            if uri.endswith(FILENAME):
                value, media = canonical_bytes(history), "application/json"
            elif uri.endswith("/index.json"):
                value, media = (
                    canonical_bytes(
                        {"directory": {"item": [{"name": "proxy.htm", "size": 10}]}}
                    ),
                    "application/json",
                )
            else:
                value, media = b"<html>proxy</html>", "text/html"
            return _SecResponse(value, 200, media, AT, (), len(value))

    use_case = object.__new__(SecAcquisitionUseCase)
    use_case.adapter = Provider(
        SecRequestPolicy(user_agent="proxy-test test@example.com")
    )
    use_case.capture_store = ArtifactStore(tmp_path / "artifacts")
    use_case.content_store = FilesystemContentStore(tmp_path / "content")
    use_case._capture_lock = lambda _: nullcontext()
    request = SimpleNamespace(
        cik=CIK,
        valuation_timestamp=AT,
        source_selection_policy="sec-pit-v1",
        supplemental_filing_policy="sec-equity-award-proxy.v2",
    )
    return use_case, request, SecSubmissionsV1.model_validate(data), calls


def capture(use_case, request, submissions):
    return use_case._capture_award_proxy_sources(
        request,
        submissions,
        annual_accession=ANNUAL,
        deadline_at=datetime.now(UTC) + timedelta(minutes=1),
    )


def inventory(root):
    return {
        str(p.relative_to(root)): (p.read_bytes(), p.stat().st_mtime_ns)
        for p in root.rglob("*")
        if p.is_file()
    }


def test_historical_proxy_original_is_retained_and_restart_writes_nothing(tmp_path):
    use_case, request, submissions, calls = setup_case(tmp_path)
    first, issues = capture(use_case, request, submissions)
    assert not issues
    assert [source.source_id for source in first] == [
        "sec-submissions-history",
        "sec-supplemental-filing-index",
        "sec-supplemental-filing",
    ]
    assert first[-1].accession_number == PROXY
    before = inventory(tmp_path)
    restarted, _, _, _ = setup_case(tmp_path)
    restarted.adapter = use_case.adapter
    second, second_issues = capture(restarted, request, submissions)
    assert second == first and second_issues == issues
    assert len(calls) == 3
    assert inventory(tmp_path) == before


def test_recent_window_cannot_imply_absence_without_history_index(tmp_path):
    use_case, request, submissions, calls = setup_case(tmp_path, files=False)
    with pytest.raises(ServiceError) as error:
        capture(use_case, request, submissions)
    assert error.value.code == "EQUITY_AWARD_PROXY_HISTORY_INCOMPLETE"
    assert calls == []


@pytest.mark.parametrize("change", ["count", "range", "length", "duplicate"])
def test_invalid_history_is_retained_and_refuses_before_proxy_download(
    tmp_path, change
):
    def mutate(data, history):
        if change == "count":
            data["filings"]["files"][0]["filingCount"] = 2
        elif change == "range":
            data["filings"]["files"][0]["filingFrom"] = "2026-03-01"
        elif change == "length":
            history["form"] = []
        else:
            for values in history.values():
                values.extend(values)
            data["filings"]["files"][0]["filingCount"] = 2

    use_case, request, submissions, calls = setup_case(tmp_path, mutate=mutate)
    with pytest.raises(ServiceError) as first:
        capture(use_case, request, submissions)
    before = inventory(tmp_path)
    with pytest.raises(ServiceError) as again:
        capture(use_case, request, submissions)
    assert (
        first.value.code == again.value.code == "EQUITY_AWARD_PROXY_HISTORY_INCOMPLETE"
    )
    assert len(calls) == 1 and inventory(tmp_path) == before
    assert any(
        json.loads(p.read_bytes()).get("uri", "").endswith(FILENAME)
        for p in (tmp_path / "artifacts").rglob("*.artifact")
    )


def test_foreign_history_filename_is_rejected_without_io(tmp_path):
    def mutate(data, _):
        data["filings"]["files"][0]["name"] = "CIK0000000001-submissions-001.json"

    use_case, request, submissions, calls = setup_case(tmp_path, mutate=mutate)
    with pytest.raises(ServiceError) as error:
        capture(use_case, request, submissions)
    assert error.value.code == "SOURCE_PAYLOAD_INVALID" and calls == []


def test_overlapping_history_accession_conflict_is_not_silently_deduplicated(tmp_path):
    def mutate(data, _):
        data["filings"]["recent"] = rows(document="conflicting.htm")

    use_case, request, submissions, _ = setup_case(tmp_path, mutate=mutate)
    with pytest.raises(ServiceError) as error:
        capture(use_case, request, submissions)
    assert error.value.code == "FILING_METADATA_CONFLICT"


def test_outside_window_proxy_without_acceptance_time_does_not_break_lookup(tmp_path):
    def mutate(data, _):
        data["filings"]["recent"] = rows(day="1995-01-01")
        data["filings"]["recent"]["acceptanceDateTime"] = [None]

    use_case, request, submissions, _ = setup_case(tmp_path, mutate=mutate)
    sources, issues = capture(use_case, request, submissions)
    assert not issues and sources[-1].accession_number == PROXY


def test_unrelated_historical_shard_is_not_downloaded(tmp_path):
    def mutate(data, _):
        data["filings"]["files"][0].update(
            filingFrom="2000-01-01", filingTo="2000-01-01"
        )

    use_case, request, submissions, calls = setup_case(tmp_path, mutate=mutate)
    sources, issues = capture(use_case, request, submissions)
    assert sources == () and calls == []
    assert [issue.code for issue in issues] == ["EQUITY_AWARD_PROXY_UNAVAILABLE"]
