import hashlib
import json
import socket
from pathlib import Path
from zipfile import ZipFile

import pytest

from fundamental_service.arelle_parser import (
    ArelleParserError,
    ArelleValidationProfileV1,
    parse_filing_offline,
)


def test_pinned_arelle_parses_captured_xbrl_without_network():
    report = parse_filing_offline(
        Path(__file__).parent / "fixtures" / "simple.xbrl",
        profile=ArelleValidationProfileV1(profile_id="sec-efm-us-gaap-v1"),
        taxonomy_version="fixture-taxonomy-v1",
    )
    assert report.offline is True
    assert report.parser_version == "2.47.4"
    assert any(fact.concept.endswith("Revenue") for fact in report.facts)


def test_parser_rejects_non_offline_profile():
    with pytest.raises(ValueError, match="offline=true"):
        ArelleValidationProfileV1(profile_id="sec-efm-us-gaap-v1", offline=False)


def test_captured_sec_filing_rebuilds_with_pinned_taxonomy_cache_without_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    fixture_root = Path(__file__).parent / "fixtures" / "sec-edgar"
    filing_dir = tmp_path / "filing"
    taxonomy_dir = tmp_path / "taxonomy"
    filing_dir.mkdir()
    taxonomy_dir.mkdir()
    (filing_dir / "aapl-20240928.htm").write_bytes(
        (fixture_root / "apple-2024-original-aapl-20240928.htm").read_bytes()
    )
    with ZipFile(
        fixture_root / "apple-2024-original-0000320193-24-000123-xbrl.zip"
    ) as archive:
        for filename in (
            "aapl-20240928.xsd",
            "aapl-20240928_pre.xml",
            "aapl-20240928_def.xml",
            "aapl-20240928_lab.xml",
            "aapl-20240928_cal.xml",
        ):
            (filing_dir / filename).write_bytes(archive.read(filename))
    with ZipFile(fixture_root / "arelle-taxonomy-cache-2024.zip") as archive:
        archive.extractall(taxonomy_dir)

    attempted_network: list[object] = []

    def blocked_network(*args: object, **kwargs: object) -> None:
        attempted_network.append((args, kwargs))
        raise AssertionError("offline SEC rebuild attempted network access")

    monkeypatch.setattr(socket.socket, "connect", blocked_network)
    report = parse_filing_offline(
        filing_dir / "aapl-20240928.htm",
        profile=ArelleValidationProfileV1(profile_id="sec-efm-us-gaap-v1"),
        taxonomy_version="us-gaap-2024",
        taxonomy_cache_dir=taxonomy_dir,
        source_content_hash=hashlib.sha256(
            (fixture_root / "apple-2024-original-aapl-20240928.htm").read_bytes()
        ).hexdigest(),
    )
    assert report.offline is True
    assert len(report.facts) >= 1000
    assert any(
        fact.concept == "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"
        and fact.value == "391035000000"
        and fact.period_end is not None
        for fact in report.facts
    )
    assert report.finding_codes
    assert attempted_network == []


def test_sec_capture_manifest_has_verified_hashes_and_amendment_metadata():
    fixture_root = Path(__file__).parent / "fixtures" / "sec-edgar"
    manifest = json.loads((fixture_root / "capture_manifest.json").read_text())
    assert manifest["parser_version"] == "arelle-release==2.47.4"
    assert manifest["sec_user_agent_identifiable"] is True
    records = {record["path"]: record for record in manifest["sources"]}
    for path, record in records.items():
        assert (
            hashlib.sha256((fixture_root / path).read_bytes()).hexdigest()
            == record["sha256"]
        )
        assert record["http_status"] == 200
    amendment = next(record for record in records.values() if record["is_amendment"])
    assert amendment["form"] == "10-K/A"
    assert amendment["amends_accession"] == "0001628280-25-003063"


def test_missing_filing_fails_explicitly(tmp_path: Path):
    with pytest.raises(ArelleParserError) as error:
        parse_filing_offline(
            tmp_path / "missing.xbrl",
            profile=ArelleValidationProfileV1(profile_id="sec-efm-us-gaap-v1"),
            taxonomy_version="fixture-taxonomy-v1",
        )
    assert error.value.code == "FILING_BYTES_UNAVAILABLE"


def test_parser_rejects_source_hash_mismatch():
    with pytest.raises(ArelleParserError) as error:
        parse_filing_offline(
            Path(__file__).parent / "fixtures" / "simple.xbrl",
            profile=ArelleValidationProfileV1(profile_id="sec-efm-us-gaap-v1"),
            taxonomy_version="fixture-taxonomy-v1",
            source_content_hash="0" * 64,
        )
    assert error.value.code == "SOURCE_HASH_MISMATCH"
