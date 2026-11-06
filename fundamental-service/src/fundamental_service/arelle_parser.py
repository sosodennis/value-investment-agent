"""Pinned Arelle boundary for offline filing validation and XBRL extraction."""

from __future__ import annotations

import hashlib
import multiprocessing
import os
import queue
import sys
import tempfile
import threading
import time
from datetime import date, datetime, timedelta, timezone
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .serialization import sha256_digest

_NON_BLOCKING_ARELLE_CODES = frozenset(
    {
        "ix11.10.1.2:invalidTransformation",
        "ix11.11.1.2:invalidTransformation",
    }
)
_PLUGIN_ROOT_LOCK = threading.Lock()
_PLUGIN_ROOTS: dict[str, tuple[tempfile.TemporaryDirectory[str], Path]] = {}


class ArelleParserError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class ArelleValidationProfileV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    arelle_version: str = "2.47.4"
    efm_release: str = "26.3"
    efm_validation_version: str = "1.26.3"
    efm_profile: str = "efm-strict-all-years"
    dqc_version: str = "v31.0.3"
    xule_version: str = "30055"
    offline: bool = True
    validation_mode: Literal["parse-only", "sec-efm-dqc"] = "parse-only"
    profile_id: str = Field(min_length=1)
    edgar_plugin_dir: Path | None = None
    xule_plugin_dir: Path | None = None
    dqc_ruleset_path: Path | None = None
    edgar_plugin_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    xule_plugin_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    dqc_ruleset_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def pinned_runtime(self) -> "ArelleValidationProfileV1":
        if self.arelle_version != "2.47.4":
            raise ValueError("Arelle version must be pinned to 2.47.4")
        if self.efm_profile != "efm-strict-all-years":
            raise ValueError("SEC validation requires strict all-years EFM")
        if self.dqc_version != "v31.0.3" or self.xule_version != "30055":
            raise ValueError("SEC validation profile versions are not pinned")
        if not self.offline:
            raise ValueError("offline parser profile must set offline=true")
        configured = (
            self.edgar_plugin_dir,
            self.xule_plugin_dir,
            self.dqc_ruleset_path,
            self.edgar_plugin_sha256,
            self.xule_plugin_sha256,
            self.dqc_ruleset_sha256,
        )
        if any(item is not None for item in configured) and not all(
            item is not None for item in configured
        ):
            raise ValueError(
                "validation plugin paths and hashes must be pinned together"
            )
        if self.validation_mode == "sec-efm-dqc" and not all(
            item is not None for item in configured
        ):
            raise ValueError(
                "SEC EFM/DQC validation requires pinned plugin paths and hashes"
            )
        return self

    def digest(self) -> str:
        payload = self.model_dump(mode="json")
        for name in ("edgar_plugin_dir", "xule_plugin_dir", "dqc_ruleset_path"):
            if payload[name] is not None:
                payload[name] = Path(payload[name]).name
        return sha256_digest(payload)


class ParsedXbrlFactV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    concept: str = Field(min_length=1)
    value: str
    context_id: str = Field(min_length=1)
    unit: str | None = None
    decimals: str | None = None
    entity_scheme: str | None = None
    entity_identifier: str | None = None
    period_start: date | None = None
    period_end: date | None = None
    instant: date | None = None
    dimensions: tuple[tuple[str, str], ...] = ()
    is_numeric: bool = False
    scale: int = 0
    consolidation_scope: str = "unknown"
    security_scope: str = "unknown"


class ArelleFindingV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str = Field(min_length=1)
    severity: str = Field(min_length=1)
    message: str = Field(min_length=1)


class ArelleParseReportV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    filing_path: str = Field(min_length=1)
    parser_version: str = Field(min_length=1)
    taxonomy_version: str = Field(min_length=1)
    validation_profile: ArelleValidationProfileV1
    validation_profile_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    facts: tuple[ParsedXbrlFactV1, ...] = ()
    findings: tuple[ArelleFindingV1, ...] = ()
    finding_codes: tuple[str, ...] = ()
    validation_engines: tuple[str, ...] = ()
    validation_evidence: tuple[str, ...] = ()
    parsed_at: datetime
    offline: bool = True
    network_attempt_count: int = Field(default=0, ge=0)
    source_content_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    taxonomy_cache_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    def blocking_finding_codes(self) -> tuple[str, ...]:
        if not self.findings:
            # Older persisted reports contain only codes. Treat every such
            # code as blocking; only current reports may carry explicit
            # severity evidence.
            return tuple(sorted(set(self.finding_codes)))
        return tuple(
            sorted(
                {
                    finding.code
                    for finding in self.findings
                    if finding.severity in {"error", "critical", "fatal"}
                    and finding.code not in _NON_BLOCKING_ARELLE_CODES
                }
            )
        )

    def replay_digest(self) -> str:
        facts = sorted(
            (fact.model_dump(mode="json") for fact in self.facts),
            key=lambda fact: sha256_digest(fact),
        )
        findings = sorted(
            (finding.model_dump(mode="json") for finding in self.findings),
            key=lambda finding: sha256_digest(finding),
        )
        return sha256_digest(
            {
                "parser_version": self.parser_version,
                "taxonomy_version": self.taxonomy_version,
                "validation_profile_digest": self.validation_profile_digest,
                "source_content_hash": self.source_content_hash,
                "taxonomy_cache_hash": self.taxonomy_cache_hash,
                "facts": facts,
                "findings": findings,
                "validation_engines": self.validation_engines,
                "validation_evidence": self.validation_evidence,
                "offline": self.offline,
                "network_attempt_count": self.network_attempt_count,
            }
        )


def fact_semantic_digest(report: ArelleParseReportV1) -> str:
    """Digest XBRL fact meaning without parser paths or run-time timestamps."""
    facts = sorted(
        (fact.model_dump(mode="json") for fact in report.facts),
        key=lambda fact: sha256_digest(fact),
    )
    return sha256_digest({"fact_count": len(facts), "facts": facts})


def _directory_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(
        path
        for path in root.rglob("*")
        if path.is_file()
        and "__pycache__" not in path.relative_to(root).parts
        and path.suffix not in {".pyc", ".pyo"}
    ):
        digest.update(str(path.relative_to(root)).encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _validation_plugin_root(profile: "ArelleValidationProfileV1") -> Path:
    assert profile.edgar_plugin_dir and profile.xule_plugin_dir
    cache_key = hashlib.sha256(
        f"{profile.edgar_plugin_sha256}:{profile.xule_plugin_sha256}".encode()
    ).hexdigest()
    with _PLUGIN_ROOT_LOCK:
        cached = _PLUGIN_ROOTS.get(cache_key)
        if cached is not None:
            return cached[1]
        config_root = tempfile.TemporaryDirectory(
            prefix=f"fundamental-arelle-{cache_key[:12]}-"
        )
        plugin_root = Path(config_root.name) / "plugins"
        plugin_root.mkdir()
        (plugin_root / "EDGAR").symlink_to(
            profile.edgar_plugin_dir, target_is_directory=True
        )
        (plugin_root / "xule").symlink_to(
            profile.xule_plugin_dir / "xule", target_is_directory=True
        )
        (plugin_root / "validate").mkdir()
        (plugin_root / "validate" / "DQC.py").symlink_to(
            profile.xule_plugin_dir / "validate" / "DQC.py"
        )
        _PLUGIN_ROOTS[cache_key] = (config_root, plugin_root)
        return plugin_root


def _finding_from_log(record: dict[str, Any]) -> ArelleFindingV1 | None:
    level = str(record.get("level", "")).lower()
    if level not in {"error", "critical", "warning", "fatal"}:
        return None
    code = str(record.get("code") or "arelle:unknown")
    if code in _NON_BLOCKING_ARELLE_CODES:
        level = "warning"
    message = record.get("message")
    if isinstance(message, dict):
        message_text = str(message.get("text") or code)
    else:
        message_text = str(message or code)
    return ArelleFindingV1(code=code, severity=level, message=message_text[:2048])


def _unlogged_model_error_findings(
    model_errors: tuple[str, ...], logged_codes: set[str]
) -> tuple[ArelleFindingV1, ...]:
    return tuple(
        ArelleFindingV1(
            code=code,
            severity="warning" if code in _NON_BLOCKING_ARELLE_CODES else "error",
            message=(
                "Arelle reported a known non-blocking Inline XBRL "
                "transformation diagnostic."
                if code in _NON_BLOCKING_ARELLE_CODES
                else "Arelle reported a model error without a corresponding log record."
            ),
        )
        for code in model_errors
        if code not in logged_codes
    )


def _dqc_validation_completed(handler: Any, records: tuple[Any, ...]) -> bool:
    for record in records:
        entry = handler.recordToJson(record)
        code = str(entry.get("code") or "")
        if code.startswith("DQC"):
            return True
        message = entry.get("message")
        details = message.get("args") if isinstance(message, dict) else None
        if (
            code == "info:profileActivity"
            and isinstance(details, dict)
            and details.get("activity") == "... DQCRT checks"
        ):
            return True
    return False


def _parse_worker(
    result_queue: multiprocessing.Queue,
    filing_path: str,
    profile_data: dict[str, Any],
    taxonomy_version: str,
    taxonomy_cache_dir: str | None,
    expected_source_hash: str | None,
) -> None:
    attempted_network = 0
    bytecode_cache: tempfile.TemporaryDirectory[str] | None = None
    try:
        bytecode_cache = tempfile.TemporaryDirectory(
            prefix="fundamental-arelle-pycache-"
        )
        sys.pycache_prefix = bytecode_cache.name
        import socket

        def block_network(*args: Any, **kwargs: Any) -> None:
            nonlocal attempted_network
            attempted_network += 1
            raise OSError("offline Arelle worker attempted network access")

        socket.socket.connect = block_network
        socket.socket.connect_ex = block_network
        report = _parse_in_process(
            Path(filing_path),
            ArelleValidationProfileV1.model_validate(profile_data),
            taxonomy_version,
            Path(taxonomy_cache_dir) if taxonomy_cache_dir else None,
            expected_source_hash,
        )
        result_queue.put(
            report.model_copy(
                update={"network_attempt_count": attempted_network}
            ).model_dump(mode="json")
        )
    except Exception as error:
        result_queue.put(
            {
                "error": getattr(error, "code", "XBRL_PARSE_FAILED"),
                "message": str(error),
                "network_attempt_count": attempted_network,
            }
        )
    finally:
        if bytecode_cache is not None:
            bytecode_cache.cleanup()


def _parse_in_process(
    filing_path: Path,
    profile: ArelleValidationProfileV1,
    taxonomy_version: str,
    taxonomy_cache_dir: Path | None,
    source_content_hash: str | None,
) -> ArelleParseReportV1:
    if not filing_path.is_file():
        raise ArelleParserError("FILING_BYTES_UNAVAILABLE", str(filing_path))
    actual_source_hash = hashlib.sha256(filing_path.read_bytes()).hexdigest()
    if source_content_hash is not None and source_content_hash != actual_source_hash:
        raise ArelleParserError(
            "SOURCE_HASH_MISMATCH", "parser bytes do not match source manifest"
        )
    try:
        installed_version = version("arelle-release")
    except PackageNotFoundError as error:
        raise ArelleParserError(
            "ARELLE_UNAVAILABLE", "arelle-release==2.47.4 is required"
        ) from error
    if installed_version != profile.arelle_version:
        raise ArelleParserError(
            "ARELLE_VERSION_MISMATCH",
            f"installed Arelle {installed_version} does not match "
            f"{profile.arelle_version}",
        )
    if filing_path.suffix.lower() in {".htm", ".html"} and taxonomy_cache_dir is None:
        raise ArelleParserError(
            "TAXONOMY_CACHE_REQUIRED",
            "inline SEC filings require a captured taxonomy cache for offline parsing",
        )

    validation_paths = (
        profile.edgar_plugin_dir,
        profile.xule_plugin_dir,
        profile.dqc_ruleset_path,
        profile.edgar_plugin_sha256,
        profile.xule_plugin_sha256,
        profile.dqc_ruleset_sha256,
    )
    has_validation_resources = all(item is not None for item in validation_paths)
    if (
        any(item is not None for item in validation_paths)
        and not has_validation_resources
    ):
        raise ArelleParserError(
            "VALIDATION_RESOURCES_UNAVAILABLE",
            "validation resources are not fully pinned",
        )
    if profile.validation_mode == "sec-efm-dqc" and not has_validation_resources:
        raise ArelleParserError(
            "VALIDATION_RESOURCES_UNAVAILABLE",
            "SEC validation plugins and DQC rules are required",
        )
    validation_enabled = profile.validation_mode == "sec-efm-dqc"
    if has_validation_resources:
        assert (
            profile.edgar_plugin_dir
            and profile.xule_plugin_dir
            and profile.dqc_ruleset_path
        )
        actual_hashes = (
            _directory_hash(profile.edgar_plugin_dir),
            _directory_hash(profile.xule_plugin_dir),
            hashlib.sha256(profile.dqc_ruleset_path.read_bytes()).hexdigest()
            if profile.dqc_ruleset_path.is_file()
            else "",
        )
        if actual_hashes != (
            profile.edgar_plugin_sha256,
            profile.xule_plugin_sha256,
            profile.dqc_ruleset_sha256,
        ):
            raise ArelleParserError(
                "VALIDATION_RESOURCE_HASH_MISMATCH",
                "pinned EFM/DQC resource hash does not match",
            )

    manager = None
    findings: tuple[ArelleFindingV1, ...] = ()
    validation_engines: tuple[str, ...] = ()
    validation_evidence: tuple[str, ...] = ()
    try:
        if validation_enabled:
            from arelle.CntlrCmdLine import CntlrCmdLine, ParserForDynamicPlugins
            from arelle.logging.handlers.LogToXmlHandler import LogToXmlHandler
            from arelle.RuntimeOptions import RuntimeOptions

            controller = CntlrCmdLine(disable_persistent_config=True)
            plugin_root = _validation_plugin_root(profile)
            controller._pluginManager._pluginBase = str(plugin_root) + os.sep
            dqc_plugin = controller._pluginManager.addPluginModule("validate/DQC")
            if dqc_plugin is None:
                raise ArelleParserError(
                    "DQC_PLUGIN_UNAVAILABLE", "pinned DQC plugin did not load"
                )
            edgar_plugin = controller._pluginManager.addPluginModule("EDGAR/validate")
            if edgar_plugin is None:
                raise ArelleParserError(
                    "EFM_PLUGIN_UNAVAILABLE", "pinned SEC EFM plugin did not load"
                )
            # Cntlr initializes ModelManager before these modules are registered,
            # which caches an empty DisclosureSystem.Types hook list.
            controller._pluginManager.pluginMethodsForClasses.clear()
            controller.preloadedPlugins = {
                "validate/DQC": dqc_plugin,
                "EDGAR/validate": edgar_plugin,
            }
            controller.startLogging(logHandler=LogToXmlHandler(controller))
            options = RuntimeOptions(
                pluginOptions={
                    "xule_rule_set": str(profile.dqc_ruleset_path),
                    "xule_multi": False,
                    "xule_bypass_packages": False,
                },
                entrypointFile=str(filing_path),
                plugins="EDGAR/validate|validate/DQC",
                validate=True,
                disclosureSystemName=profile.efm_profile,
                workOffline=True,
                cacheDirectory=str(taxonomy_cache_dir)
                if taxonomy_cache_dir is not None
                else None,
                keepOpen=True,
                disablePersistentConfig=True,
                logLevel="DEBUG",
            )
            for extender in controller.plugins.hooks("CntlrCmdLine.Options"):
                extender(ParserForDynamicPlugins(options))
            controller.postLoggingInit()
            if not controller.run(options):
                raise ArelleParserError(
                    "XBRL_PARSE_FAILED", "Arelle command-line validation failed"
                )
            manager = controller.modelManager
            model = manager.modelXbrl
        else:
            from arelle import Cntlr, ModelManager

            controller = Cntlr.Cntlr(logFileName=None, disable_persistent_config=True)
            manager = ModelManager.initialize(controller)
            controller.modelManager = manager
            if profile.offline and hasattr(controller, "webCache"):
                controller.webCache.workOffline = True
                if taxonomy_cache_dir is not None:
                    if not taxonomy_cache_dir.is_dir():
                        raise ArelleParserError(
                            "TAXONOMY_CACHE_UNAVAILABLE", str(taxonomy_cache_dir)
                        )
                    controller.webCache.cacheDir = str(taxonomy_cache_dir)
            model = manager.load(str(filing_path))
        if model is None:
            raise ArelleParserError("XBRL_PARSE_FAILED", "Arelle returned no model")
        model_errors = tuple(sorted({str(code) for code in model.errors}))
        if validation_enabled:
            disclosure_system = controller.modelManager.disclosureSystem
            if (
                disclosure_system.name
                != "US SEC (Edgar Filing Manual, Strict, all years)"
                or not getattr(disclosure_system, "EFMplugin", False)
            ):
                raise ArelleParserError(
                    "EFM_PROFILE_UNAVAILABLE", "strict SEC EFM profile is not available"
                )
            handler = controller.logHandler
            records = getattr(handler, "logRecordBuffer", ())
            findings = tuple(
                item
                for record in records
                if (item := _finding_from_log(handler.recordToJson(record))) is not None
            )
            logged_codes = {item.code for item in findings}
            findings += _unlogged_model_error_findings(model_errors, logged_codes)
            if not _dqc_validation_completed(handler, records):
                raise ArelleParserError(
                    "DQC_VALIDATION_UNAVAILABLE", "DQC rules did not run"
                )
            validation_engines = ("sec-efm", "dqc-us")
            validation_evidence = (
                "strict-sec-efm-profile-selected",
                "dqc-dqcrt-checks-completed",
            )
        else:
            blocking_model_errors = tuple(
                code for code in model_errors if code not in _NON_BLOCKING_ARELLE_CODES
            )
            if blocking_model_errors:
                raise ArelleParserError(
                    "XBRL_PARSE_FAILED",
                    "Arelle could not load the filing DTS: "
                    + ", ".join(blocking_model_errors),
                )
        facts: list[ParsedXbrlFactV1] = []
        for fact in getattr(model, "facts", ()):
            concept = getattr(getattr(fact, "concept", None), "qname", None)
            context = getattr(fact, "contextID", None)
            if concept is None or context is None:
                continue
            model_context = getattr(fact, "context", None)
            entity_identifier = getattr(model_context, "entityIdentifier", None)
            start_datetime = getattr(model_context, "startDatetime", None)
            end_datetime = getattr(model_context, "endDatetime", None)
            instant_datetime = getattr(model_context, "instantDatetime", None)
            period_end = (
                (end_datetime - timedelta(days=1)).date()
                if end_datetime is not None and start_datetime is not None
                else None
            )
            dimensions: list[tuple[str, str]] = []
            for dimension, member in sorted(
                getattr(model_context, "qnameDims", {}).items(),
                key=lambda item: str(item[0]),
            ):
                member_name = getattr(member, "memberQname", None)
                typed_member = getattr(member, "typedMember", None)
                dimensions.append(
                    (
                        str(dimension),
                        str(member_name)
                        if member_name is not None
                        else str(typed_member),
                    )
                )
            model_unit = getattr(fact, "unit", None)
            measures = getattr(
                model_unit, "measures", ((), ()) if model_unit is not None else None
            )
            unit = (
                "/".join(
                    "*".join(str(measure) for measure in side)
                    for side in measures
                    if side
                )
                if measures is not None
                else None
            )
            facts.append(
                ParsedXbrlFactV1(
                    concept=str(concept),
                    value=str(getattr(fact, "value", "")),
                    context_id=str(context),
                    unit=unit,
                    decimals=str(getattr(fact, "decimals", "")) or None,
                    entity_scheme=str(entity_identifier[0])
                    if entity_identifier
                    else None,
                    entity_identifier=str(entity_identifier[1])
                    if entity_identifier
                    else None,
                    period_start=start_datetime.date()
                    if start_datetime is not None
                    else None,
                    period_end=period_end,
                    instant=(instant_datetime - timedelta(days=1)).date()
                    if instant_datetime is not None
                    else None,
                    dimensions=tuple(dimensions),
                    is_numeric=bool(getattr(fact, "isNumeric", False)),
                    scale=int(getattr(fact, "scale", 0) or 0),
                    consolidation_scope="segmented" if dimensions else "consolidated",
                    security_scope="segmented" if dimensions else "unspecified",
                )
            )
        return ArelleParseReportV1(
            filing_path=str(filing_path),
            parser_version=profile.arelle_version,
            taxonomy_version=taxonomy_version,
            validation_profile=profile,
            validation_profile_digest=profile.digest(),
            facts=tuple(facts),
            findings=findings,
            finding_codes=tuple(sorted({item.code for item in findings})),
            validation_engines=validation_engines,
            validation_evidence=validation_evidence,
            parsed_at=datetime.now(timezone.utc),
            offline=profile.offline,
            source_content_hash=actual_source_hash,
            taxonomy_cache_hash=_directory_hash(taxonomy_cache_dir)
            if taxonomy_cache_dir
            else None,
        )
    except ArelleParserError:
        raise
    except Exception as error:
        raise ArelleParserError(
            "XBRL_PARSE_FAILED", "Arelle failed to parse or validate captured filing"
        ) from error
    finally:
        close = getattr(manager, "close", None)
        if callable(close):
            close()


def parse_filing_offline(
    filing_path: Path,
    *,
    profile: ArelleValidationProfileV1,
    taxonomy_version: str,
    taxonomy_cache_dir: Path | None = None,
    source_content_hash: str | None = None,
    deadline_at: datetime | None = None,
) -> ArelleParseReportV1:
    """Parse and validate captured bytes offline under a hard worker deadline."""
    if not filing_path.is_file():
        raise ArelleParserError("FILING_BYTES_UNAVAILABLE", str(filing_path))
    if source_content_hash is not None:
        actual = hashlib.sha256(filing_path.read_bytes()).hexdigest()
        if actual != source_content_hash:
            raise ArelleParserError(
                "SOURCE_HASH_MISMATCH", "parser bytes do not match source manifest"
            )
    if deadline_at is None:
        deadline_at = datetime.now(timezone.utc) + timedelta(minutes=5)
    remaining = (deadline_at - datetime.now(timezone.utc)).total_seconds()
    if remaining <= 0:
        raise ArelleParserError(
            "REQUEST_DEADLINE_EXCEEDED",
            "SEC acquisition deadline expired before parsing",
        )
    ctx = multiprocessing.get_context("spawn")
    result_queue = ctx.Queue(maxsize=1)
    process = ctx.Process(
        target=_parse_worker,
        args=(
            result_queue,
            str(filing_path),
            profile.model_dump(mode="json"),
            taxonomy_version,
            str(taxonomy_cache_dir) if taxonomy_cache_dir else None,
            source_content_hash,
        ),
        daemon=True,
    )
    process.start()
    monotonic_deadline = time.monotonic() + remaining
    try:
        result = None
        while result is None:
            remaining = monotonic_deadline - time.monotonic()
            if remaining <= 0:
                raise ArelleParserError(
                    "REQUEST_DEADLINE_EXCEEDED",
                    "offline SEC parser exceeded the acquisition deadline",
                )
            try:
                result = result_queue.get(timeout=min(0.1, remaining))
            except queue.Empty:
                if not process.is_alive():
                    raise ArelleParserError(
                        "XBRL_PARSE_FAILED",
                        "offline SEC parser exited without a result",
                    )
        process.join(timeout=max(0, monotonic_deadline - time.monotonic()))
        if process.is_alive():
            raise ArelleParserError(
                "REQUEST_DEADLINE_EXCEEDED",
                "offline SEC parser exceeded the acquisition deadline",
            )
    finally:
        if process.is_alive():
            process.terminate()
            process.join(timeout=0.2)
            if process.is_alive() and hasattr(process, "kill"):
                process.kill()
                process.join(timeout=0.2)
        result_queue.close()
    if result.get("network_attempt_count", 0) != 0:
        raise ArelleParserError(
            "OFFLINE_NETWORK_ATTEMPT",
            "offline Arelle worker attempted network access",
        )
    if "error" in result:
        raise ArelleParserError(
            str(result["error"]), str(result.get("message", "Arelle parse failed"))
        )
    return ArelleParseReportV1.model_validate(result)
