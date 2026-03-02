from __future__ import annotations

from src.agents.fundamental.interface.contracts import parse_financial_reports_model
from src.interface.artifacts.artifact_model_shared import as_mapping
from src.shared.kernel.types import JSONObject

from .extension_token_normalizer import normalize_extension_type_token


def _normalize_sec_xbrl_report(
    report_raw: object,
    *,
    context: str,
) -> JSONObject:
    report: JSONObject = dict(as_mapping(report_raw, context))
    extension_raw = report.get("extension")
    if extension_raw is None:
        return report
    _ = as_mapping(extension_raw, f"{context}.extension")

    extension_type = normalize_extension_type_token(
        report.get("extension_type"),
        context=f"{context}.extension_type",
    )
    if extension_type is None:
        raise TypeError(f"{context}.extension requires extension_type")
    report["extension_type"] = extension_type
    return report


def to_canonical_financial_reports(reports_raw: object) -> list[JSONObject]:
    if not isinstance(reports_raw, list):
        raise TypeError("sec_xbrl.financial_reports must be a list")
    normalized_reports = [
        _normalize_sec_xbrl_report(
            report_raw,
            context=f"sec_xbrl.financial_reports[{index}]",
        )
        for index, report_raw in enumerate(reports_raw)
    ]
    return parse_financial_reports_model(
        normalized_reports,
        context="sec_xbrl.financial_reports",
    )
