from __future__ import annotations

import errno
import multiprocessing
import os
import signal
import sys
import tempfile
import threading
import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from multiprocessing.connection import Connection
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

from .arelle_parser import (
    _PARSER_DEADLINE_EXIT,
    ArelleParseReportV1,
    ArelleParserError,
    ArelleValidationFailureV1,
    ArelleValidationProfileV1,
    ParsedXbrlFactV1,
    ParserResourcePolicy,
    _apply_worker_memory_limit,
    _claim_parser_process_slot,
    _parse_in_process,
    _parser_slot,
    _watch_parser_parent,
    fact_semantic_digest,
    parser_worker_import_paths,
)
from .dqc_applicability import DqcFilingContextV1
from .parser_computation import logical_profile
from .regulatory_validation import (
    bind_dqc_filing_context,
    require_sec_validation_evidence,
)
from .serialization import sha256_digest
from .snapshots import SnapshotError

_TARGET_DQC_CODE: Literal["DQC.US.0015.5970"] = "DQC.US.0015.5970"
_MAX_CHILD_RESULT_BYTES = 128 * 1024 * 1024
_MAX_FOCUS_EVENTS = 256
_MAX_EVENT_FACTS = 64


class FocusModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class ArelleActualFocusFactV1(FocusModel):
    fact_id: str = Field(min_length=1, max_length=512)
    fact: ParsedXbrlFactV1
    numeric_value: str = Field(
        max_length=256, pattern=r"^[+-]?[0-9]+(?:\.[0-9]+)?(?:[Ee][+-]?[0-9]+)?$"
    )


class ArelleActualFocusEventV1(FocusModel):
    code: Literal["DQC.US.0015.5970"] = _TARGET_DQC_CODE
    level: str = Field(min_length=1, max_length=32)
    facts: tuple[ArelleActualFocusFactV1, ...] = Field(max_length=_MAX_EVENT_FACTS)


class FiscalDiagnosticFocusExecutionV1(FocusModel):
    protocol: Literal["fundamental.fiscal-diagnostic-focus-execution.v1"] = (
        "fundamental.fiscal-diagnostic-focus-execution.v1"
    )
    report: ArelleParseReportV1
    events: tuple[ArelleActualFocusEventV1, ...] = Field(max_length=_MAX_FOCUS_EVENTS)
    complete_fact_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    complete_findings_digest: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def digests_match_report(self) -> FiscalDiagnosticFocusExecutionV1:
        if self.complete_fact_digest != fact_semantic_digest(self.report):
            raise ValueError("complete fact digest differs from report")
        if self.complete_findings_digest != sha256_digest(
            sorted(self.report.findings, key=sha256_digest)
        ):
            raise ValueError("complete finding digest differs from report")
        return self


class _FocusFailure(FocusModel):
    protocol: Literal["fundamental.fiscal-diagnostic-focus-failure.v1"] = (
        "fundamental.fiscal-diagnostic-focus-failure.v1"
    )
    code: str = Field(min_length=1, max_length=128)
    message: str = Field(min_length=1, max_length=512)
    validation_failure: ArelleValidationFailureV1 | None = None


_FocusChildResult = Annotated[
    FiscalDiagnosticFocusExecutionV1 | _FocusFailure, Field(discriminator="protocol")
]
_CHILD_RESULT_ADAPTER: TypeAdapter[_FocusChildResult] = TypeAdapter(_FocusChildResult)


def _fact_from_model_object(value: object) -> ArelleActualFocusFactV1:
    from arelle.ModelInstanceObject import ModelFact, ModelInlineFact

    if not isinstance(value, ModelFact):
        raise ArelleParserError(
            "FISCAL_FOCUS_OBJECT_INVALID", "official DQC focus is not an XBRL fact"
        )
    fact_id = value.id
    concept = value.concept.qname if value.concept is not None else None
    context = value.context
    context_id = value.contextID
    numeric_value: object = getattr(value, "xValue", None)
    if (
        not fact_id
        or concept is None
        or context is None
        or not context_id
        or not value.isNumeric
        or isinstance(numeric_value, bool)
        or not isinstance(numeric_value, (int, float, Decimal))
    ):
        raise ArelleParserError(
            "FISCAL_FOCUS_OBJECT_INVALID",
            "official DQC focus lacks numeric fact identity",
        )

    dimensions: list[tuple[str, str]] = []
    namespaces: list[tuple[str, str | None, str | None]] = []
    for axis, member in sorted(
        context.qnameDims.items(), key=lambda item: str(item[0])
    ):
        explicit_member = member.memberQname
        dimensions.append(
            (
                str(axis),
                str(
                    explicit_member
                    if explicit_member is not None
                    else member.typedMember
                ),
            )
        )
        namespaces.append(
            (
                str(axis),
                axis.namespaceURI,
                explicit_member.namespaceURI if explicit_member is not None else None,
            )
        )
    unit = value.unit
    unit_text = (
        "/".join(
            "*".join(str(measure) for measure in side) for side in unit.measures if side
        )
        if unit is not None
        else None
    )
    entity = context.entityIdentifier
    start = context.startDatetime
    end = context.endDatetime
    instant = context.instantDatetime
    fact = ParsedXbrlFactV1(
        concept=str(concept),
        namespace_uri=str(concept.namespaceURI),
        value=str(value.value),
        context_id=context_id,
        unit=unit_text,
        decimals=str(value.decimals) or None,
        entity_scheme=str(entity[0]) if entity else None,
        entity_identifier=str(entity[1]) if entity else None,
        period_start=start.date() if start is not None else None,
        period_end=(end - timedelta(days=1)).date()
        if end is not None and start is not None
        else None,
        instant=(instant - timedelta(days=1)).date() if instant is not None else None,
        dimensions=tuple(dimensions),
        dimension_namespace_uris=tuple(namespaces),
        is_numeric=True,
        scale=int(value.scale or 0) if isinstance(value, ModelInlineFact) else 0,
        consolidation_scope="segmented" if dimensions else "consolidated",
        security_scope="segmented" if dimensions else "unspecified",
    )
    return ArelleActualFocusFactV1(
        fact_id=fact_id,
        fact=fact,
        numeric_value=str(numeric_value),
    )


def _model_objects(value: object) -> tuple[object, ...]:
    if value is None:
        return ()
    if isinstance(value, (tuple, list, set, frozenset)):
        return tuple(value)
    return (value,)


def _focus_child(
    result_file: Connection,
    filing_path: str,
    profile_data: bytes,
    taxonomy_version: str,
    taxonomy_cache_dir: str,
    expected_source_hash: str,
    max_memory_bytes: int,
    slot_directory: str | None,
    max_concurrency: int,
    deadline_at: datetime,
    scratch_directory: str,
) -> None:
    try:
        sys.path[:] = parser_worker_import_paths()
        tempfile.tempdir = scratch_directory
        parent = multiprocessing.parent_process()
        if parent is None:
            raise ArelleParserError(
                "PARSER_PROCESS_START_FAILED", "focus worker requires its caller"
            )
        threading.Thread(
            target=_watch_parser_parent,
            args=(parent.sentinel, deadline_at, scratch_directory),
            daemon=True,
        ).start()
        _claim_parser_process_slot(
            Path(slot_directory) if slot_directory else None, max_concurrency
        )
        _require_child_memory_limit(max_memory_bytes)
        _limit_child_files()
        execution = _observe_validation(
            Path(filing_path),
            ArelleValidationProfileV1.model_validate_json(profile_data),
            taxonomy_version,
            Path(taxonomy_cache_dir),
            expected_source_hash,
        )
        _write_child_result(result_file, execution)
    except MemoryError:
        _write_child_result(
            result_file,
            _FocusFailure(
                code="PARSER_RESOURCE_EXHAUSTED",
                message="focus child exceeded its memory budget",
            ),
        )
    except ArelleParserError as error:
        _write_child_result(
            result_file,
            _FocusFailure(
                code=error.code,
                message=(str(error) or error.code)[:512],
                validation_failure=error.validation_failure,
            ),
        )
    except SnapshotError as error:
        _write_child_result(
            result_file,
            _FocusFailure(code=error.code, message=(str(error) or error.code)[:512]),
        )
    except Exception:
        _write_child_result(
            result_file,
            _FocusFailure(
                code="FISCAL_FOCUS_VALIDATION_FAILED",
                message="official focus worker could not complete validation",
            ),
        )


def _require_child_memory_limit(max_memory_bytes: int) -> None:
    try:
        import resource

        _apply_worker_memory_limit(max_memory_bytes)
        limits = resource.getrlimit(resource.RLIMIT_AS)
        if any(
            limit == resource.RLIM_INFINITY or not 0 <= limit <= max_memory_bytes
            for limit in limits
        ):
            raise ValueError("focus child memory limits exceed the policy")
    except (
        ArelleParserError,
        AttributeError,
        ImportError,
        OSError,
        ValueError,
    ) as error:
        raise ArelleParserError(
            "FISCAL_FOCUS_MEMORY_LIMIT_UNAVAILABLE",
            "focus child could not enforce its memory budget",
        ) from error


def _limit_child_files() -> None:
    try:
        import resource

        _, hard = resource.getrlimit(resource.RLIMIT_FSIZE)
        limit = (
            _MAX_CHILD_RESULT_BYTES
            if hard == resource.RLIM_INFINITY
            else min(hard, _MAX_CHILD_RESULT_BYTES)
        )
        resource.setrlimit(resource.RLIMIT_FSIZE, (limit, limit))
    except (ImportError, OSError, ValueError) as error:
        raise ArelleParserError(
            "FISCAL_FOCUS_OUTPUT_LIMIT_UNAVAILABLE",
            "focus child could not limit its output file",
        ) from error


def _write_child_result(result_file: Connection, result: _FocusChildResult) -> None:
    payload = _CHILD_RESULT_ADAPTER.dump_json(result)
    if len(payload) > _MAX_CHILD_RESULT_BYTES:
        raise ArelleParserError(
            "FISCAL_FOCUS_OUTPUT_LIMIT", "focus child result exceeds its byte limit"
        )
    try:
        with os.fdopen(os.dup(result_file.fileno()), "wb") as output:
            output.seek(0)
            output.truncate()
            output.write(payload)
    except OSError as error:
        if error.errno == errno.EFBIG:
            raise ArelleParserError(
                "FISCAL_FOCUS_OUTPUT_LIMIT", "focus child result exceeds its byte limit"
            ) from error
        raise


def _observe_validation(
    filing_path: Path,
    profile: ArelleValidationProfileV1,
    taxonomy_version: str,
    taxonomy_cache_dir: Path,
    expected_source_hash: str,
) -> FiscalDiagnosticFocusExecutionV1:
    import socket

    from arelle import ModelXbrl

    network_attempts = 0
    events: list[ArelleActualFocusEventV1] = []
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex
    original_log = ModelXbrl.ModelXbrl.log

    def block_network(*args: object, **kwargs: object) -> None:
        nonlocal network_attempts
        network_attempts += 1
        raise OSError("offline Arelle worker attempted network access")

    def observe(
        model: ModelXbrl.ModelXbrl,
        level: str,
        codes: object,
        msg: str,
        **parameters: object,
    ) -> None:
        if codes == _TARGET_DQC_CODE:
            if len(events) >= _MAX_FOCUS_EVENTS:
                raise ArelleParserError(
                    "FISCAL_FOCUS_OUTPUT_LIMIT", "too many target DQC events"
                )
            objects = _model_objects(parameters.get("modelObject"))
            if len(objects) > _MAX_EVENT_FACTS:
                raise ArelleParserError(
                    "FISCAL_FOCUS_OUTPUT_LIMIT",
                    "too many focus objects in the DQC event",
                )
            events.append(
                ArelleActualFocusEventV1(
                    level=level.upper(),
                    facts=tuple(_fact_from_model_object(item) for item in objects),
                )
            )
        original_log(model, level, codes, msg, **parameters)

    setattr(socket.socket, "connect", block_network)
    setattr(socket.socket, "connect_ex", block_network)
    setattr(ModelXbrl.ModelXbrl, "log", observe)
    try:
        report = _parse_in_process(
            filing_path,
            profile,
            taxonomy_version,
            taxonomy_cache_dir,
            expected_source_hash,
        )
        require_sec_validation_evidence(report)
        return FiscalDiagnosticFocusExecutionV1(
            report=report,
            events=tuple(events),
            complete_fact_digest=fact_semantic_digest(report),
            complete_findings_digest=sha256_digest(
                sorted(report.findings, key=sha256_digest)
            ),
        )
    finally:
        setattr(socket.socket, "connect", original_connect)
        setattr(socket.socket, "connect_ex", original_connect_ex)
        setattr(ModelXbrl.ModelXbrl, "log", original_log)
        if network_attempts:
            raise ArelleParserError(
                "OFFLINE_NETWORK_ATTEMPT", "offline Arelle attempted network access"
            )


def run_fiscal_diagnostic_focus(
    filing_path: Path,
    *,
    profile: ArelleValidationProfileV1,
    taxonomy_version: str,
    taxonomy_cache_dir: Path,
    source_content_hash: str,
    deadline_at: datetime,
    resource_policy: ParserResourcePolicy | None = None,
) -> FiscalDiagnosticFocusExecutionV1:
    """Repeat full official validation and return only typed actual-focus evidence."""
    policy = (resource_policy or ParserResourcePolicy.from_env()).validate()
    if not filing_path.is_file() or not taxonomy_cache_dir.is_dir():
        raise SnapshotError(
            "FISCAL_FOCUS_INPUT_UNAVAILABLE", "retained parser inputs are unavailable"
        )
    if deadline_at.tzinfo is None or deadline_at.utcoffset() is None:
        raise ValueError("focus deadline must include a timezone")
    if datetime.now(UTC) >= deadline_at:
        raise ArelleParserError(
            "REQUEST_DEADLINE_EXCEEDED", "focus deadline expired before validation"
        )
    monotonic_deadline = (
        time.monotonic() + (deadline_at - datetime.now(UTC)).total_seconds()
    )
    with (
        _parser_slot(policy.max_concurrency),
        tempfile.TemporaryDirectory(prefix="fundamental-fiscal-focus-") as scratch,
        tempfile.TemporaryFile() as output,
        Connection(os.dup(output.fileno())) as result_file,
    ):
        process = multiprocessing.get_context("spawn").Process(
            target=_focus_child,
            args=(
                result_file,
                str(filing_path),
                profile.model_dump_json().encode(),
                taxonomy_version,
                str(taxonomy_cache_dir),
                source_content_hash,
                policy.max_memory_bytes,
                str(policy.slot_directory) if policy.slot_directory else None,
                policy.max_concurrency,
                deadline_at,
                scratch,
            ),
            daemon=True,
        )
        try:
            try:
                process.start()
            except OSError as error:
                raise ArelleParserError(
                    "PARSER_PROCESS_START_FAILED", "focus worker could not start"
                ) from error
            while process.is_alive():
                remaining = monotonic_deadline - time.monotonic()
                if remaining <= 0:
                    raise ArelleParserError(
                        "REQUEST_DEADLINE_EXCEEDED",
                        "official fiscal focus validation exceeded its deadline",
                    )
                process.join(timeout=min(0.1, remaining))
            if (
                process.exitcode == _PARSER_DEADLINE_EXIT
                or time.monotonic() >= monotonic_deadline
            ):
                raise ArelleParserError(
                    "REQUEST_DEADLINE_EXCEEDED",
                    "official fiscal focus validation exceeded its deadline",
                )
            if process.exitcode in {-signal.SIGKILL, -signal.SIGSEGV, -signal.SIGXCPU}:
                raise ArelleParserError(
                    "PARSER_RESOURCE_EXHAUSTED",
                    "focus worker exceeded its resource budget",
                )
            if process.exitcode == -signal.SIGXFSZ:
                raise ArelleParserError(
                    "FISCAL_FOCUS_OUTPUT_LIMIT",
                    "focus child result exceeds its byte limit",
                )
            if process.exitcode != 0:
                raise ArelleParserError(
                    "FISCAL_FOCUS_VALIDATION_FAILED",
                    "official focus worker exited without a result",
                )
            try:
                output.seek(0)
                payload = output.read(_MAX_CHILD_RESULT_BYTES + 1)
            except OSError as error:
                raise ArelleParserError(
                    "FISCAL_FOCUS_RESULT_INVALID", "focus worker result is unreadable"
                ) from error
            if len(payload) > _MAX_CHILD_RESULT_BYTES:
                raise ArelleParserError(
                    "FISCAL_FOCUS_OUTPUT_LIMIT",
                    "focus child result exceeds its byte limit",
                )
            try:
                result = _CHILD_RESULT_ADAPTER.validate_json(payload)
            except ValueError as error:
                raise ArelleParserError(
                    "FISCAL_FOCUS_RESULT_INVALID",
                    "focus worker returned invalid evidence",
                ) from error
            if time.monotonic() >= monotonic_deadline:
                raise ArelleParserError(
                    "REQUEST_DEADLINE_EXCEEDED",
                    "official fiscal focus validation exceeded its deadline",
                )
            if isinstance(result, _FocusFailure):
                raise ArelleParserError(
                    result.code,
                    result.message,
                    validation_failure=result.validation_failure,
                )
            return result
        finally:
            if process.pid is not None:
                if process.is_alive():
                    process.terminate()
                    process.join(timeout=0.2)
                    if process.is_alive():
                        process.kill()
                        process.join(timeout=0.2)
                if not process.is_alive():
                    process.join()
            if not process.is_alive():
                process.close()


def _match_actual_focus(
    report: ArelleParseReportV1,
    execution: FiscalDiagnosticFocusExecutionV1,
    *,
    filing_context: DqcFilingContextV1,
) -> ArelleActualFocusFactV1:
    replayed = execution.report
    for candidate in (report, replayed):
        require_sec_validation_evidence(candidate)
        if (
            not candidate.offline
            or not candidate.validation_profile.offline
            or candidate.source_content_hash is None
            or candidate.taxonomy_cache_hash is None
            or candidate.parser_version != candidate.validation_profile.arelle_version
            or candidate.validation_profile_digest
            != candidate.validation_profile.digest()
            or candidate.validation_profile.dqc_version != filing_context.dqc_version
            or candidate.validation_profile.dqc_applicability_digest
            != filing_context.policy_digest
            or set(candidate.finding_codes)
            != {finding.code for finding in candidate.findings}
        ):
            raise SnapshotError(
                "FISCAL_FOCUS_REPORT_MISMATCH",
                "incomplete or inconsistent validation report",
            )
    bound_report = bind_dqc_filing_context(report, filing_context)
    bound_replay = bind_dqc_filing_context(replayed, filing_context)
    if fact_semantic_digest(report) != execution.complete_fact_digest:
        raise SnapshotError("FISCAL_FOCUS_REPORT_MISMATCH", "complete facts differ")
    if (
        sha256_digest(sorted(report.findings, key=sha256_digest))
        != execution.complete_findings_digest
    ):
        raise SnapshotError("FISCAL_FOCUS_REPORT_MISMATCH", "complete findings differ")
    if (
        logical_profile(report.validation_profile)
        != logical_profile(replayed.validation_profile)
        or bound_report.replay_digest() != bound_replay.replay_digest()
    ):
        raise SnapshotError(
            "FISCAL_FOCUS_REPORT_MISMATCH", "replayed validation differs"
        )
    findings = tuple(item for item in report.findings if item.code == _TARGET_DQC_CODE)
    if len(findings) != 1 or findings[0].rule_severity != "error":
        raise SnapshotError(
            "FISCAL_FOCUS_FINDING_AMBIGUOUS", "target finding is not unique"
        )
    if findings[0].severity != "warning":
        raise SnapshotError(
            "FISCAL_FOCUS_FINDING_INVALID", "raw target severity differs"
        )
    applicability = bound_report.finding_applicability(findings[0])
    if applicability is None or applicability.status != "active":
        raise SnapshotError(
            "FISCAL_FOCUS_FINDING_INVALID", "target diagnostic is not active"
        )
    blocking = bound_report.blocking_finding_codes()
    if set(blocking) != {_TARGET_DQC_CODE}:
        raise SnapshotError(
            "FISCAL_FOCUS_OTHER_BLOCKING_FINDING", "another finding blocks"
        )
    if len(execution.events) != 1 or execution.events[0].level != "ERROR":
        raise SnapshotError(
            "FISCAL_FOCUS_EVENT_AMBIGUOUS", "target event is not unique"
        )
    event = execution.events[0]
    if len(event.facts) != 1:
        raise SnapshotError(
            "FISCAL_FOCUS_OBJECT_AMBIGUOUS", "target focus is not unique"
        )
    focus = event.facts[0]
    matches = tuple(fact for fact in report.facts if fact == focus.fact)
    if len(matches) != 1 or not focus.fact.is_numeric:
        raise SnapshotError(
            "FISCAL_FOCUS_FACT_MISMATCH", "actual focus differs from report"
        )
    return focus
