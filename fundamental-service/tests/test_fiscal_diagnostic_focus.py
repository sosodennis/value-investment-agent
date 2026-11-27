import multiprocessing
import os
import signal
import tempfile
import time
from datetime import UTC, date, datetime, timedelta
from functools import partial
from pathlib import Path

import pytest
from fundamental_service import fiscal_diagnostic_focus as worker
from fundamental_service.arelle_parser import (
    ArelleFindingV1,
    ArelleParseReportV1,
    ArelleParserError,
    ArelleValidationProfileV1,
    ParsedXbrlFactV1,
    ParserResourcePolicy,
    _claim_parser_process_slot,
    fact_semantic_digest,
)
from fundamental_service.dqc_applicability import (
    DqcFilingContextV1,
    dqc_applicability_policy_digest,
)
from fundamental_service.fiscal_diagnostic_focus import (
    ArelleActualFocusEventV1,
    ArelleActualFocusFactV1,
    FiscalDiagnosticFocusExecutionV1,
    _match_actual_focus,
    run_fiscal_diagnostic_focus,
)
from fundamental_service.regulatory_validation import bind_dqc_filing_context
from fundamental_service.serialization import sha256_digest
from fundamental_service.snapshots import SnapshotError
from pydantic import ValidationError

_FILING_CONTEXT = DqcFilingContextV1(
    issuer_id="0000789019",
    accession_number="0000950170-24-118967",
    filing_date=date(2024, 10, 30),
    policy_digest=dqc_applicability_policy_digest(),
)


def match_actual_focus(retained, execution):
    return _match_actual_focus(retained, execution, filing_context=_FILING_CONTEXT)


def _execution(
    report: ArelleParseReportV1, events: tuple[ArelleActualFocusEventV1, ...]
) -> FiscalDiagnosticFocusExecutionV1:
    return FiscalDiagnosticFocusExecutionV1(
        report=report,
        events=events,
        complete_fact_digest=fact_semantic_digest(report),
        complete_findings_digest=sha256_digest(
            sorted(report.findings, key=sha256_digest)
        ),
    )


@pytest.fixture
def evidence() -> tuple[ArelleParseReportV1, FiscalDiagnosticFocusExecutionV1]:
    profile = ArelleValidationProfileV1(
        profile_id="sec-efm-us-dqc-v31.0.3",
        validation_mode="sec-efm-dqc",
        edgar_plugin_dir=Path("/pinned/EDGAR"),
        edgar_plugin_sha256="1" * 64,
        xule_plugin_dir=Path("/pinned/xule"),
        xule_plugin_sha256="2" * 64,
        dqc_ruleset_path=Path("/pinned/rules.zip"),
        dqc_ruleset_sha256="3" * 64,
        dqc_applicability_digest=dqc_applicability_policy_digest(),
    )
    fact = ParsedXbrlFactV1(
        concept="us-gaap:ShortTermInvestments",
        namespace_uri="http://fasb.org/us-gaap/2024",
        value="-1000000",
        context_id="c-derivatives",
        unit="iso4217:USD",
        decimals="-6",
        entity_scheme="http://www.sec.gov/CIK",
        entity_identifier="0000789019",
        instant=date(2024, 9, 30),
        dimensions=(("us-gaap:FinancialInstrumentAxis", "us-gaap:DerivativeMember"),),
        dimension_namespace_uris=(
            (
                "us-gaap:FinancialInstrumentAxis",
                "http://fasb.org/us-gaap/2024",
                "http://fasb.org/us-gaap/2024",
            ),
        ),
        is_numeric=True,
        scale=6,
        consolidation_scope="segmented",
        security_scope="segmented",
    )
    finding = ArelleFindingV1(
        code="DQC.US.0015.5970",
        severity="warning",
        rule_severity="error",
        rule_effective_date=date(2017, 3, 28),
        message="The reported short-term investment is negative.",
    )
    retained = ArelleParseReportV1(
        filing_path="/retained/original.htm",
        parser_version="2.47.4",
        taxonomy_version="us-gaap-2024",
        validation_profile=profile,
        validation_profile_digest=profile.digest(),
        facts=(fact,),
        findings=(finding,),
        finding_codes=(finding.code,),
        validation_engines=("sec-efm", "dqc-us"),
        validation_evidence=(
            "strict-sec-efm-profile-selected",
            "dqc-dqcrt-checks-completed",
        ),
        parsed_at=datetime(2024, 11, 1, tzinfo=UTC),
        source_content_hash="4" * 64,
        taxonomy_cache_hash="5" * 64,
    )
    replayed = retained.model_copy(
        update={
            "filing_path": "/scratch/original.htm",
            "parsed_at": retained.parsed_at + timedelta(days=1),
        }
    )
    event = ArelleActualFocusEventV1(
        level="ERROR",
        facts=(
            ArelleActualFocusFactV1(
                fact_id="f-derivatives", fact=fact, numeric_value="-1000000"
            ),
        ),
    )
    return retained, _execution(replayed, (event,))


def test_matches_actual_focus_without_rewriting_retained_report(evidence):
    retained, replayed = evidence
    raw_bytes = retained.model_dump_json().encode()
    execution = FiscalDiagnosticFocusExecutionV1.model_validate_json(
        replayed.model_dump_json().encode()
    )

    focus = match_actual_focus(retained, execution)

    assert (focus.fact_id, focus.fact.context_id, focus.numeric_value) == (
        "f-derivatives",
        "c-derivatives",
        "-1000000",
    )
    assert focus.fact.instant == date(2024, 9, 30)
    assert (focus.fact.value, focus.fact.scale, focus.fact.unit) == (
        "-1000000",
        6,
        "iso4217:USD",
    )
    assert retained.blocking_finding_codes() == ("DQC.US.0015.5970",)
    assert retained.model_dump_json().encode() == raw_bytes


def test_match_respects_catalog_binding_and_leaves_raw_action_unbound(evidence):
    raw_action, execution = evidence
    bound = bind_dqc_filing_context(raw_action, _FILING_CONTEXT)
    another_context = _FILING_CONTEXT.model_copy(
        update={"filing_date": date(2024, 10, 31)}
    )

    assert match_actual_focus(bound, execution).fact_id == "f-derivatives"
    with pytest.raises(SnapshotError) as failure:
        _match_actual_focus(bound, execution, filing_context=another_context)
    assert failure.value.code == "DQC_FILING_CONTEXT_MISMATCH"
    assert raw_action.dqc_filing_context is None
    assert execution.report.dqc_filing_context is None


@pytest.mark.parametrize("side", ["retained", "replayed"])
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("source_content_hash", "a" * 64),
        ("taxonomy_cache_hash", "a" * 64),
        ("validation_profile_digest", "a" * 64),
        ("taxonomy_version", "us-gaap-2025"),
        ("parser_version", "2.47.5"),
        ("source_content_hash", None),
        ("taxonomy_cache_hash", None),
        ("network_attempt_count", 1),
        ("offline", False),
        ("validation_engines", ("sec-efm",)),
        ("validation_evidence", ("strict-sec-efm-profile-selected",)),
    ],
)
def test_rejects_validation_or_input_changes_with_identical_facts(
    evidence, side, field, value
):
    retained, execution = evidence
    if side == "retained":
        retained = retained.model_copy(update={field: value})
    else:
        execution = _execution(
            execution.report.model_copy(update={field: value}), execution.events
        )

    with pytest.raises(SnapshotError):
        match_actual_focus(retained, execution)


@pytest.mark.parametrize("field", ["complete_fact_digest", "complete_findings_digest"])
def test_typed_result_recomputes_full_report_digests(evidence, field):
    _, execution = evidence
    altered = execution.model_copy(update={field: "a" * 64})
    with pytest.raises(ValidationError, match="digest differs from report"):
        FiscalDiagnosticFocusExecutionV1.model_validate_json(
            altered.model_dump_json().encode()
        )


@pytest.mark.parametrize("changed_collection", ["facts", "findings"])
def test_matching_focus_cannot_hide_other_report_changes(evidence, changed_collection):
    retained, execution = evidence
    change = {
        "facts": (*retained.facts, retained.facts[0].model_copy(update={"value": "0"})),
        "findings": (
            *retained.findings,
            ArelleFindingV1(
                code="EFM.extra", severity="warning", message="Extra finding"
            ),
        ),
    }[changed_collection]
    updates = {changed_collection: change}
    if changed_collection == "findings":
        updates["finding_codes"] = ("DQC.US.0015.5970", "EFM.extra")
    changed_report = retained.model_copy(update=updates)

    with pytest.raises(SnapshotError) as failure:
        match_actual_focus(changed_report, execution)
    assert failure.value.code == "FISCAL_FOCUS_REPORT_MISMATCH"


def test_parse_only_observations_cannot_match_even_when_identical(evidence):
    retained, execution = evidence
    profile = ArelleValidationProfileV1(profile_id="parse-only")
    changes = {
        "validation_profile": profile,
        "validation_profile_digest": profile.digest(),
    }
    with pytest.raises(SnapshotError) as failure:
        match_actual_focus(
            retained.model_copy(update=changes),
            _execution(execution.report.model_copy(update=changes), execution.events),
        )
    assert failure.value.code == "SEC_VALIDATION_REQUIRED"


def test_future_and_unknown_target_dates_cannot_match(evidence):
    retained, execution = evidence
    earlier = _FILING_CONTEXT.model_copy(update={"filing_date": date(2016, 1, 1)})
    with pytest.raises(SnapshotError) as failure:
        _match_actual_focus(retained, execution, filing_context=earlier)
    assert failure.value.code == "FISCAL_FOCUS_FINDING_INVALID"

    undated = retained.findings[0].model_copy(update={"rule_effective_date": None})
    changes = {"findings": (undated,)}
    with pytest.raises(SnapshotError) as failure:
        match_actual_focus(
            retained.model_copy(update=changes),
            _execution(execution.report.model_copy(update=changes), execution.events),
        )
    assert failure.value.code == "FISCAL_FOCUS_FINDING_INVALID"


@pytest.mark.parametrize(
    ("change", "error_code"),
    [
        ("missing_finding", "FISCAL_FOCUS_FINDING_AMBIGUOUS"),
        ("duplicate_finding", "FISCAL_FOCUS_FINDING_AMBIGUOUS"),
        ("second_blocker", "FISCAL_FOCUS_OTHER_BLOCKING_FINDING"),
        ("missing_event", "FISCAL_FOCUS_EVENT_AMBIGUOUS"),
        ("duplicate_event", "FISCAL_FOCUS_EVENT_AMBIGUOUS"),
        ("missing_focus", "FISCAL_FOCUS_OBJECT_AMBIGUOUS"),
        ("duplicate_focus", "FISCAL_FOCUS_OBJECT_AMBIGUOUS"),
        ("wrong_focus", "FISCAL_FOCUS_FACT_MISMATCH"),
    ],
)
def test_rejects_ambiguous_or_unmatched_evidence(evidence, change, error_code):
    retained, replayed = evidence
    (finding,) = retained.findings
    (event,) = replayed.events
    (focus,) = event.facts
    finding_updates = {
        "missing_finding": (),
        "duplicate_finding": (finding, finding),
        "second_blocker": (
            finding,
            ArelleFindingV1(code="EFM.6.1", severity="error", message="EFM error"),
        ),
    }
    findings = finding_updates.get(change, retained.findings)
    updates = {
        "findings": findings,
        "finding_codes": tuple(sorted({item.code for item in findings})),
    }
    retained = retained.model_copy(update=updates)
    event_updates = {
        "missing_focus": (),
        "duplicate_focus": (focus, focus),
        "wrong_focus": (
            focus.model_copy(
                update={"fact": focus.fact.model_copy(update={"context_id": "other"})}
            ),
        ),
    }
    events = {
        "missing_event": (),
        "duplicate_event": (event, event),
    }.get(
        change,
        (event.model_copy(update={"facts": event_updates.get(change, event.facts)}),),
    )
    execution = _execution(replayed.report.model_copy(update=updates), events)

    with pytest.raises(SnapshotError) as failure:
        match_actual_focus(retained, execution)
    assert failure.value.code == error_code


def _run_worker(directory, source_hash, *, seconds=15, slot_directory=None):
    return run_fiscal_diagnostic_focus(
        directory / "filing.xbrl",
        profile=ArelleValidationProfileV1(profile_id="fixture"),
        taxonomy_version="fixture",
        taxonomy_cache_dir=directory,
        source_content_hash=source_hash,
        deadline_at=datetime.now(UTC) + timedelta(seconds=seconds),
        resource_policy=ParserResourcePolicy(slot_directory=slot_directory),
    )


@pytest.fixture
def input_directory(tmp_path):
    (tmp_path / "filing.xbrl").write_bytes(b"fixture input")
    return tmp_path


@pytest.mark.parametrize(
    ("exitcode", "expected"),
    [
        (-signal.SIGKILL, "PARSER_RESOURCE_EXHAUSTED"),
        (-signal.SIGSEGV, "PARSER_RESOURCE_EXHAUSTED"),
        (-signal.SIGXCPU, "PARSER_RESOURCE_EXHAUSTED"),
        (-signal.SIGXFSZ, "FISCAL_FOCUS_OUTPUT_LIMIT"),
        (124, "REQUEST_DEADLINE_EXCEEDED"),
        (1, "FISCAL_FOCUS_VALIDATION_FAILED"),
    ],
)
def test_classifies_worker_exit(monkeypatch, input_directory, exitcode, expected):
    class ExitedProcess:
        pid = 1234

        def start(self):
            return None

        def is_alive(self):
            return False

        def join(self):
            return None

        def close(self):
            return None

    process = ExitedProcess()
    process.exitcode = exitcode

    class Context:
        def Process(self, **kwargs):
            return process

    monkeypatch.setattr(multiprocessing, "get_context", lambda _: Context())
    with pytest.raises(ArelleParserError) as failure:
        _run_worker(input_directory, "0" * 64)
    assert failure.value.code == expected


def _blocked_focus_child_for_lifecycle_test(*args):
    def block(*parser_args):
        scratch = Path(tempfile.gettempdir())
        (Path(parser_args[0]).parent / "worker-ready").write_text(str(scratch))
        while True:
            time.sleep(1)

    # Isolate lifecycle behavior on hosts that cannot enforce RLIMIT_AS.
    worker._require_child_memory_limit = lambda _: None
    worker._parse_in_process = block
    worker._focus_child(*args)


def _run_orphanable_parent(directory, slots):
    worker._focus_child = _blocked_focus_child_for_lifecycle_test
    _run_worker(directory, "0" * 64, seconds=15, slot_directory=slots)


def _wait_until(predicate, *, timeout=8):
    deadline = time.monotonic() + timeout
    while not predicate():
        assert time.monotonic() < deadline
        time.sleep(0.02)


def test_real_spawn_hard_deadline_reclaims_child(monkeypatch, input_directory):
    known_pids = {child.pid for child in multiprocessing.active_children()}
    monkeypatch.setattr(worker, "_focus_child", _blocked_focus_child_for_lifecycle_test)

    with pytest.raises(ArelleParserError) as failure:
        _run_worker(input_directory, "0" * 64, seconds=3)

    assert failure.value.code == "REQUEST_DEADLINE_EXCEEDED"
    scratch = Path((input_directory / "worker-ready").read_text())
    assert not scratch.exists()
    assert {child.pid for child in multiprocessing.active_children()} == known_pids


def test_caller_cancellation_reclaims_running_child(monkeypatch, input_directory):
    known_pids = {child.pid for child in multiprocessing.active_children()}
    ready = input_directory / "worker-ready"
    process_class = multiprocessing.get_context("spawn").Process
    original_join = process_class.join
    cancelled = False

    def interrupt_first_join(process, timeout=None):
        nonlocal cancelled
        if not cancelled:
            cancelled = True
            _wait_until(lambda: ready.exists() and ready.stat().st_size > 0)
            raise KeyboardInterrupt
        return original_join(process, timeout=timeout)

    monkeypatch.setattr(worker, "_focus_child", _blocked_focus_child_for_lifecycle_test)
    monkeypatch.setattr(process_class, "join", interrupt_first_join)
    with pytest.raises(KeyboardInterrupt):
        _run_worker(input_directory, "0" * 64)

    assert not Path(ready.read_text()).exists()
    assert {child.pid for child in multiprocessing.active_children()} == known_pids


def test_abrupt_parent_exit_reclaims_child_scratch_and_shared_slot(input_directory):
    slots = input_directory / "slots"
    ready = input_directory / "worker-ready"
    process = multiprocessing.get_context("spawn").Process(
        target=_run_orphanable_parent, args=(input_directory, slots)
    )
    process.start()
    try:
        _wait_until(lambda: ready.exists() and ready.stat().st_size > 0)
        scratch = Path(ready.read_text())
        assert scratch.is_dir()
        with pytest.raises(ArelleParserError) as failure:
            _claim_parser_process_slot(slots, 1)
        assert failure.value.code == "PARSER_CONCURRENCY_EXHAUSTED"

        process.kill()
        process.join(timeout=3)
        assert process.exitcode == -signal.SIGKILL
        _wait_until(lambda: not scratch.exists())

        def slot_is_released():
            try:
                slot = _claim_parser_process_slot(slots, 1)
            except ArelleParserError as error:
                assert error.code == "PARSER_CONCURRENCY_EXHAUSTED"
                return False
            assert slot is not None
            os.close(slot)
            return True

        _wait_until(slot_is_released)
    finally:
        if process.is_alive():
            process.kill()
            process.join(timeout=3)
        process.close()


def _write_controlled_result(result, *args):
    output = args[0]
    os.write(output.fileno(), result)


@pytest.mark.parametrize(
    ("result", "expected"),
    [
        (b"invalid result", "FISCAL_FOCUS_RESULT_INVALID"),
        (b"0" * 128, "FISCAL_FOCUS_OUTPUT_LIMIT"),
    ],
)
def test_rejects_malformed_or_over_budget_child_bytes(
    monkeypatch, input_directory, result, expected
):
    monkeypatch.setattr(
        worker, "_focus_child", partial(_write_controlled_result, result)
    )
    monkeypatch.setattr(worker, "_MAX_CHILD_RESULT_BYTES", 64)
    with pytest.raises(ArelleParserError) as failure:
        _run_worker(input_directory, "0" * 64)
    assert failure.value.code == expected


def _controlled_memory_limits_child(limits, execution, *args):
    import resource

    getrlimit = resource.getrlimit

    def controlled_getrlimit(limit):
        return limits if limit == resource.RLIMIT_AS else getrlimit(limit)

    resource.getrlimit = controlled_getrlimit
    worker._apply_worker_memory_limit = lambda _: None
    worker._observe_validation = lambda *_: execution
    worker._focus_child(*args)


@pytest.mark.parametrize(
    ("soft_offset", "hard_offset", "should_run"),
    [
        (None, None, False),
        (None, 0, False),
        (0, None, False),
        (1, 0, False),
        (0, 1, False),
        (0, 0, True),
        (-2, -1, True),
    ],
)
def test_worker_requires_bounded_memory_limits(
    monkeypatch, input_directory, evidence, soft_offset, hard_offset, should_run
):
    import resource

    _, execution = evidence
    budget = ParserResourcePolicy().max_memory_bytes
    limits = tuple(
        resource.RLIM_INFINITY if offset is None else budget + offset
        for offset in (soft_offset, hard_offset)
    )
    monkeypatch.setattr(
        worker,
        "_focus_child",
        partial(_controlled_memory_limits_child, limits, execution),
    )

    if should_run:
        assert _run_worker(input_directory, "0" * 64) == execution
    else:
        with pytest.raises(ArelleParserError) as failure:
            _run_worker(input_directory, "0" * 64)
        assert failure.value.code == "FISCAL_FOCUS_MEMORY_LIMIT_UNAVAILABLE"


def _memory_exhaustion_child(*args):
    def exhaustion(max_memory_bytes):
        assert max_memory_bytes == ParserResourcePolicy().max_memory_bytes
        raise MemoryError

    worker._apply_worker_memory_limit = exhaustion
    worker._focus_child(*args)


def test_worker_memory_failure_round_trips_typed_result(monkeypatch, input_directory):
    monkeypatch.setattr(worker, "_focus_child", _memory_exhaustion_child)
    with pytest.raises(ArelleParserError) as failure:
        _run_worker(input_directory, "0" * 64)
    assert failure.value.code == "PARSER_RESOURCE_EXHAUSTED"
