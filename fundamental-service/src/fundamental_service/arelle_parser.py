"""Pinned Arelle boundary for offline filing validation and XBRL extraction."""

from __future__ import annotations

import hashlib
import multiprocessing
import tempfile
from datetime import date, datetime, timedelta, timezone
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .serialization import sha256_digest


class ArelleParserError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class ArelleValidationProfileV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    arelle_version: str = "2.47.4"
    efm_release: str = "26.3"
    efm_validation_version: str = "1.26.3"
    efm_profile: str = "sec-efm-strict-all-years"
    dqc_version: str = "v31.0.3"
    xule_version: str = "30055"
    offline: bool = True
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
        if self.efm_profile != "sec-efm-strict-all-years":
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
    parsed_at: datetime
    offline: bool = True
    source_content_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    taxonomy_cache_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    def blocking_finding_codes(self) -> tuple[str, ...]:
        return tuple(
            finding.code
            for finding in self.findings
            if finding.severity in {"error", "critical", "fatal"}
        )


def _directory_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(path for path in root.rglob("*") if path.is_file()):
        digest.update(str(path.relative_to(root)).encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _finding_from_log(record: dict[str, Any]) -> ArelleFindingV1 | None:
    level = str(record.get("level", "")).lower()
    if level not in {"error", "critical", "warning", "fatal"}:
        return None
    code = str(record.get("code") or "arelle:unknown")
    message = record.get("message")
    if isinstance(message, dict):
        message_text = str(message.get("text") or code)
    else:
        message_text = str(message or code)
    return ArelleFindingV1(code=code, severity=level, message=message_text[:2048])


def _parse_worker(
    result_queue: multiprocessing.Queue,
    filing_path: str,
    profile_data: dict[str, Any],
    taxonomy_version: str,
    taxonomy_cache_dir: str | None,
    expected_source_hash: str | None,
) -> None:
    try:
        result_queue.put(
            _parse_in_process(
                Path(filing_path),
                ArelleValidationProfileV1.model_validate(profile_data),
                taxonomy_version,
                Path(taxonomy_cache_dir) if taxonomy_cache_dir else None,
                expected_source_hash,
            ).model_dump(mode="json")
        )
    except Exception as error:
        result_queue.put(
            {
                "error": getattr(error, "code", "XBRL_PARSE_FAILED"),
                "message": str(error),
            }
        )


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
            f"installed Arelle {installed_version} does not match {profile.arelle_version}",
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
    if any(item is not None for item in validation_paths):
        if not all(item is not None for item in validation_paths):
            raise ArelleParserError(
                "VALIDATION_RESOURCES_UNAVAILABLE",
                "validation resources are not fully pinned",
            )
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
    elif filing_path.suffix.lower() in {".htm", ".html"}:
        raise ArelleParserError(
            "VALIDATION_RESOURCES_UNAVAILABLE",
            "SEC validation plugins and DQC rules are required",
        )

    from arelle import Cntlr, ModelManager
    from arelle.logging.handlers.LogToXmlHandler import LogToXmlHandler

    config_root = tempfile.TemporaryDirectory(prefix="fundamental-arelle-config-")
    manager = None
    findings: tuple[ArelleFindingV1, ...] = ()
    try:
        controller = Cntlr.Cntlr(logFileName=None, disable_persistent_config=True)
        controller.startLogging(logHandler=LogToXmlHandler(controller))
        controller._pluginManager.addPluginModule(
            str(profile.edgar_plugin_dir / "__init__.py")
        )
        controller._pluginManager.addPluginModule(str(profile.xule_plugin_dir))
        manager = ModelManager.initialize(controller)
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
        if model.errors:
            raise ArelleParserError(
                "XBRL_PARSE_FAILED", "Arelle could not load the filing DTS"
            )
        controller._pluginManager.addPluginModule(
            str(profile.xule_plugin_dir / "validate" / "DQC.py")
        )
        dqc_module = next(
            (
                module
                for module in controller._pluginManager.modulePluginInfos.values()
                if "DQC Rules Validator" in str(module.get("name", ""))
            ),
            None,
        )
        if dqc_module is not None:
            controller._pluginManager.removePluginModule(
                str(dqc_module.get("moduleURL", ""))
            )
        disclosure_system = controller.modelManager.disclosureSystem
        disclosure_system.select(profile.efm_profile)
        if disclosure_system.name not in {"efm-strict-all-years", "efm-all-years"}:
            raise ArelleParserError(
                "EFM_PROFILE_UNAVAILABLE", "strict SEC EFM profile is not available"
            )
        if taxonomy_cache_dir is not None:
            disclosure_system.dir = str(profile.edgar_plugin_dir)
        model.modelManager.validate(
            model, parameters={"xule_rule_set": str(profile.dqc_ruleset_path)}
        )
        handler = controller.logHandler
        records = getattr(handler, "logRecordBuffer", ())
        findings = tuple(
            item
            for record in records
            if (item := _finding_from_log(handler.recordToJson(record))) is not None
        )
        if (
            not any(item.code.startswith("DQC") for item in findings)
            and profile.dqc_ruleset_path
        ):
            if not any(
                record.get("code") == "info:profileActivity"
                for record in (handler.recordToJson(item) for item in records)
            ):
                raise ArelleParserError(
                    "DQC_VALIDATION_UNAVAILABLE", "DQC rules did not run"
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
        config_root.cleanup()


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
        return _parse_in_process(
            filing_path,
            profile,
            taxonomy_version,
            taxonomy_cache_dir,
            source_content_hash,
        )
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
    process.join(timeout=remaining)
    if process.is_alive():
        process.terminate()
        process.join(timeout=2)
        if process.is_alive() and hasattr(process, "kill"):
            process.kill()
            process.join(timeout=2)
        raise ArelleParserError(
            "REQUEST_DEADLINE_EXCEEDED",
            "offline SEC parser exceeded the acquisition deadline",
        )
    try:
        result = result_queue.get_nowait()
    except Exception as error:
        raise ArelleParserError(
            "XBRL_PARSE_FAILED", "offline SEC parser exited without a result"
        ) from error
    finally:
        result_queue.close()
    if "error" in result:
        raise ArelleParserError(
            str(result["error"]), str(result.get("message", "Arelle parse failed"))
        )
    return ArelleParseReportV1.model_validate(result)
