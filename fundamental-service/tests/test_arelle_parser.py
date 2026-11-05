import hashlib
import json
import socket
from datetime import date, datetime, timezone
from pathlib import Path
from zipfile import ZipFile

import pytest

from fundamental_service.arelle_parser import (
    ArelleFindingV1,
    ArelleParserError,
    ArelleParseReportV1,
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


def test_known_inline_transform_diagnostics_do_not_hide_other_blocking_findings():
    profile = ArelleValidationProfileV1(profile_id="sec-efm-us-gaap-v1")
    report = ArelleParseReportV1(
        filing_path="fixture.xbrl",
        parser_version=profile.arelle_version,
        taxonomy_version="fixture-taxonomy-v1",
        validation_profile=profile,
        validation_profile_digest=profile.digest(),
        findings=(
            ArelleFindingV1(
                code="ix11.10.1.2:invalidTransformation",
                severity="error",
                message="invalid transformation",
            ),
            ArelleFindingV1(
                code="ix11.11.1.2:invalidTransformation",
                severity="error",
                message="invalid transformation",
            ),
            ArelleFindingV1(
                code="EFM.5.02.05.disallowedElement",
                severity="error",
                message="disallowed inline element",
            ),
        ),
        parsed_at=datetime.now(timezone.utc),
    )

    assert report.blocking_finding_codes() == ("EFM.5.02.05.disallowedElement",)


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
    company_facts = json.loads((fixture_root / "apple-companyfacts.json").read_text())
    for concept in ("Assets", "Liabilities", "StockholdersEquity"):
        expected_records = [
            (unit, record)
            for unit, records in company_facts["facts"]["us-gaap"][concept][
                "units"
            ].items()
            for record in records
            if record["accn"] == "0000320193-24-000123" and "start" not in record
        ]
        assert len({record["end"] for _, record in expected_records}) >= 2
        for unit, record in expected_records:
            parsed_facts = [
                fact
                for fact in report.facts
                if fact.concept == f"us-gaap:{concept}"
                and fact.value == str(record["val"])
                and fact.unit == f"iso4217:{unit}"
                and not fact.dimensions
            ]
            assert parsed_facts
            assert {fact.instant for fact in parsed_facts} == {
                date.fromisoformat(record["end"])
            }
            assert all(fact.context_id for fact in parsed_facts)
    assert report.validation_profile_digest == report.validation_profile.digest()
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
