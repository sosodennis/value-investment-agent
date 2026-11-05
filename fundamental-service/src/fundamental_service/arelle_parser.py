"""Pinned Arelle boundary for offline filing validation and XBRL extraction."""

from __future__ import annotations

import hashlib
import tempfile
from datetime import date, datetime, timedelta, timezone
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from unittest.mock import patch

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ArelleParserError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class ArelleValidationProfileV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    arelle_version: str = "2.47.4"
    efm_profile: str = "sec-efm"
    dqc_version: str = "v31.0.3"
    xule_version: str = "30055"
    offline: bool = True
    profile_id: str = Field(min_length=1)

    @model_validator(mode="after")
    def pinned_runtime(self) -> "ArelleValidationProfileV1":
        if self.arelle_version != "2.47.4":
            raise ValueError("Arelle version must be pinned to 2.47.4")
        if (
            self.efm_profile != "sec-efm"
            or self.dqc_version != "v31.0.3"
            or self.xule_version != "30055"
        ):
            raise ValueError("SEC validation profile versions are not pinned")
        if not self.offline:
            raise ValueError("offline parser profile must set offline=true")
        return self


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


class ArelleParseReportV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    filing_path: str = Field(min_length=1)
    parser_version: str = Field(min_length=1)
    taxonomy_version: str = Field(min_length=1)
    validation_profile: ArelleValidationProfileV1
    facts: tuple[ParsedXbrlFactV1, ...] = ()
    finding_codes: tuple[str, ...] = ()
    parsed_at: datetime
    offline: bool = True
    source_content_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    taxonomy_cache_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    def blocking_finding_codes(self) -> tuple[str, ...]:
        allowed_warnings = {
            "ix11.10.1.2:invalidTransformation",
            "ix11.11.1.2:invalidTransformation",
        }
        return tuple(
            code for code in self.finding_codes if code not in allowed_warnings
        )


def _directory_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(path for path in root.rglob("*") if path.is_file()):
        digest.update(str(path.relative_to(root)).encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
    return digest.hexdigest()


def parse_filing_offline(
    filing_path: Path,
    *,
    profile: ArelleValidationProfileV1,
    taxonomy_version: str,
    taxonomy_cache_dir: Path | None = None,
    source_content_hash: str | None = None,
) -> ArelleParseReportV1:
    """Parse a captured filing without provider access.

    Missing Arelle is an explicit release failure. There is no local fallback
    parser because doing so would make validation evidence incomparable.
    """
    if not filing_path.is_file():
        raise ArelleParserError("FILING_BYTES_UNAVAILABLE", str(filing_path))
    actual_source_hash = hashlib.sha256(filing_path.read_bytes()).hexdigest()
    if source_content_hash is not None and source_content_hash != actual_source_hash:
        raise ArelleParserError(
            "SOURCE_HASH_MISMATCH", "parser bytes do not match source manifest"
        )
    try:
        from arelle import Cntlr, ModelManager
    except ImportError as error:
        raise ArelleParserError(
            "ARELLE_UNAVAILABLE",
            "arelle-release==2.47.4 is required for filing parsing",
        ) from error
    if filing_path.suffix.lower() in {".htm", ".html"} and taxonomy_cache_dir is None:
        raise ArelleParserError(
            "TAXONOMY_CACHE_REQUIRED",
            "inline SEC filings require a captured taxonomy cache for offline parsing",
        )
    cache_dir = tempfile.TemporaryDirectory(prefix="fundamental-arelle-user-")
    manager = None
    finding_codes: tuple[str, ...] = ()
    try:
        try:
            installed_version = version("arelle-release")
        except PackageNotFoundError as error:
            raise ArelleParserError(
                "ARELLE_UNAVAILABLE", "arelle-release==2.47.4 is required"
            ) from error
        if installed_version != profile.arelle_version:
            raise ArelleParserError(
                "ARELLE_VERSION_MISMATCH",
                "installed Arelle "
                f"{installed_version} does not match {profile.arelle_version}",
            )
        log_path = Path(cache_dir.name) / "arelle.log"
        with patch.dict("os.environ", {"XDG_CONFIG_HOME": cache_dir.name}):
            controller = Cntlr.Cntlr(
                logFileName=str(log_path), disable_persistent_config=True
            )
        if profile.offline and hasattr(controller, "webCache"):
            controller.webCache.workOffline = True
            if taxonomy_cache_dir is not None:
                if not taxonomy_cache_dir.is_dir():
                    raise ArelleParserError(
                        "TAXONOMY_CACHE_UNAVAILABLE", str(taxonomy_cache_dir)
                    )
                controller.webCache.cacheDir = str(taxonomy_cache_dir)
        manager = ModelManager.initialize(controller)
        model = manager.load(str(filing_path))
        if model is None:
            raise ArelleParserError("XBRL_PARSE_FAILED", "Arelle returned no model")
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
            if end_datetime is not None and start_datetime is not None:
                period_end = (end_datetime - timedelta(days=1)).date()
            else:
                period_end = None
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
                    entity_scheme=(
                        str(entity_identifier[0]) if entity_identifier else None
                    ),
                    entity_identifier=(
                        str(entity_identifier[1]) if entity_identifier else None
                    ),
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
                    consolidation_scope=("segmented" if dimensions else "consolidated"),
                    security_scope=("segmented" if dimensions else "unspecified"),
                )
            )
        finding_codes = tuple(
            sorted({str(code) for code in getattr(model, "errors", ())})
        )
    except ArelleParserError:
        raise
    except Exception as error:
        raise ArelleParserError(
            "XBRL_PARSE_FAILED", "Arelle failed to parse captured filing"
        ) from error
    finally:
        close = getattr(manager, "close", None)
        if callable(close):
            close()
        cache_dir.cleanup()
    return ArelleParseReportV1(
        filing_path=str(filing_path),
        parser_version=profile.arelle_version,
        taxonomy_version=taxonomy_version,
        validation_profile=profile,
        facts=tuple(facts),
        finding_codes=finding_codes,
        parsed_at=datetime.now(timezone.utc),
        offline=profile.offline,
        source_content_hash=actual_source_hash,
        taxonomy_cache_hash=(
            _directory_hash(taxonomy_cache_dir)
            if taxonomy_cache_dir is not None
            else None
        ),
    )
