import hashlib
import json
import os
import queue
import socket
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zipfile import ZipFile

import pytest
from fundamental_service.arelle_parser import (
    ArelleFindingV1,
    ArelleParseReportV1,
    ArelleParserError,
    ArelleValidationFailureV1,
    ArelleValidationProfileV1,
    ParserResourcePolicy,
    _directory_hash,
    _dqc_validation_completed,
    _finding_from_log,
    _missing_dqc_error,
    _parser_slot,
    _unlogged_model_error_findings,
    fact_semantic_digest,
    parse_filing_offline,
)
from fundamental_service.contracts import SourceRole
from fundamental_service.sec_integrity import assess_filing_response
from fundamental_service.snapshots import CapturedSource


def _configured_sec_profile() -> tuple[ArelleValidationProfileV1, Path]:
    required = (
        "ISSUE328_EDGAR_PLUGIN_DIR",
        "ISSUE328_XULE_PLUGIN_DIR",
        "ISSUE328_DQC_RULESET_PATH",
        "ISSUE328_TAXONOMY_CACHE_DIR",
    )
    if not all(os.environ.get(name) for name in required):
        pytest.skip("pinned SEC EFM/DQC runtime paths are not configured")
    edgar = Path(os.environ["ISSUE328_EDGAR_PLUGIN_DIR"])
    xule = Path(os.environ["ISSUE328_XULE_PLUGIN_DIR"])
    dqc = Path(os.environ["ISSUE328_DQC_RULESET_PATH"])
    profile = ArelleValidationProfileV1(
        profile_id="sec-efm-dqc-us-gaap-2024-v1",
        validation_mode="sec-efm-dqc",
        edgar_plugin_dir=edgar,
        xule_plugin_dir=xule,
        dqc_ruleset_path=dqc,
        edgar_plugin_sha256=_directory_hash(edgar),
        xule_plugin_sha256=_directory_hash(xule),
        dqc_ruleset_sha256=hashlib.sha256(dqc.read_bytes()).hexdigest(),
    )
    return profile, Path(os.environ["ISSUE328_TAXONOMY_CACHE_DIR"])


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


def test_parser_maps_resource_worker_exit_to_typed_failure(
    monkeypatch: pytest.MonkeyPatch,
):
    class _EmptyQueue:
        def get(self, *, timeout):
            raise queue.Empty

        def close(self):
            return None

    class _DeadProcess:
        exitcode = -9

        def start(self):
            return None

        def is_alive(self):
            return False

        def join(self, timeout=None):
            return None

    class _Context:
        def Queue(self, maxsize):
            return _EmptyQueue()

        def Process(self, **kwargs):
            return _DeadProcess()

    monkeypatch.setattr(
        "fundamental_service.arelle_parser.multiprocessing.get_context",
        lambda name: _Context(),
    )

    with pytest.raises(ArelleParserError) as failure:
        parse_filing_offline(
            Path(__file__).parent / "fixtures" / "simple.xbrl",
            profile=ArelleValidationProfileV1(profile_id="sec-efm-us-gaap-v1"),
            taxonomy_version="fixture-taxonomy-v1",
        )
    assert failure.value.code == "PARSER_RESOURCE_EXHAUSTED"


def test_parser_resource_policy_rejects_invalid_limits():
    with pytest.raises(ArelleParserError) as failure:
        ParserResourcePolicy(max_memory_bytes=1).validate()
    assert failure.value.code == "PARSER_RESOURCE_POLICY_INVALID"


@pytest.mark.skipif(sys.platform != "linux", reason="Linux worker memory enforcement")
@pytest.mark.parametrize("inherited", ["unlimited", "stricter", "stricter-soft"])
def test_worker_enforces_memory_budget_without_raising_inherited_limits(inherited):
    script = """
import json, resource, sys
from fundamental_service.arelle_parser import _apply_worker_memory_limit
budget = 512 * 1024 * 1024
if sys.argv[1] == "stricter":
    resource.setrlimit(resource.RLIMIT_AS, (budget * 3 // 4, budget * 3 // 4))
elif sys.argv[1] == "stricter-soft":
    resource.setrlimit(resource.RLIMIT_AS, (budget * 3 // 4, budget))
before = resource.getrlimit(resource.RLIMIT_AS)
_apply_worker_memory_limit(budget)
print(json.dumps({"before": before, "after": resource.getrlimit(resource.RLIMIT_AS)}))
"""
    result = subprocess.run(
        [sys.executable, "-c", script, inherited],
        check=True,
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": str(Path(__file__).parents[1] / "src")},
    )
    observation = json.loads(result.stdout)
    budget = 512 * 1024 * 1024
    soft, hard = observation["after"]
    assert 0 < soft <= hard <= budget
    for old, new in zip(observation["before"], observation["after"], strict=True):
        assert old == -1 or new <= old
    if inherited != "unlimited":
        assert soft == budget * 3 // 4


def test_parser_concurrency_budget_fails_closed():
    with _parser_slot(1):
        with pytest.raises(ArelleParserError) as failure:
            with _parser_slot(1):
                pass
    assert failure.value.code == "PARSER_CONCURRENCY_EXHAUSTED"


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


@pytest.mark.parametrize(
    ("level", "severity"),
    [("warning-semantic", "warning"), ("error-semantic", "error")],
)
def test_semantic_validation_findings_remain_in_the_report(level: str, severity: str):
    finding = _finding_from_log(
        {
            "level": level,
            "code": "EFM.semantic",
            "message": {"text": "semantic finding"},
        }
    )
    assert finding is not None and finding.severity == severity


@pytest.mark.parametrize(
    "failure_code",
    [
        "DQC.US.0001.1.incomplete",
        "xule.ValidationIncomplete",
        "xule:ValidationException",
        "arelle:dqcrtException",
    ],
)
def test_partial_dqc_findings_cannot_certify_completed_validation(failure_code: str):
    class Handler:
        @staticmethod
        def recordToJson(record: dict[str, object]) -> dict[str, object]:
            return record

    records = ({"code": "DQC.US.0004.1"}, {"code": failure_code})
    assert not _dqc_validation_completed(Handler(), records)
    assert not _dqc_validation_completed(Handler(), tuple(reversed(records)))


@pytest.mark.parametrize(
    ("namespaces", "expected"),
    [
        (("http://fasb.org/us-gaap/2014-01-31",), "DQC_TAXONOMY_UNSUPPORTED"),
        (("http://fasb.org/us-gaap/2019",), "DQC_TAXONOMY_UNSUPPORTED"),
        (("http://fasb.org/us-gaap/2020",), "DQC_VALIDATION_UNAVAILABLE"),
        (("http://fasb.org/us-gaap/2024",), "DQC_VALIDATION_UNAVAILABLE"),
        (
            ("http://fasb.org/us-gaap/2014-01-31", "http://fasb.org/us-gaap/2024"),
            "DQC_VALIDATION_UNAVAILABLE",
        ),
        (("http://example.com/us-gaap/2014-01-31",), "DQC_VALIDATION_UNAVAILABLE"),
        ((), "DQC_VALIDATION_UNAVAILABLE"),
    ],
)
def test_missing_dqc_retains_findings_and_actual_taxonomy(
    namespaces: tuple[str, ...], expected: str
):
    findings = (
        ArelleFindingV1(code="EFM.6.05.42", severity="warning", message="deprecated"),
        ArelleFindingV1(code="EFM.6.05.20", severity="error", message="invalid"),
    )
    error = _missing_dqc_error(
        ArelleValidationProfileV1(profile_id="historical-diagnostic-v1"),
        "1" * 64,
        namespaces,
        findings,
    )
    assert error.code == expected
    diagnostic = error.validation_failure
    assert diagnostic is not None
    assert set(diagnostic.findings) == set(findings)
    assert diagnostic.taxonomy_namespaces == tuple(sorted(set(namespaces)))
    assert diagnostic.validation_engines == ("sec-efm",)
    assert "dqc-not-completed" in diagnostic.validation_evidence
    reordered = diagnostic.model_copy(
        update={
            "findings": tuple(reversed(diagnostic.findings)),
            "taxonomy_namespaces": tuple(reversed(namespaces)),
        }
    )
    assert reordered.replay_digest() == diagnostic.replay_digest()
    assert (
        ArelleValidationFailureV1.model_validate_json(diagnostic.model_dump_json())
        == diagnostic
    )


def test_historical_dqc_failure_survives_the_offline_worker_boundary():
    instance = os.environ.get("ISSUE361_HISTORICAL_INSTANCE_PATH")
    cache = os.environ.get("ISSUE361_HISTORICAL_TAXONOMY_CACHE_DIR")
    if not instance or not cache:
        pytest.skip("captured historical diagnostic instance/cache are not configured")
    profile, _ = _configured_sec_profile()
    profile = profile.model_copy(update={"profile_id": "historical-diagnostic-v1"})
    source_hash = hashlib.sha256(Path(instance).read_bytes()).hexdigest()
    diagnostics = []
    for _ in range(2):
        with pytest.raises(ArelleParserError) as failure:
            parse_filing_offline(
                Path(instance),
                profile=profile,
                taxonomy_version="us-gaap-2014",
                taxonomy_cache_dir=Path(cache),
                source_content_hash=source_hash,
            )
        assert failure.value.code == "DQC_TAXONOMY_UNSUPPORTED"
        diagnostic = failure.value.validation_failure
        assert diagnostic is not None
        assert diagnostic.source_content_hash == source_hash
        assert "http://fasb.org/us-gaap/2014-01-31" in diagnostic.taxonomy_namespaces
        assert "EFM.6.05.42" in {finding.code for finding in diagnostic.findings}
        assert "dqc-us" not in diagnostic.validation_engines
        diagnostics.append(diagnostic.replay_digest())
    assert diagnostics[0] == diagnostics[1]


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
    assert report.network_attempt_count == 0


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


def test_aapl_sec_efm_dqc_replay_resolves_archived_images_without_network(
    tmp_path: Path,
):
    profile, taxonomy_dir = _configured_sec_profile()
    fixture_root = Path(__file__).parent / "fixtures" / "sec-edgar"
    filing_path = tmp_path / "aapl-20240928.htm"
    filing_path.write_bytes(
        (fixture_root / "apple-2024-original-aapl-20240928.htm").read_bytes()
    )
    with ZipFile(
        fixture_root / "apple-2024-original-0000320193-24-000123-xbrl.zip"
    ) as archive:
        archive_names = (
            "aapl-20240928.xsd",
            "aapl-20240928_pre.xml",
            "aapl-20240928_def.xml",
            "aapl-20240928_lab.xml",
            "aapl-20240928_cal.xml",
            "aapl-20240928_g1.jpg",
            "aapl-20240928_g2.jpg",
        )
        for filename in archive_names:
            (tmp_path / filename).write_bytes(archive.read(filename))

    reports = tuple(
        parse_filing_offline(
            filing_path,
            profile=profile,
            taxonomy_version="us-gaap-2024",
            taxonomy_cache_dir=taxonomy_dir,
            source_content_hash=hashlib.sha256(filing_path.read_bytes()).hexdigest(),
            deadline_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        )
        for _ in range(2)
    )
    report, replay = reports

    assert len(report.facts) >= 1000
    assert report.validation_engines == ("sec-efm", "dqc-us")
    assert report.validation_evidence == (
        "strict-sec-efm-profile-selected",
        "dqc-dqcrt-checks-completed",
    )
    assert report.network_attempt_count == 0
    assert report.replay_digest() == replay.replay_digest()
    assert "EFM.5.02.05.graphicFileError" not in report.finding_codes
    assert "EFM.5.02.05.disallowedElement" in report.blocking_finding_codes()
    assert any(
        finding.code == "EFM.5.02.05.disallowedElement" and finding.severity == "error"
        for finding in report.findings
    )


def test_aapl_efm_image_resolution_is_offline_and_preserves_other_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    required = ("ISSUE328_EDGAR_PLUGIN_DIR", "ISSUE328_TAXONOMY_CACHE_DIR")
    if not all(os.environ.get(name) for name in required):
        pytest.skip("pinned SEC EFM runtime paths are not configured")

    from arelle.CntlrCmdLine import CntlrCmdLine, ParserForDynamicPlugins
    from arelle.logging.handlers.LogToXmlHandler import LogToXmlHandler
    from arelle.RuntimeOptions import RuntimeOptions

    fixture_root = Path(__file__).parent / "fixtures" / "sec-edgar"
    raw_content = (fixture_root / "apple-2024-original-aapl-20240928.htm").read_bytes()
    archive_path = fixture_root / "apple-2024-original-0000320193-24-000123-xbrl.zip"
    archive_root = tmp_path / "accession-archive"
    with ZipFile(archive_path) as archive:
        archive_root.mkdir()
        for name in (
            "aapl-20240928.xsd",
            "aapl-20240928_pre.xml",
            "aapl-20240928_def.xml",
            "aapl-20240928_lab.xml",
            "aapl-20240928_cal.xml",
        ):
            (archive_root / name).write_bytes(archive.read(name))
        graphics = {
            name: archive.read(name)
            for name in ("aapl-20240928_g1.jpg", "aapl-20240928_g2.jpg")
        }

    case_roots = {
        "missing": tmp_path / "missing-graphics",
        "present": tmp_path / "present-graphics",
    }
    for case_root in case_roots.values():
        case_root.mkdir()
        (case_root / "aapl-20240928.htm").write_bytes(raw_content)
        for source in archive_root.iterdir():
            (case_root / source.name).write_bytes(source.read_bytes())
    for name, content in graphics.items():
        (case_roots["present"] / name).write_bytes(content)

    plugin_root = tmp_path / "plugins"
    plugin_root.mkdir()
    edgar_plugin_dir = Path(os.environ["ISSUE328_EDGAR_PLUGIN_DIR"])
    (plugin_root / "EDGAR").symlink_to(edgar_plugin_dir, target_is_directory=True)
    taxonomy_cache_dir = Path(os.environ["ISSUE328_TAXONOMY_CACHE_DIR"])
    network_attempts: list[object] = []

    def blocked_network(*args: object, **kwargs: object) -> None:
        network_attempts.append((args, kwargs))
        raise AssertionError("offline SEC replay attempted network access")

    monkeypatch.setattr(socket.socket, "connect", blocked_network)

    def replay(case_root: Path) -> dict[str, object]:
        controller = CntlrCmdLine(disable_persistent_config=True)
        controller._pluginManager._pluginBase = str(plugin_root) + os.sep
        edgar_plugin = controller._pluginManager.addPluginModule("EDGAR/validate")
        assert edgar_plugin is not None
        controller._pluginManager.pluginMethodsForClasses.clear()
        controller.preloadedPlugins = {"EDGAR/validate": edgar_plugin}
        handler = LogToXmlHandler(controller)
        controller.startLogging(logHandler=handler)
        options = RuntimeOptions(
            plugins="EDGAR/validate",
            entrypointFile=str(case_root / "aapl-20240928.htm"),
            validate=True,
            disclosureSystemName="efm-strict-all-years",
            workOffline=True,
            cacheDirectory=str(taxonomy_cache_dir),
            keepOpen=True,
            disablePersistentConfig=True,
            logLevel="DEBUG",
        )
        for extender in controller.plugins.hooks("CntlrCmdLine.Options"):
            extender(ParserForDynamicPlugins(options))
        controller.postLoggingInit()
        assert controller.run(options)
        model = controller.modelManager.modelXbrl
        assert (
            controller.modelManager.disclosureSystem.name
            == "US SEC (Edgar Filing Manual, Strict, all years)"
        )
        facts = sorted(
            (
                str(getattr(getattr(fact, "concept", None), "qname", "")),
                str(getattr(fact, "value", "")),
                str(getattr(fact, "contextID", "")),
                str(getattr(fact, "unitID", "")),
            )
            for fact in model.facts
        )
        findings = tuple(
            handler.recordToJson(record) for record in handler.logRecordBuffer
        )
        result = {
            "fact_count": len(facts),
            "fact_digest": hashlib.sha256(
                json.dumps(facts, separators=(",", ":")).encode()
            ).hexdigest(),
            "model_errors": tuple(sorted(str(code) for code in model.errors)),
            "findings": findings,
        }
        controller.modelManager.close()
        return result

    missing = replay(case_roots["missing"])
    present = replay(case_roots["present"])

    graphic_error = "EFM.5.02.05.graphicFileError"
    disallowed_element = "EFM.5.02.05.disallowedElement"
    assert missing["fact_count"] == present["fact_count"] >= 1000
    assert missing["fact_digest"] == present["fact_digest"]
    assert missing["model_errors"].count(graphic_error) == 2
    assert graphic_error not in present["model_errors"]
    assert disallowed_element in missing["model_errors"]
    assert disallowed_element in present["model_errors"]
    for result, expected_code in (
        (missing, graphic_error),
        (present, disallowed_element),
    ):
        assert any(
            finding.get("code") == expected_code and finding.get("level") == "error"
            for finding in result["findings"]
        )
    assert network_attempts == []


def test_aapl_normalization_preserves_real_xbrl_semantics(tmp_path: Path):
    profile, taxonomy_dir = _configured_sec_profile()
    fixture_root = Path(__file__).parent / "fixtures" / "sec-edgar"
    raw_content = (fixture_root / "apple-2024-original-aapl-20240928.htm").read_bytes()
    archive_path = fixture_root / "apple-2024-original-0000320193-24-000123-xbrl.zip"
    archive_content = archive_path.read_bytes()
    with ZipFile(archive_path) as package:
        archive_member = package.read("aapl-20240928.htm")
        dts = {
            filename: package.read(filename)
            for filename in (
                "aapl-20240928.xsd",
                "aapl-20240928_pre.xml",
                "aapl-20240928_def.xml",
                "aapl-20240928_lab.xml",
                "aapl-20240928_cal.xml",
            )
        }
    captured_at = datetime(2026, 11, 6, tzinfo=timezone.utc)
    base_uri = "https://www.sec.gov/Archives/edgar/data/320193/000032019324000123"
    raw = CapturedSource(
        source_id="sec-filing",
        uri=f"{base_uri}/aapl-20240928.htm",
        role=SourceRole.FILING,
        content=raw_content,
        media_type="text/html",
        http_status=200,
        available_at=captured_at,
        captured_at=captured_at,
        accession_number="0000320193-24-000123",
        form="10-K",
        filed_at=datetime(2024, 11, 1, tzinfo=timezone.utc),
        response_headers=(("x-akamai-transformed", "0 - 0 -"),),
    )
    index = CapturedSource(
        source_id="sec-filing-index",
        uri=f"{base_uri}/index.json",
        role=SourceRole.REFERENCE,
        content=json.dumps(
            {
                "directory": {
                    "item": [
                        {
                            "name": "aapl-20240928.htm",
                            "size": str(len(archive_member) + 1),
                        },
                        {
                            "name": "0000320193-24-000123-xbrl.zip",
                            "size": str(len(archive_content)),
                        },
                    ]
                }
            }
        ).encode(),
        media_type="application/json",
        http_status=200,
        available_at=captured_at,
        captured_at=captured_at,
        accession_number="0000320193-24-000123",
    )
    archive = CapturedSource(
        source_id="sec-filing-archive",
        uri=f"{base_uri}/0000320193-24-000123-xbrl.zip",
        role=SourceRole.FILING,
        content=archive_content,
        media_type="application/zip",
        http_status=200,
        available_at=captured_at,
        captured_at=captured_at,
        accession_number="0000320193-24-000123",
        form="10-K",
        filed_at=datetime(2024, 11, 1, tzinfo=timezone.utc),
    )
    assessment = assess_filing_response(
        raw_response=raw, archive_index=index, archive=archive
    )
    assert assessment.relation == "normalized"
    assert assessment.normalized_content == archive_member

    normalized_path = tmp_path / "normalized" / "aapl-20240928.htm"
    archive_path = tmp_path / "archive" / "aapl-20240928.htm"
    normalized_path.parent.mkdir()
    archive_path.parent.mkdir()
    normalized_path.write_bytes(assessment.normalized_content)
    archive_path.write_bytes(assessment.archive_member)
    for root in (normalized_path.parent, archive_path.parent):
        for filename, content in dts.items():
            (root / filename).write_bytes(content)

    kwargs = dict(
        profile=profile,
        taxonomy_version="us-gaap-2024",
        taxonomy_cache_dir=taxonomy_dir,
    )
    normalized_report = parse_filing_offline(
        normalized_path,
        **kwargs,
        source_content_hash=hashlib.sha256(normalized_path.read_bytes()).hexdigest(),
    )
    archive_report = parse_filing_offline(
        archive_path,
        **kwargs,
        source_content_hash=hashlib.sha256(archive_path.read_bytes()).hexdigest(),
    )
    archive_replay = parse_filing_offline(
        archive_path,
        **kwargs,
        source_content_hash=hashlib.sha256(archive_path.read_bytes()).hexdigest(),
    )
    normalized_replay = parse_filing_offline(
        normalized_path,
        **kwargs,
        source_content_hash=hashlib.sha256(normalized_path.read_bytes()).hexdigest(),
    )
    assert len(normalized_report.facts) == len(archive_report.facts)
    assert fact_semantic_digest(normalized_report) == fact_semantic_digest(
        archive_report
    )
    assert tuple(
        sorted((item.code, item.severity) for item in normalized_report.findings)
    ) == tuple(sorted((item.code, item.severity) for item in archive_report.findings))
    assert normalized_report.replay_digest() == normalized_replay.replay_digest()
    assert archive_report.replay_digest() == archive_replay.replay_digest()
    assert (
        normalized_report.validation_profile_digest
        == archive_report.validation_profile_digest
    )
    assert normalized_report.validation_engines == archive_report.validation_engines
    assert normalized_report.validation_evidence == archive_report.validation_evidence
    assert normalized_report.network_attempt_count == 0
    assert archive_report.network_attempt_count == 0


def test_microsoft_sec_efm_dqc_replay_allows_verified_fixture(tmp_path: Path):
    profile, taxonomy_dir = _configured_sec_profile()
    fixture = (
        Path(__file__).parent
        / "fixtures"
        / "sec-edgar"
        / "microsoft-2024-original-xbrl-test-package.zip"
    )
    with ZipFile(fixture) as archive:
        filing_path = tmp_path / "msft-20240630.htm"
        filing_path.write_bytes(archive.read("msft-20240630.htm"))
        (tmp_path / "msft-20240630.xsd").write_bytes(archive.read("msft-20240630.xsd"))

    report = parse_filing_offline(
        filing_path,
        profile=profile,
        taxonomy_version="us-gaap-2023-2024",
        taxonomy_cache_dir=taxonomy_dir,
        source_content_hash=hashlib.sha256(filing_path.read_bytes()).hexdigest(),
    )

    assert len(report.facts) >= 1800
    assert report.blocking_finding_codes() == ()
    assert report.validation_engines == ("sec-efm", "dqc-us")
    assert report.network_attempt_count == 0
    replay = parse_filing_offline(
        filing_path,
        profile=profile,
        taxonomy_version="us-gaap-2023-2024",
        taxonomy_cache_dir=taxonomy_dir,
        source_content_hash=hashlib.sha256(filing_path.read_bytes()).hexdigest(),
    )
    assert report.replay_digest() == replay.replay_digest()
