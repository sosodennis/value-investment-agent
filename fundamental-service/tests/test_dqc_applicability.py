from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from fundamental_service.arelle_parser import (
    ArelleFindingV1,
    ArelleParseReportV1,
    ArelleValidationProfileV1,
)
from fundamental_service.dqc_applicability import (
    DqcFilingContextV1,
    dqc_applicability_policy_digest,
    evaluate_dqc_applicability,
)
from fundamental_service.regulatory_validation import bind_dqc_filing_context
from fundamental_service.snapshots import SnapshotError


def _context(filing_date=date(2026, 2, 12), **changes):
    return DqcFilingContextV1(
        issuer_id="0000007623",
        accession_number="0001437749-26-003904",
        filing_date=filing_date,
        policy_digest=dqc_applicability_policy_digest(),
    ).model_copy(update=changes)


def _report(findings):
    profile = ArelleValidationProfileV1(
        profile_id="fixture-sec-v31",
        validation_mode="sec-efm-dqc",
        edgar_plugin_dir=Path("fixture-edgar"),
        xule_plugin_dir=Path("fixture-xule"),
        dqc_ruleset_path=Path("fixture-rules.zip"),
        edgar_plugin_sha256="1" * 64,
        xule_plugin_sha256="2" * 64,
        dqc_ruleset_sha256="3" * 64,
        dqc_applicability_digest=dqc_applicability_policy_digest(),
    )
    return ArelleParseReportV1(
        filing_path="fixture-original.htm",
        parser_version="2.47.4",
        taxonomy_version="us-gaap-2025",
        validation_profile=profile,
        validation_profile_digest=profile.digest(),
        findings=tuple(findings),
        validation_engines=("sec-efm", "dqc-us"),
        validation_evidence=(
            "strict-sec-efm-profile-selected",
            "dqc-dqcrt-checks-completed",
        ),
        parsed_at=datetime(2026, 11, 14, tzinfo=timezone.utc),
    )


def _finding(code="DQC.US.0243.10944", **changes):
    return ArelleFindingV1(
        code=code,
        severity="warning",
        rule_severity="error",
        message="fixture official diagnostic",
    ).model_copy(update=changes)


@pytest.mark.parametrize(
    "filed,expected",
    [
        (date(2026, 8, 31), ()),
        (date(2026, 9, 1), ("DQC.US.0243.10944",)),
        (date(2026, 9, 2), ("DQC.US.0243.10944",)),
    ],
)
def test_exact_official_assertion_date_uses_original_filing_day(filed, expected):
    original = _report([_finding()])
    assert original.blocking_finding_codes() == ("DQC.US.0243.10944",)
    bound = bind_dqc_filing_context(original, _context(filed))
    assert bound.blocking_finding_codes() == expected
    assert bound.findings == original.findings
    assert bound.parsed_at > datetime(2026, 9, 1, tzinfo=timezone.utc)
    decision = bound.finding_applicability(bound.findings[0])
    assert decision.effective_date == date(2026, 9, 1)
    assert decision.date_source == "official-rule-document"
    assert (
        decision.document_sha256
        == "a5184563321280b25907b901480cdbae75120443c429e600ae7be8217efe598f"
    )


def test_not_yet_effective_assertion_stays_in_persisted_replay():
    finding = _finding("DQC.US.0249.10961")
    original = _report([finding])
    bound = bind_dqc_filing_context(original, _context(date(2026, 11, 14)))
    restored = ArelleParseReportV1.model_validate_json(bound.model_dump_json())
    assert restored.findings == (finding,)
    assert restored.blocking_finding_codes() == ()
    assert restored.replay_digest() == bound.replay_digest()
    assert bind_dqc_filing_context(restored, restored.dqc_filing_context) == restored
    assert restored.replay_digest() != original.replay_digest()


@pytest.mark.parametrize(
    "filed,expected",
    [
        (date(2024, 10, 9), ()),
        (date(2025, 10, 8), ()),
        (date(2026, 5, 31), ()),
        (date(2026, 6, 1), ("DQC.US.0228.10921",)),
        (date(2026, 6, 2), ("DQC.US.0228.10921",)),
    ],
)
def test_official_xule_and_date_table_bind_exact_assertion(filed, expected):
    finding = _finding("DQC.US.0228.10921")
    bound = bind_dqc_filing_context(_report([finding]), _context(filed))
    assert bound.findings == (finding,)
    assert bound.blocking_finding_codes() == expected
    decision = bound.finding_applicability(finding)
    assert decision.effective_date == date(2026, 6, 1)
    assert decision.date_source == "official-rule-date-table"
    assert decision.document_sha256 is None
    assert decision.date_table_sha256 == (
        "98dde485be1cc5814cb3f6a7cd6ebd9152742bfb42c314ba6fa876a82f2e4da8"
    )
    assert len(decision.rule_source_sha256) == 8
    restored = ArelleParseReportV1.model_validate_json(bound.model_dump_json())
    assert restored.replay_digest() == bound.replay_digest()


@pytest.mark.parametrize(
    "finding",
    [
        _finding("DQC.US.0238.10921"),
        _finding("DQC.US.0228.10801"),
        _finding("DQC.US.0228.10921", rule_effective_date=date(2026, 6, 2)),
        _finding("DQC.US.0228.10921", rule_severity="critical"),
        _finding("DQC.US.0228.10921", rule_severity="fatal"),
    ],
)
def test_date_table_does_not_approve_other_assertions_or_critical_errors(finding):
    bound = bind_dqc_filing_context(_report([finding]), _context(date(2024, 1, 1)))
    assert bound.blocking_finding_codes() == (finding.code,)


def test_date_table_and_document_conflict_stays_blocking(monkeypatch):
    import fundamental_service.dqc_applicability as policy

    monkeypatch.setattr(
        policy,
        "_document_dates",
        lambda: {"DQC.US.0228.10921": (date(2026, 6, 2), "a" * 64)},
    )
    finding = _finding("DQC.US.0228.10921")
    bound = bind_dqc_filing_context(_report([finding]), _context())
    assert bound.blocking_finding_codes() == (finding.code,)
    decision = bound.finding_applicability(finding)
    assert decision.status == "conflict"
    assert decision.effective_date is None
    assert decision.document_sha256 == "a" * 64
    assert decision.date_table_sha256 is not None


def test_corrupt_assertion_date_catalog_refuses(tmp_path, monkeypatch):
    import fundamental_service.dqc_applicability as policy

    corrupt = tmp_path / "table.json"
    corrupt.write_bytes(b"{}")
    policy._assertion_dates.cache_clear()
    monkeypatch.setattr(policy, "_TABLE_CATALOG_PATH", corrupt)
    try:
        with pytest.raises(ValueError, match="date table hash"):
            evaluate_dqc_applicability(
                code="DQC.US.0228.10921", emitted_date=None, context=_context()
            )
    finally:
        policy._assertion_dates.cache_clear()


@pytest.mark.parametrize("level", ["critical", "fatal"])
def test_critical_or_fatal_validation_remains_blocking(level):
    finding = _finding(rule_severity=level)
    bound = bind_dqc_filing_context(_report([finding]), _context())
    assert bound.blocking_finding_codes() == (finding.code,)


@pytest.mark.parametrize(
    "finding",
    [
        _finding("DQC.US.0099.9533", rule_effective_date=date(2021, 1, 1)),
        _finding("DQC.US.9999.99999"),
        _finding("DQC.US.0243.99999"),
        _finding("EFM.6.08.05.firstLetter", severity="error"),
        _finding("xule:ValidationException", severity="error"),
        _finding(rule_effective_date=date(2027, 1, 1)),
    ],
)
def test_active_unknown_non_dqc_and_conflicting_dates_stay_blocking(finding):
    bound = bind_dqc_filing_context(_report([finding]), _context())
    assert bound.blocking_finding_codes() == (finding.code,)


def test_logged_official_date_can_establish_applicability_without_document_fallback():
    finding = _finding("DQC.US.0200.10000", rule_effective_date=date(2026, 9, 1))
    bound = bind_dqc_filing_context(_report([finding]), _context())
    assert bound.blocking_finding_codes() == ()
    decision = bound.finding_applicability(finding)
    assert decision.date_source == "official-xule"
    assert decision.status == "future"
    assert decision.document_sha256 is None


def test_conflicting_effective_dates_are_explicit():
    context = _context()
    decision = evaluate_dqc_applicability(
        code="DQC.US.0243.10944", emitted_date=date(2027, 1, 1), context=context
    )
    assert decision.status == "conflict"
    assert decision.effective_date is None
    assert decision.date_source == "conflict"


@pytest.mark.parametrize(
    "field,value", [("filing_date", "2099-01-01"), ("issuer_id", "0000000001")]
)
def test_context_cannot_be_changed_without_rebinding_evidence(field, value):
    bound = bind_dqc_filing_context(_report([_finding()]), _context())
    payload = bound.model_dump(mode="json")
    payload["dqc_filing_context"][field] = value
    with pytest.raises(ValidationError, match="matching validation evidence"):
        ArelleParseReportV1.model_validate(payload)


def test_rebinding_another_filing_refuses():
    bound = bind_dqc_filing_context(_report([_finding()]), _context())
    with pytest.raises(SnapshotError) as failure:
        bind_dqc_filing_context(bound, _context(date(2026, 9, 1)))
    assert failure.value.code == "DQC_FILING_CONTEXT_MISMATCH"


def test_incomplete_validation_cannot_be_made_usable_by_future_rule_date():
    report = _report([_finding()]).model_copy(update={"validation_evidence": ()})
    with pytest.raises(SnapshotError) as failure:
        bind_dqc_filing_context(report, _context())
    assert failure.value.code == "VALIDATION_EVIDENCE_MISSING"


def test_unknown_policy_cannot_authorize_applicability():
    payload = _context().model_dump(mode="json")
    payload["policy_digest"] = "0" * 64
    with pytest.raises(ValidationError, match="pinned policy"):
        DqcFilingContextV1.model_validate(payload)


def test_corrupt_official_catalog_refuses(tmp_path, monkeypatch):
    import fundamental_service.dqc_applicability as policy

    corrupt = tmp_path / "catalog.json"
    corrupt.write_bytes(b"{}")
    policy._document_dates.cache_clear()
    monkeypatch.setattr(policy, "_CATALOG_PATH", corrupt)
    try:
        with pytest.raises(ValueError, match="catalog hash"):
            evaluate_dqc_applicability(
                code="DQC.US.0243.10944", emitted_date=None, context=_context()
            )
    finally:
        policy._document_dates.cache_clear()


@pytest.mark.parametrize(
    "filed,blocks,status",
    (
        (date(2024, 2, 9), False, "future"),
        (date(2026, 5, 31), False, "future"),
        (date(2026, 6, 1), True, "active"),
        (date(2026, 11, 14), True, "active"),
    ),
)
def test_aggregate_sibling_assertion_uses_exact_official_date_binding(
    filed, blocks, status
):
    finding = _finding("DQC.US.0231.10924")
    bound = bind_dqc_filing_context(_report([finding]), _context(filed))
    assert bool(bound.blocking_finding_codes()) == blocks
    assert bound.findings == (finding,)
    decision = bound.finding_applicability(finding)
    assert decision.status == status
    assert decision.effective_date == date(2026, 6, 1)
    assert decision.date_source == "official-rule-date-table"
    assert decision.document_sha256 is None
    assert (
        decision.date_table_sha256
        == "98dde485be1cc5814cb3f6a7cd6ebd9152742bfb42c314ba6fa876a82f2e4da8"
    )
    assert len(decision.rule_source_sha256) == 8
    assert len(set(decision.rule_source_sha256)) == 7


def test_aggregate_sibling_conflicting_emitted_date_remains_blocking():
    finding = _finding("DQC.US.0231.10924", rule_effective_date=date(2025, 4, 15))
    bound = bind_dqc_filing_context(_report([finding]), _context(date(2024, 2, 9)))
    assert bound.blocking_finding_codes() == (finding.code,)
    assert bound.finding_applicability(finding).status == "conflict"
