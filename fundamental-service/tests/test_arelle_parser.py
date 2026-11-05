import hashlib
import json
import os
import socket
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zipfile import ZipFile

import pytest
from fundamental_service.arelle_parser import (
    ArelleFindingV1,
    ArelleParseReportV1,
    ArelleParserError,
    ArelleValidationProfileV1,
    _directory_hash,
    _dqc_validation_completed,
    _unlogged_model_error_findings,
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


def test_parser_uses_deadline_worker_for_isolated_replay():
    report = parse_filing_offline(
        Path(__file__).parent / "fixtures" / "simple.xbrl",
        profile=ArelleValidationProfileV1(profile_id="sec-efm-us-gaap-v1"),
        taxonomy_version="fixture-taxonomy-v1",
        deadline_at=datetime.now(timezone.utc) + timedelta(seconds=30),
    )
    assert report.offline is True
    assert any(fact.concept.endswith("Revenue") for fact in report.facts)


def test_apple_sec_efm_dqc_replay_with_pinned_runtime(
    tmp_path: Path,
):
    required_environment = (
        "ISSUE312_EDGAR_PLUGIN_DIR",
        "ISSUE312_XULE_PLUGIN_DIR",
        "ISSUE312_DQC_RULESET_PATH",
        "ISSUE312_TAXONOMY_CACHE_DIR",
    )
    if not all(os.environ.get(name) for name in required_environment):
        pytest.skip("pinned SEC EFM/DQC runtime paths are not configured")

    fixture_root = Path(__file__).parent / "fixtures" / "sec-edgar"
    filing_dir = tmp_path / "filing"
    filing_dir.mkdir()
    filing_path = filing_dir / "aapl-20240928.htm"
    filing_path.write_bytes(
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

    edgar_plugin_dir = Path(os.environ["ISSUE312_EDGAR_PLUGIN_DIR"])
    xule_plugin_dir = Path(os.environ["ISSUE312_XULE_PLUGIN_DIR"])
    ruleset_path = Path(os.environ["ISSUE312_DQC_RULESET_PATH"])
    report = parse_filing_offline(
        filing_path,
        profile=ArelleValidationProfileV1(
            profile_id="sec-efm-dqc-us-gaap-2024-v1",
            validation_mode="sec-efm-dqc",
            edgar_plugin_dir=edgar_plugin_dir,
            xule_plugin_dir=xule_plugin_dir,
            dqc_ruleset_path=ruleset_path,
            edgar_plugin_sha256=_directory_hash(edgar_plugin_dir),
            xule_plugin_sha256=_directory_hash(xule_plugin_dir),
            dqc_ruleset_sha256=hashlib.sha256(ruleset_path.read_bytes()).hexdigest(),
        ),
        taxonomy_version="us-gaap-2024",
        taxonomy_cache_dir=Path(os.environ["ISSUE312_TAXONOMY_CACHE_DIR"]),
        source_content_hash=hashlib.sha256(filing_path.read_bytes()).hexdigest(),
        deadline_at=datetime.now(timezone.utc) + timedelta(minutes=5),
    )

    assert len(report.facts) >= 1000
    assert report.validation_engines == ("sec-efm", "dqc-us")
    assert report.validation_evidence == (
        "strict-sec-efm-profile-selected",
        "dqc-dqcrt-checks-completed",
    )
    assert "EFM.5.02.05.disallowedElement" in report.blocking_finding_codes()


def test_microsoft_sec_efm_dqc_replay_uses_canonical_sec_archive_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    required_environment = (
        "ISSUE312_EDGAR_PLUGIN_DIR",
        "ISSUE312_XULE_PLUGIN_DIR",
        "ISSUE312_DQC_RULESET_PATH",
        "ISSUE312_TAXONOMY_CACHE_DIR",
    )
    if not all(os.environ.get(name) for name in required_environment):
        pytest.skip("pinned SEC EFM/DQC runtime paths are not configured")

    fixture_root = Path(__file__).parent / "fixtures" / "sec-edgar"
    archive_path = fixture_root / "microsoft-2024-original-xbrl-test-package.zip"
    filing_dir = tmp_path / "filing"
    filing_dir.mkdir()
    with ZipFile(archive_path) as archive:
        filing_path = filing_dir / "msft-20240630.htm"
        filing_path.write_bytes(archive.read("msft-20240630.htm"))
        (filing_dir / "msft-20240630.xsd").write_bytes(
            archive.read("msft-20240630.xsd")
        )

    attempted_network: list[object] = []

    def blocked_network(*args: object, **kwargs: object) -> None:
        attempted_network.append((args, kwargs))
        raise AssertionError("offline SEC replay attempted network access")

    monkeypatch.setattr(socket.socket, "connect", blocked_network)
    edgar_plugin_dir = Path(os.environ["ISSUE312_EDGAR_PLUGIN_DIR"])
    xule_plugin_dir = Path(os.environ["ISSUE312_XULE_PLUGIN_DIR"])
    ruleset_path = Path(os.environ["ISSUE312_DQC_RULESET_PATH"])
    report = parse_filing_offline(
        filing_path,
        profile=ArelleValidationProfileV1(
            profile_id="sec-efm-dqc-us-gaap-2023-2024-v1",
            validation_mode="sec-efm-dqc",
            edgar_plugin_dir=edgar_plugin_dir,
            xule_plugin_dir=xule_plugin_dir,
            dqc_ruleset_path=ruleset_path,
            edgar_plugin_sha256=_directory_hash(edgar_plugin_dir),
            xule_plugin_sha256=_directory_hash(xule_plugin_dir),
            dqc_ruleset_sha256=hashlib.sha256(ruleset_path.read_bytes()).hexdigest(),
        ),
        taxonomy_version="us-gaap-2023-2024",
        taxonomy_cache_dir=Path(os.environ["ISSUE312_TAXONOMY_CACHE_DIR"]),
        source_content_hash=hashlib.sha256(filing_path.read_bytes()).hexdigest(),
    )

    assert len(report.facts) >= 1800
    assert report.validation_engines == ("sec-efm", "dqc-us")
    assert report.validation_evidence == (
        "strict-sec-efm-profile-selected",
        "dqc-dqcrt-checks-completed",
    )
    assert report.blocking_finding_codes() == ()
    assert report.taxonomy_version == "us-gaap-2023-2024"
    assert attempted_network == []


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


def test_unlogged_model_errors_remain_blocking_except_known_transform_diagnostics():
    profile = ArelleValidationProfileV1(profile_id="sec-efm-us-gaap-v1")
    findings = _unlogged_model_error_findings(
        (
            "ix11.10.1.2:invalidTransformation",
            "xbrl:unknownBlockingModelError",
        ),
        logged_codes=set(),
    )
    report = ArelleParseReportV1(
        filing_path="fixture.xbrl",
        parser_version=profile.arelle_version,
        taxonomy_version="fixture-taxonomy-v1",
        validation_profile=profile,
        validation_profile_digest=profile.digest(),
        findings=findings,
        parsed_at=datetime.now(timezone.utc),
    )

    assert report.blocking_finding_codes() == ("xbrl:unknownBlockingModelError",)
    assert {finding.code: finding.severity for finding in findings} == {
        "ix11.10.1.2:invalidTransformation": "warning",
        "xbrl:unknownBlockingModelError": "error",
    }


def test_dqc_completion_requires_a_dqc_finding_or_dqcrt_activity():
    class Handler:
        @staticmethod
        def recordToJson(record: dict[str, object]) -> dict[str, object]:
            return record

    assert not _dqc_validation_completed(
        Handler(),
        (
            {
                "code": "info:profileActivity",
                "message": {"args": {"activity": "... validateDTS"}},
            },
        ),
    )
    assert _dqc_validation_completed(
        Handler(),
        (
            {
                "code": "info:profileActivity",
                "message": {"args": {"activity": "... DQCRT checks"}},
            },
        ),
    )


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
    for fixture in manifest["test_fixtures"]:
        assert (
            hashlib.sha256((fixture_root / fixture["path"]).read_bytes()).hexdigest()
            == fixture["sha256"]
        )
    microsoft_capture = manifest["external_public_evidence"][0]
    assert microsoft_capture["sha256"] == (
        "5a7653632f53c2529c4da82d25043fc52f05bfbe536837345aa5904560d92a82"
    )
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
