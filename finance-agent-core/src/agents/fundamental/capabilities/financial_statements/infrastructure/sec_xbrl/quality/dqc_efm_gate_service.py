from __future__ import annotations

from collections.abc import Mapping

from src.shared.kernel.types import JSONObject

FUNDAMENTAL_XBRL_QUALITY_BLOCKED = "FUNDAMENTAL_XBRL_QUALITY_BLOCKED"
_QUALITY_POLICY_VERSION = "xbrl_dqc_efm_gate_v1_2026_03_09"
_BLOCK_SEVERITIES = {"fatal", "critical", "error"}
_WARN_SEVERITIES = {"warning", "warn"}
_CRITICAL_FIELDS: tuple[str, ...] = (
    "total_revenue",
    "operating_income",
    "income_before_tax",
    "income_tax_expense",
    "total_debt",
    "cash_and_equivalents",
    "shares_outstanding",
)


def evaluate_xbrl_quality_gates(
    *,
    reports_raw: object,
    diagnostics: Mapping[str, object] | None = None,
) -> JSONObject:
    issues: list[JSONObject] = []

    for issue in _build_critical_field_missing_issues(reports_raw):
        issues.append(issue)
    for issue in _normalize_external_quality_issues(diagnostics):
        issues.append(issue)

    blocking_issues = [issue for issue in issues if issue.get("blocking") is True]
    warning_issues = [issue for issue in issues if issue.get("blocking") is not True]

    status = "pass"
    if blocking_issues:
        status = "block"
    elif warning_issues:
        status = "warn"

    quality_gates: JSONObject = {
        "status": status,
        "policy_version": _QUALITY_POLICY_VERSION,
        "blocking_count": len(blocking_issues),
        "warning_count": len(warning_issues),
        "issue_count": len(issues),
        "critical_fields": list(_CRITICAL_FIELDS),
        "issues": issues,
    }
    if blocking_issues:
        quality_gates["blocking_error_code"] = FUNDAMENTAL_XBRL_QUALITY_BLOCKED
    return quality_gates


def _build_critical_field_missing_issues(reports_raw: object) -> list[JSONObject]:
    reports = reports_raw if isinstance(reports_raw, list) else []
    if not reports:
        return []
    latest = reports[0]

    issues: list[JSONObject] = []
    for field_key in _CRITICAL_FIELDS:
        if field_key == "shares_outstanding":
            if _has_shares(latest):
                continue
            missing = True
        else:
            missing = _extract_report_base_field_value(latest, field_key) is None
        if not missing:
            continue
        issues.append(
            {
                "code": "DQC_CRITICAL_FIELD_MISSING",
                "source": "DQC",
                "severity": "critical",
                "field_key": field_key,
                "message": f"Critical valuation field missing: {field_key}",
                "blocking": True,
            }
        )
    return issues


def _has_shares(report: object) -> bool:
    for field_key in (
        "shares_outstanding",
        "weighted_average_shares_diluted",
        "weighted_average_shares_basic",
    ):
        value = _extract_report_base_field_value(report, field_key)
        if value is not None:
            return True
    return False


def _normalize_external_quality_issues(
    diagnostics: Mapping[str, object] | None,
) -> list[JSONObject]:
    if not isinstance(diagnostics, Mapping):
        return []
    raw_issues = diagnostics.get("dqc_efm_issues")
    if not isinstance(raw_issues, list):
        return []

    normalized: list[JSONObject] = []
    for raw in raw_issues:
        if not isinstance(raw, Mapping):
            continue
        normalized_issue = normalize_dqc_efm_issue(raw)
        if normalized_issue is None:
            continue
        normalized.append(normalized_issue)
    return normalized


def normalize_dqc_efm_issue(raw: Mapping[str, object]) -> JSONObject | None:
    source = _normalize_source(raw.get("source"))
    severity = _normalize_severity(raw.get("severity"))
    field_key = _normalize_optional_string(raw.get("field_key"))
    code = _normalize_optional_string(raw.get("code")) or "XBRL_QUALITY_ISSUE"
    message = _normalize_optional_string(raw.get("message")) or code
    blocking = _normalize_optional_bool(raw.get("blocking"))
    if blocking is None:
        blocking = _is_blocking(source=source, severity=severity, field_key=field_key)

    normalized: JSONObject = {
        "code": code,
        "source": source,
        "severity": severity,
        "field_key": field_key,
        "message": message,
        "blocking": blocking,
    }
    concept = _normalize_optional_string(raw.get("concept"))
    if concept is not None:
        normalized["concept"] = concept
    context_id = _normalize_optional_string(raw.get("context_id"))
    if context_id is not None:
        normalized["context_id"] = context_id
    return normalized


def _is_blocking(
    *,
    source: str,
    severity: str,
    field_key: str | None,
) -> bool:
    if source == "EFM":
        return severity in _BLOCK_SEVERITIES
    if source == "DQC":
        return (
            severity in _BLOCK_SEVERITIES
            and isinstance(field_key, str)
            and field_key in _CRITICAL_FIELDS
        )
    return False


def _normalize_source(value: object) -> str:
    token = _normalize_optional_string(value)
    if token is None:
        return "UNKNOWN"
    upper = token.upper()
    if upper in {"DQC", "EFM"}:
        return upper
    return upper


def _normalize_severity(value: object) -> str:
    token = _normalize_optional_string(value)
    if token is None:
        return "warning"
    lowered = token.lower()
    if lowered in _BLOCK_SEVERITIES:
        return lowered
    if lowered in _WARN_SEVERITIES:
        return "warning"
    return lowered


def _normalize_optional_string(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    token = value.strip()
    return token or None


def _normalize_optional_bool(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    return None


def _extract_report_base_field_value(report: object, field_key: str) -> object | None:
    base = getattr(report, "base", None)
    if base is not None:
        field = getattr(base, field_key, None)
        if field is not None:
            if hasattr(field, "value"):
                return field.value
            return field

    if isinstance(report, Mapping):
        base_raw = report.get("base")
        if isinstance(base_raw, Mapping):
            field_raw = base_raw.get(field_key)
            if isinstance(field_raw, Mapping):
                return field_raw.get("value")
            return field_raw
    return None
