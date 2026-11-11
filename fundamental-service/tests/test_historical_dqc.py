"""Historical rules execute offline without granting release authority."""

from __future__ import annotations
import hashlib
import os
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import cast
import pytest
from arelle.Cntlr import Cntlr
from arelle.ValidateXbrl import ValidateXbrl
from fundamental_service import historical_dqc
from fundamental_service.arelle_parser import (
    ArelleParseReportV1,
    ArelleParserError,
    ArelleValidationProfileV1,
    _directory_hash,
    _finding_from_log,
    _missing_dqc_error,
    parse_filing_offline,
)
from fundamental_service.historical_dqc import (
    HISTORICAL_PROFILE_ID,
    OFFICIAL_MODULES,
    OFFICIAL_SOURCE_SHA256,
    HistoricalDqcExecution,
    HistoricalDqcProfile,
    V1_PROFILE,
    V3_PROFILE,
    execution_for,
)
from fundamental_service.ingestion import SecIngestionService
from fundamental_service.snapshots import SnapshotError


def test_original_dqc_error_remains_blocking_after_edgar_relevels_it():
    finding = _finding_from_log(
        {
            "level": "warning",
            "code": "DQC.US.0015.2098",
            "message": {
                "text": "negative PPE",
                "args": {"fundamental_rule_severity": "error"},
            },
        }
    )
    assert finding is not None
    assert finding.severity == "warning" and finding.rule_severity == "error"
    report = ArelleParseReportV1(
        filing_path="original.xml",
        parser_version="2.47.4",
        taxonomy_version="us-gaap-2014",
        validation_profile=_profile(),
        validation_profile_digest=_profile().digest(),
        findings=(finding,),
        parsed_at=datetime(2026, 11, 11, tzinfo=timezone.utc),
    )
    assert report.blocking_finding_codes() == (finding.code,)


def test_modern_profile_keeps_its_existing_identity():
    from fundamental_service.serialization import sha256_digest

    profile = ArelleValidationProfileV1(profile_id="offline-parse-only-v1")
    original = profile.model_dump(
        mode="json", exclude={"historical_dqc_dir", "historical_dqc_sha256"}
    )
    assert profile.digest() == sha256_digest(original)


def _profile(**changes: object) -> ArelleValidationProfileV1:
    values: dict[str, object] = {
        "profile_id": HISTORICAL_PROFILE_ID,
        "dqc_version": "v1.0.0",
        "validation_mode": "sec-efm-dqc",
        "edgar_plugin_dir": "/runtime/EDGAR",
        "xule_plugin_dir": "/runtime/xule",
        "dqc_ruleset_path": "/runtime/dqc.zip",
        "edgar_plugin_sha256": "a" * 64,
        "xule_plugin_sha256": "b" * 64,
        "dqc_ruleset_sha256": "c" * 64,
        "historical_dqc_dir": "/runtime/historical-dqc",
        "historical_dqc_sha256": OFFICIAL_SOURCE_SHA256,
    }
    return ArelleValidationProfileV1.model_validate({**values, **changes})


@pytest.mark.parametrize(
    "changes",
    [
        {"dqc_version": "v31.0.3"},
        {"profile_id": "sec-efm-us-dqc-v31.0.3"},
        {"historical_dqc_dir": None},
        {"historical_dqc_sha256": "d" * 64},
        {"validation_mode": "parse-only"},
    ],
)
def test_historical_profile_rejects_mixed_or_unpinned_resources(changes):
    with pytest.raises(ValueError):
        _profile(**changes)


def test_historical_profile_digest_binds_sources_without_host_paths():
    profile = _profile()
    assert (
        profile.digest()
        == _profile(historical_dqc_dir="/another/host/historical-dqc").digest()
    )
    assert profile.digest() != _profile(edgar_plugin_sha256="e" * 64).digest()


def test_v3_profile_requires_its_exact_package_version_and_distinct_digest():
    profile = _profile(
        profile_id=V3_PROFILE.profile_id,
        dqc_version=V3_PROFILE.dqc_version,
        historical_dqc_sha256=V3_PROFILE.source_sha256,
    )
    assert profile.digest() != _profile().digest()
    for changes in (
        {"dqc_version": "v1.0.0"},
        {"historical_dqc_sha256": OFFICIAL_SOURCE_SHA256},
        {"validation_mode": "parse-only"},
    ):
        with pytest.raises(ValueError):
            ArelleValidationProfileV1.model_validate(
                {**profile.model_dump(), **changes}
            )


def _validation(namespaces: tuple[str, ...]):
    state = HistoricalDqcExecution(Path("/pinned"))
    controller = SimpleNamespace(fundamental_historical_dqc_execution=state)
    logs = []

    def original_log(level: str, codes: object, msg: str, **args: object) -> None:
        logs.append((level, codes, msg, args))

    model = SimpleNamespace(
        modelManager=SimpleNamespace(cntlr=controller),
        namespaceDocs=dict.fromkeys(namespaces),
        log=original_log,
    )
    validation = SimpleNamespace(modelXbrl=model)
    return validation, state, original_log, logs


def test_official_hooks_complete_only_after_all_return_and_log_observer_is_restored(
    monkeypatch: pytest.MonkeyPatch,
):
    validation, state, original_log, logs = _validation(
        ("http://fasb.org/us-gaap/2014-01-31", "http://xbrl.sec.gov/dei/2014-01-31")
    )
    monkeypatch.setattr(historical_dqc, "_load_package", lambda root: object())
    calls = []

    def hook_for(package, name):
        def hook(value):
            calls.append(name)
            value.modelXbrl.log("ERROR", "DQC.US.0015.2098", "official finding")

        return hook

    monkeypatch.setattr(historical_dqc, "_official_hook", hook_for)
    historical_dqc.validate(cast(ValidateXbrl, validation))
    assert calls == list(OFFICIAL_MODULES)
    assert state.completed
    assert validation.modelXbrl.log is original_log
    assert all(row[3]["fundamental_rule_severity"] == "error" for row in logs)
    assert execution_for(cast(Cntlr, validation.modelXbrl.modelManager.cntlr)) is state


def test_partial_rules_never_certify_and_preserve_returned_inventory(
    monkeypatch: pytest.MonkeyPatch,
):
    validation, state, original_log, _ = _validation(
        ("http://fasb.org/us-gaap/2014-01-31",)
    )
    monkeypatch.setattr(historical_dqc, "_load_package", lambda root: object())

    def hook_for(package, name):
        def hook(value):
            if name == OFFICIAL_MODULES[1]:
                raise RuntimeError("official rule execution failed")

        return hook

    monkeypatch.setattr(historical_dqc, "_official_hook", hook_for)
    with pytest.raises(RuntimeError, match="official rule execution failed"):
        historical_dqc.validate(cast(ValidateXbrl, validation))
    assert not state.completed
    assert state.returned_modules == [OFFICIAL_MODULES[0]]
    assert validation.modelXbrl.log is original_log
    error = _missing_dqc_error(_profile(), "a" * 64, (), (), state)
    assert error.code == "DQC_VALIDATION_UNAVAILABLE"
    assert error.validation_failure is not None
    assert (
        "historical-module-returned:dqc_us_0004"
        in error.validation_failure.validation_evidence
    )


@pytest.mark.parametrize("year", (2011, 2018))
def test_v3_keeps_unsupported_namespaces_blocked(year):
    namespaces = (f"http://fasb.org/us-gaap/{year}-01-31",)
    validation, state, _, _ = _validation(namespaces)
    state.profile = V3_PROFILE
    historical_dqc.validate(cast(ValidateXbrl, validation))
    assert not state.completed and state.returned_modules == []
    assert state.unsupported_namespaces == namespaces


def test_v3_last_hook_failure_never_counts_as_complete(monkeypatch):
    validation, state, original_log, _ = _validation(
        ("http://fasb.org/us-gaap/2016-01-31",)
    )
    state.profile = V3_PROFILE
    monkeypatch.setattr(historical_dqc, "_load_package", lambda root: object())

    def hook_for(package, name):
        def hook(value):
            if name == V3_PROFILE.modules[-1]:
                raise RuntimeError("final official hook failed")

        return hook

    monkeypatch.setattr(historical_dqc, "_official_hook", hook_for)
    with pytest.raises(RuntimeError, match="final official hook failed"):
        historical_dqc.validate(cast(ValidateXbrl, validation))
    assert not state.completed and state.failed
    assert tuple(state.returned_modules) == V3_PROFILE.modules[:-1]
    assert validation.modelXbrl.log is original_log


@pytest.mark.parametrize(
    "namespaces",
    [
        ("http://fasb.org/us-gaap/2016-01-31",),
        ("http://fasb.org/us-gaap/2014-01-31", "http://fasb.org/us-gaap/2016-01-31"),
        ("http://fasb.org/us-gaap/2014-01-31", "http://xbrl.sec.gov/dei/2018-01-31"),
    ],
)
def test_unsupported_or_mixed_namespaces_do_not_run_rules(namespaces):
    validation, state, original_log, logs = _validation(namespaces)
    historical_dqc.validate(cast(ValidateXbrl, validation))
    assert not state.completed
    assert state.returned_modules == []
    assert state.unsupported_namespaces
    assert logs == []
    assert validation.modelXbrl.log is original_log
    error = _missing_dqc_error(_profile(), "a" * 64, namespaces, (), state)
    assert error.code == "DQC_TAXONOMY_UNSUPPORTED"


@pytest.mark.parametrize("historical", (V1_PROFILE, V3_PROFILE), ids=("v1", "v3"))
def test_original_historical_xml_replays_with_real_efm_and_official_dqc(
    tmp_path: Path, historical: HistoricalDqcProfile
):
    names = (
        "ISSUE376_HISTORICAL_DQC_DIR"
        if historical == V1_PROFILE
        else "ISSUE376_HISTORICAL_DQC_V3_DIR",
        "ISSUE376_HISTORICAL_XML",
        "ISSUE376_EDGAR_PLUGIN_DIR",
        "ISSUE376_XULE_PLUGIN_DIR",
        "ISSUE376_DQC_RULESET_PATH",
        "ISSUE376_TAXONOMY_CACHE_DIR",
    )
    if not all(os.getenv(name) for name in names):
        pytest.skip(
            "captured historical source and pinned validation resources are not configured"
        )
    edgar = Path(os.environ[names[2]])
    xule = Path(os.environ[names[3]])
    ruleset = Path(os.environ[names[4]])
    profile = _profile(
        profile_id=historical.profile_id,
        dqc_version=historical.dqc_version,
        historical_dqc_sha256=historical.source_sha256,
        edgar_plugin_dir=edgar,
        xule_plugin_dir=xule,
        dqc_ruleset_path=ruleset,
        edgar_plugin_sha256=_directory_hash(edgar),
        xule_plugin_sha256=_directory_hash(xule),
        dqc_ruleset_sha256=hashlib.sha256(ruleset.read_bytes()).hexdigest(),
        historical_dqc_dir=os.environ[names[0]],
    )
    filing = Path(os.environ[names[1]])
    reports = tuple(
        parse_filing_offline(
            filing,
            profile=profile,
            taxonomy_version="us-gaap-2014",
            taxonomy_cache_dir=Path(os.environ[names[5]]),
            source_content_hash=hashlib.sha256(filing.read_bytes()).hexdigest(),
            deadline_at=datetime.now(timezone.utc) + timedelta(seconds=180),
        )
        for _ in range(2)
    )
    assert reports[0].replay_digest() == reports[1].replay_digest()
    assert all(report.network_attempt_count == 0 for report in reports)
    assert all(report.validation_engines == ("sec-efm", "dqc-us") for report in reports)
    for report in reports:
        # Publication needs the separately reviewed historical release contract.
        with pytest.raises(SnapshotError, match="completion evidence"):
            SecIngestionService._require_validation_evidence(report)
    assert len(reports[0].facts) == 327
    original_cik = next(
        f for f in reports[0].facts if f.concept == "dei:EntityCentralIndexKey"
    )
    assert original_cik.namespace_uri == "http://xbrl.sec.gov/dei/2014-01-31"
    assert original_cik.entity_identifier == "0001539778"
    assert "DQC.US.0015.2098" in reports[0].blocking_finding_codes()
    assert any(
        f.rule_severity == "error" and f.severity == "warning"
        for f in reports[0].findings
    )
    if historical == V3_PROFILE:
        modern = ArelleValidationProfileV1.model_validate(
            {
                **profile.model_dump(),
                "profile_id": "sec-efm-us-dqc-v31.0.3",
                "dqc_version": "v31.0.3",
                "historical_dqc_dir": None,
                "historical_dqc_sha256": None,
            }
        )
        with pytest.raises(ArelleParserError) as incomplete:
            parse_filing_offline(
                filing,
                profile=modern,
                taxonomy_version="us-gaap-2014",
                taxonomy_cache_dir=Path(os.environ[names[5]]),
            )
        assert incomplete.value.code == "DQC_TAXONOMY_UNSUPPORTED"
        diagnostic = incomplete.value.validation_failure
        assert diagnostic is not None and diagnostic.findings
        assert "http://fasb.org/us-gaap/2014-01-31" in diagnostic.taxonomy_namespaces
        assert (
            diagnostic.source_content_hash
            == hashlib.sha256(filing.read_bytes()).hexdigest()
        )
    changed_root = tmp_path / "changed-rules"
    shutil.copytree(Path(os.environ[names[0]]), changed_root)
    changed_file = changed_root / "dqc_us_0004.py"
    changed_file.write_bytes(changed_file.read_bytes() + b"\n# changed rule source\n")
    changed_profile = profile.model_copy(update={"historical_dqc_dir": changed_root})
    with pytest.raises(ArelleParserError) as changed:
        parse_filing_offline(
            filing, profile=changed_profile, taxonomy_version="us-gaap-2014"
        )
    assert changed.value.code == "VALIDATION_RESOURCE_HASH_MISMATCH"
    with pytest.raises(ArelleParserError) as mismatch:
        parse_filing_offline(
            filing,
            profile=profile,
            taxonomy_version="us-gaap-2014",
            source_content_hash="0" * 64,
        )
    assert mismatch.value.code == "SOURCE_HASH_MISMATCH"
