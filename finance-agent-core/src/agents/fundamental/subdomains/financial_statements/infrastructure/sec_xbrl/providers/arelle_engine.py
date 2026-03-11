from __future__ import annotations

import importlib
import importlib.util
import io
import os
import re
import threading
import time
import zipfile
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime

import pandas as pd

from .engine_contracts import (
    ArelleParseResult,
    ArelleRuntimeMetadata,
    ArelleValidationIssue,
    ArelleValidationProfile,
    IArelleXbrlEngine,
    XbrlAttachmentBundle,
)

_BASE_FACT_COLUMNS = (
    "concept",
    "value",
    "label",
    "statement_type",
    "period_key",
    "period_end",
    "period_type",
    "unit",
    "decimals",
    "scale",
)


class ArelleEngineUnavailableError(RuntimeError):
    pass


class ArelleEngineParseError(RuntimeError):
    pass


ParseBundleFn = Callable[[XbrlAttachmentBundle], ArelleParseResult]

_VALIDATION_MODE_FACTS_ONLY = "facts_only"
_VALIDATION_MODE_EFM_VALIDATE = "efm_validate"
_VALIDATION_MODE_EFM_DQC_VALIDATE = "efm_dqc_validate"
_VALIDATION_MODE_ENV = "FUNDAMENTAL_XBRL_ARELLE_VALIDATION_MODE"
_DISCLOSURE_SYSTEM_ENV = "FUNDAMENTAL_XBRL_ARELLE_DISCLOSURE_SYSTEM"
_PLUGINS_ENV = "FUNDAMENTAL_XBRL_ARELLE_PLUGINS"
_PACKAGES_ENV = "FUNDAMENTAL_XBRL_ARELLE_PACKAGES"
_RUNTIME_ISOLATION_ENV = "FUNDAMENTAL_XBRL_ARELLE_RUNTIME_ISOLATION"
_SUPPORTED_VALIDATION_MODES = {
    _VALIDATION_MODE_FACTS_ONLY,
    _VALIDATION_MODE_EFM_VALIDATE,
    _VALIDATION_MODE_EFM_DQC_VALIDATE,
}
_DEFAULT_PLUGINS_BY_MODE: dict[str, tuple[str, ...]] = {
    _VALIDATION_MODE_EFM_VALIDATE: ("validate/EFM",),
    _VALIDATION_MODE_EFM_DQC_VALIDATE: ("validate/EFM", "validate/DQC"),
}
_RUNTIME_ISOLATION_SERIAL = "serial"
_RUNTIME_ISOLATION_NONE = "none"
_SUPPORTED_RUNTIME_ISOLATION_MODES = {
    _RUNTIME_ISOLATION_SERIAL,
    _RUNTIME_ISOLATION_NONE,
}
_ARELLE_RUNTIME_PARSE_LOCK = threading.RLock()


class ArelleXbrlEngine(IArelleXbrlEngine):
    def __init__(
        self,
        *,
        parse_bundle_fn: ParseBundleFn | None = None,
        validation_profile: ArelleValidationProfile | None = None,
    ) -> None:
        self._validation_profile = (
            validation_profile or _resolve_validation_profile_from_env()
        )
        self._parse_bundle_fn = parse_bundle_fn or (
            lambda bundle: _parse_bundle_with_arelle_runtime(
                bundle,
                validation_profile=self._validation_profile,
            )
        )

    def parse_attachment_bundle(
        self,
        *,
        bundle: XbrlAttachmentBundle,
    ) -> ArelleParseResult:
        return self._parse_bundle_fn(bundle)


def _parse_bundle_with_arelle_runtime(
    bundle: XbrlAttachmentBundle,
    *,
    validation_profile: ArelleValidationProfile,
) -> ArelleParseResult:
    started = time.perf_counter()
    isolation_mode = _resolve_runtime_isolation_mode_from_env()
    if importlib.util.find_spec("arelle") is None:
        raise ArelleEngineUnavailableError(
            "Arelle runtime unavailable. Install arelle to enable Arelle-first XBRL parsing."
        )

    try:
        from arelle import (  # type: ignore[import-not-found]
            Cntlr,
            FileSource,
            ModelManager,
            ModelXbrl,
            Validate,
        )
    except Exception as exc:  # pragma: no cover - guarded by find_spec
        raise ArelleEngineUnavailableError(
            f"Arelle import failed: {type(exc).__name__}: {exc}"
        ) from exc

    zip_stream = _build_zip_stream(bundle)
    controller = Cntlr.Cntlr(logFileName="structured-message")
    manager = ModelManager.initialize(controller)

    model_xbrl = None
    file_source = None
    lock_wait_ms = 0.0
    dataframe = pd.DataFrame(columns=list(_BASE_FACT_COLUMNS))
    validation_issues: tuple[ArelleValidationIssue, ...] = ()

    def _parse_once() -> None:
        nonlocal model_xbrl, file_source, validation_issues, dataframe
        _configure_validation_runtime(
            controller=controller,
            manager=manager,
            validation_profile=validation_profile,
        )
        file_source = FileSource.openFileSource(
            bundle.instance_document,
            sourceZipStream=zip_stream,
        )
        model_xbrl = ModelXbrl.load(manager, file_source)
        if validation_profile.validation_enabled:
            Validate.validate(model_xbrl)
        validation_issues = _collect_validation_issues(model_xbrl)
        dataframe = _facts_to_dataframe(model_xbrl)

    try:
        if isolation_mode == _RUNTIME_ISOLATION_SERIAL:
            lock_started = time.perf_counter()
            with _ARELLE_RUNTIME_PARSE_LOCK:
                lock_wait_ms = (time.perf_counter() - lock_started) * 1000.0
                _parse_once()
        else:
            _parse_once()
    except Exception as exc:
        raise ArelleEngineParseError(
            f"Arelle parse failed for {bundle.instance_document}: "
            f"{type(exc).__name__}: {exc}"
        ) from exc
    finally:
        try:
            close_model = getattr(model_xbrl, "close", None)
            if callable(close_model):
                close_model()
        except Exception:
            pass
        try:
            close_source = getattr(file_source, "close", None)
            if callable(close_source):
                close_source()
        except Exception:
            pass
        try:
            close_controller = getattr(controller, "close", None)
            if callable(close_controller):
                close_controller()
        except Exception:
            pass

    doc_types = {attachment.document_type.upper() for attachment in bundle.attachments}
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    return ArelleParseResult(
        facts_dataframe=dataframe,
        instance_document=bundle.instance_document,
        loaded_attachment_count=len(bundle.attachments),
        schema_loaded="EX-101.SCH" in doc_types,
        label_loaded="EX-101.LAB" in doc_types,
        presentation_loaded="EX-101.PRE" in doc_types,
        calculation_loaded="EX-101.CAL" in doc_types,
        definition_loaded="EX-101.DEF" in doc_types,
        validation_issues=validation_issues,
        runtime_metadata=ArelleRuntimeMetadata(
            mode=validation_profile.mode,
            disclosure_system=validation_profile.disclosure_system,
            plugins=validation_profile.plugins,
            packages=validation_profile.packages,
            arelle_version=_resolve_arelle_version(),
            validation_enabled=validation_profile.validation_enabled,
            runtime_isolation_mode=isolation_mode,
            runtime_lock_wait_ms=round(lock_wait_ms, 3),
        ),
        parse_latency_ms=elapsed_ms,
    )


def _build_zip_stream(bundle: XbrlAttachmentBundle) -> io.BytesIO:
    zip_stream = io.BytesIO()
    with zipfile.ZipFile(zip_stream, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for attachment in bundle.attachments:
            zf.writestr(attachment.document, attachment.content.encode("utf-8"))
    zip_stream.seek(0)
    return zip_stream


def _facts_to_dataframe(model_xbrl: object) -> pd.DataFrame:
    facts_raw = getattr(model_xbrl, "facts", None)
    if not isinstance(facts_raw, list):
        return pd.DataFrame(columns=list(_BASE_FACT_COLUMNS))

    rows: list[dict[str, object]] = []
    for fact in facts_raw:
        row = _build_fact_row(fact)
        rows.append(row)

    if not rows:
        return pd.DataFrame(columns=list(_BASE_FACT_COLUMNS))

    dataframe = pd.DataFrame(rows)
    for column in _BASE_FACT_COLUMNS:
        if column not in dataframe.columns:
            dataframe[column] = None
    return dataframe


def _build_fact_row(fact: object) -> dict[str, object]:
    context = getattr(fact, "context", None)
    period_key, period_end, period_type = _period_fields_from_context(context)

    concept = _concept_name(fact)
    label = _concept_label(fact)
    value = _fact_value(fact)
    unit = _fact_unit(fact)
    decimals = _optional_string(getattr(fact, "decimals", None))
    scale = _optional_string(getattr(fact, "scale", None))

    row: dict[str, object] = {
        "concept": concept,
        "value": value,
        "label": label,
        "statement_type": None,
        "period_key": period_key,
        "period_end": period_end,
        "period_type": period_type,
        "unit": unit,
        "decimals": decimals,
        "scale": scale,
    }

    row.update(_dimension_fields_from_context(context))
    return row


def _concept_name(fact: object) -> str:
    concept = getattr(fact, "concept", None)
    qname = getattr(concept, "qname", None)
    prefix = _optional_string(getattr(qname, "prefix", None))
    local_name = _optional_string(getattr(qname, "localName", None))
    if prefix and local_name:
        return f"{prefix}:{local_name}"
    if local_name:
        return local_name

    fallback_qname = getattr(fact, "qname", None)
    fallback_prefix = _optional_string(getattr(fallback_qname, "prefix", None))
    fallback_local = _optional_string(getattr(fallback_qname, "localName", None))
    if fallback_prefix and fallback_local:
        return f"{fallback_prefix}:{fallback_local}"
    if fallback_local:
        return fallback_local
    return _optional_string(qname) or _optional_string(fallback_qname) or "unknown:fact"


def _concept_label(fact: object) -> str | None:
    concept = getattr(fact, "concept", None)
    label_fn = getattr(concept, "label", None)
    if not callable(label_fn):
        return None
    try:
        value = label_fn(lang="en")
        normalized = _optional_string(value)
        if normalized:
            return normalized
    except Exception:
        pass
    try:
        value = label_fn()
        return _optional_string(value)
    except Exception:
        return None


def _fact_value(fact: object) -> str | None:
    value = _optional_string(getattr(fact, "value", None))
    if value is not None:
        return value
    x_value = getattr(fact, "xValue", None)
    return _optional_string(x_value)


def _fact_unit(fact: object) -> str | None:
    unit_id = _optional_string(getattr(fact, "unitID", None))
    if unit_id:
        return unit_id
    unit = getattr(fact, "unit", None)
    return _optional_string(unit)


def _period_fields_from_context(
    context: object,
) -> tuple[str, str | None, str | None]:
    if context is None:
        return "unknown_period", None, None

    is_instant = bool(getattr(context, "isInstantPeriod", False))
    if is_instant:
        instant = _normalize_iso_date(
            getattr(context, "instantDatetime", None)
            or getattr(context, "instantDate", None)
            or getattr(context, "endDatetime", None)
        )
        if instant:
            return f"instant_{instant}", instant, "instant"
        return "instant_unknown", None, "instant"

    is_duration = bool(getattr(context, "isStartEndPeriod", False))
    if is_duration:
        start = _normalize_iso_date(getattr(context, "startDatetime", None))
        end = _normalize_iso_date(getattr(context, "endDatetime", None))
        if start and end:
            return f"duration_{start}_{end}", end, "duration"
        if end:
            return f"duration_unknown_{end}", end, "duration"
        return "duration_unknown", None, "duration"

    return "unknown_period", None, None


def _dimension_fields_from_context(context: object) -> dict[str, str]:
    if context is None:
        return {}
    qname_dims = getattr(context, "qnameDims", None)
    if not isinstance(qname_dims, dict):
        return {}

    fields: dict[str, str] = {}
    for axis_qname, dim_value in qname_dims.items():
        axis_name = _optional_string(getattr(axis_qname, "localName", None))
        if not axis_name:
            axis_name = _optional_string(axis_qname)
        if not axis_name:
            continue
        member_qname = getattr(dim_value, "memberQname", None)
        member_name = _optional_string(getattr(member_qname, "localName", None))
        if not member_name:
            member_name = _optional_string(member_qname)
        if not member_name:
            member_name = _optional_string(dim_value)
        if not member_name:
            continue
        fields[f"dim_{axis_name}"] = member_name
    return fields


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None


def _normalize_iso_date(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()

    text = _optional_string(value)
    if text is None:
        return None
    if "T" in text:
        text = text.split("T")[0]
    if len(text) >= 10:
        return text[:10]
    return text


def _resolve_arelle_version() -> str | None:
    try:
        if importlib.util.find_spec("arelle") is None:
            return None
        module = importlib.import_module("arelle")
    except Exception:
        return None
    version = getattr(module, "__version__", None)
    if not isinstance(version, str):
        return None
    value = version.strip()
    return value or None


def _resolve_validation_profile_from_env() -> ArelleValidationProfile:
    mode_raw = os.getenv(_VALIDATION_MODE_ENV, _VALIDATION_MODE_FACTS_ONLY)
    mode_normalized = mode_raw.strip().lower()
    if mode_normalized not in _SUPPORTED_VALIDATION_MODES:
        mode_normalized = _VALIDATION_MODE_FACTS_ONLY

    disclosure_system_raw = os.getenv(_DISCLOSURE_SYSTEM_ENV, "").strip()
    disclosure_system = disclosure_system_raw or None
    if mode_normalized != _VALIDATION_MODE_FACTS_ONLY and disclosure_system is None:
        disclosure_system = "efm"

    plugins = _split_csv_env(_PLUGINS_ENV)
    if not plugins:
        plugins = _DEFAULT_PLUGINS_BY_MODE.get(mode_normalized, ())

    return ArelleValidationProfile(
        mode=mode_normalized,
        disclosure_system=disclosure_system,
        plugins=plugins,
        packages=_split_csv_env(_PACKAGES_ENV),
    )


def _split_csv_env(name: str) -> tuple[str, ...]:
    raw = os.getenv(name, "")
    tokens = [item.strip() for item in raw.split(",")]
    values = tuple(token for token in tokens if token)
    return values


def _resolve_runtime_isolation_mode_from_env() -> str:
    raw = os.getenv(_RUNTIME_ISOLATION_ENV, _RUNTIME_ISOLATION_SERIAL)
    normalized = raw.strip().lower()
    if normalized not in _SUPPORTED_RUNTIME_ISOLATION_MODES:
        return _RUNTIME_ISOLATION_SERIAL
    return normalized


def _configure_validation_runtime(
    *,
    controller: object,
    manager: object,
    validation_profile: ArelleValidationProfile,
) -> None:
    disclosure_system_obj = getattr(manager, "disclosureSystem", None)
    select_fn = getattr(disclosure_system_obj, "select", None)
    if callable(select_fn):
        select_fn(validation_profile.disclosure_system)
    validate_disclosure = (
        validation_profile.validation_enabled
        and validation_profile.disclosure_system is not None
    )
    manager.validateDisclosureSystem = validate_disclosure
    if not validation_profile.validation_enabled:
        return
    _activate_validation_plugins(
        controller=controller,
        plugins=validation_profile.plugins,
    )
    _activate_validation_packages(
        controller=controller,
        packages=validation_profile.packages,
    )


def _activate_validation_plugins(
    *,
    controller: object,
    plugins: tuple[str, ...],
) -> None:
    if not plugins:
        return
    plugin_manager_module = _import_arelle_runtime_module("arelle.PluginManager")
    if plugin_manager_module is None:
        raise RuntimeError(
            "Arelle PluginManager unavailable for validation plugin execution."
        )

    init_fn = getattr(plugin_manager_module, "init", None)
    add_plugin_module_fn = getattr(plugin_manager_module, "addPluginModule", None)
    if not callable(init_fn) or not callable(add_plugin_module_fn):
        raise RuntimeError("Arelle PluginManager missing required plugin hooks.")

    init_fn(controller, loadPluginConfig=False)
    for plugin_name in dict.fromkeys(plugins):
        plugin_info = add_plugin_module_fn(plugin_name)
        if plugin_info is None:
            raise RuntimeError(f"Arelle validation plugin load failed: {plugin_name}")


def _activate_validation_packages(
    *,
    controller: object,
    packages: tuple[str, ...],
) -> None:
    if not packages:
        return
    package_manager_module = _import_arelle_runtime_module("arelle.PackageManager")
    if package_manager_module is None:
        raise RuntimeError(
            "Arelle PackageManager unavailable for taxonomy package execution."
        )

    init_fn = getattr(package_manager_module, "init", None)
    add_package_fn = getattr(package_manager_module, "addPackage", None)
    if not callable(init_fn) or not callable(add_package_fn):
        raise RuntimeError("Arelle PackageManager missing required package hooks.")

    init_fn(controller, loadPackagesConfig=False)
    for package_path in dict.fromkeys(packages):
        package_info = add_package_fn(controller, package_path)
        if package_info is None:
            raise RuntimeError(f"Arelle taxonomy package load failed: {package_path}")


def _import_arelle_runtime_module(module_name: str) -> object | None:
    try:
        if importlib.util.find_spec(module_name) is None:
            return None
        return importlib.import_module(module_name)
    except Exception:
        return None


def _collect_validation_issues(model_xbrl: object) -> tuple[ArelleValidationIssue, ...]:
    raw_errors = getattr(model_xbrl, "errors", None)
    if not isinstance(raw_errors, Sequence) or isinstance(raw_errors, str | bytes):
        return ()

    issues: list[ArelleValidationIssue] = []
    seen: set[tuple[str, str, str, str, str | None, str | None, str | None]] = set()
    for raw in raw_errors:
        normalized = _normalize_validation_error(raw)
        if normalized is None:
            continue
        code, message, severity, concept, context_id = normalized
        source = _infer_issue_source(f"{code} {message}")
        field_key = _infer_issue_field_key(
            code=code,
            message=message,
            concept=concept,
        )
        dedupe_key = (code, source, severity, message, field_key, concept, context_id)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        issues.append(
            ArelleValidationIssue(
                code=code,
                source=source,
                severity=severity,
                message=message,
                field_key=field_key,
                concept=concept,
                context_id=context_id,
            )
        )
    return tuple(issues)


def _normalize_validation_error(
    raw: object,
) -> tuple[str, str, str, str | None, str | None] | None:
    if isinstance(raw, Mapping):
        code = _mapping_first_value(raw, ("code", "messageCode", "msgCode", "id"))
        message = _mapping_first_value(raw, ("message", "msg", "text", "description"))
        severity_raw = _mapping_first_value(raw, ("severity", "level", "logLevel"))
        concept = _mapping_first_value(
            raw,
            ("concept", "qname", "fact", "factQname"),
        )
        context_id = _mapping_first_value(
            raw,
            ("context_id", "contextId", "context"),
        )
        if code is None and message is None:
            return None
        resolved_code = code or "ARELLE_VALIDATION_ISSUE"
        resolved_message = message or resolved_code
        severity = _infer_issue_severity(
            severity_raw,
            code=resolved_code,
            message=resolved_message,
        )
        return resolved_code, resolved_message, severity, concept, context_id

    if isinstance(raw, Sequence) and not isinstance(raw, str | bytes):
        parts = [_optional_string(item) for item in raw]
        values = [item for item in parts if item is not None]
        if not values:
            return None
        resolved_code = values[0]
        resolved_message = values[1] if len(values) > 1 else resolved_code
        severity = _infer_issue_severity(
            None,
            code=resolved_code,
            message=resolved_message,
        )
        return resolved_code, resolved_message, severity, None, None

    raw_text = _optional_string(raw)
    if raw_text is None:
        return None
    severity = _infer_issue_severity(
        None,
        code=raw_text,
        message=raw_text,
    )
    return raw_text, raw_text, severity, None, None


def _mapping_first_value(
    mapping: Mapping[object, object],
    keys: tuple[str, ...],
) -> str | None:
    for key in keys:
        value = mapping.get(key)
        normalized = _optional_string(value)
        if normalized is not None:
            return normalized
    return None


def _infer_issue_severity(
    raw_severity: str | None,
    *,
    code: str,
    message: str,
) -> str:
    normalized_raw = _normalize_severity_token(raw_severity)
    if normalized_raw is not None:
        return normalized_raw

    haystack = f"{code} {message}".lower()
    if "fatal" in haystack:
        return "fatal"
    if "critical" in haystack:
        return "critical"
    if "warning" in haystack or "warn" in haystack:
        return "warning"
    if "info" in haystack:
        return "info"
    return "error"


def _normalize_severity_token(value: str | None) -> str | None:
    token = _optional_string(value)
    if token is None:
        return None
    normalized = token.lower()
    if normalized in {"err", "error"}:
        return "error"
    if normalized in {"fatal"}:
        return "fatal"
    if normalized in {"critical", "crit"}:
        return "critical"
    if normalized in {"warn", "warning"}:
        return "warning"
    if normalized in {"info", "information"}:
        return "info"
    return normalized


def _infer_issue_source(token: str) -> str:
    token_upper = token.upper()
    if token_upper.startswith("EFM") or re.search(r"\bEFM\b", token_upper):
        return "EFM"
    if token_upper.startswith("DQC") or re.search(r"\bDQC\b", token_upper):
        return "DQC"
    return "ARELLE"


def _infer_issue_field_key(
    *,
    code: str,
    message: str,
    concept: str | None,
) -> str | None:
    concept_token = _normalize_concept_token(concept)
    if concept_token is not None:
        concept_field = _match_field_key_from_token(concept_token)
        if concept_field is not None:
            return concept_field

    merged_token = _normalize_concept_token(f"{code} {message}")
    if merged_token is None:
        return None
    return _match_field_key_from_token(merged_token)


def _normalize_concept_token(value: str | None) -> str | None:
    token = _optional_string(value)
    if token is None:
        return None
    local_name = token.split(":")[-1]
    normalized = re.sub(r"[^a-z0-9]+", "", local_name.lower())
    return normalized or None


def _match_field_key_from_token(token: str) -> str | None:
    if "incomebeforetax" in token or "pretaxincome" in token:
        return "income_before_tax"
    if "incometaxexpense" in token or "taxexpense" in token:
        return "income_tax_expense"
    if "operatingincome" in token or "incomefromoperations" in token:
        return "operating_income"
    if "cashandequivalents" in token or "cashcashequivalents" in token:
        return "cash_and_equivalents"
    if "debt" in token or "borrowings" in token:
        return "total_debt"
    if "sharesoutstanding" in token or "weightedaverageshares" in token:
        return "shares_outstanding"
    if "revenue" in token or "sales" in token:
        return "total_revenue"
    return None
