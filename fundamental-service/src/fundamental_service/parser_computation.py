"""Versioned parser computation identity, distinct from exact execution bytes."""

from __future__ import annotations

from datetime import UTC
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from .arelle_parser import ArelleParseReportV1, ArelleValidationProfileV1
from .parser_action_contracts import Digest
from .serialization import sha256_digest


class ParserComputationV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    protocol: Literal["sec-parser-computation-v1"] = "sec-parser-computation-v1"
    action_key: Digest
    report_digest: Digest


def logical_profile(profile: ArelleValidationProfileV1) -> ArelleValidationProfileV1:
    """Retain roles, relative names and hashes while removing deployment roots."""
    changes: dict[str, object] = {
        name: Path(value.name)
        for name in (
            "edgar_plugin_dir",
            "xule_plugin_dir",
            "dqc_ruleset_path",
            "historical_dqc_dir",
            "historical_dqc_axis_config",
        )
        if (value := getattr(profile, name)) is not None
    }
    if profile.dqc_ruleset_catalog is not None:
        changes["dqc_ruleset_catalog"] = profile.dqc_ruleset_catalog.model_copy(
            update={
                "bindings": tuple(
                    binding.model_copy(update={"path": Path(binding.path.name)})
                    for binding in profile.dqc_ruleset_catalog.bindings
                )
            }
        )
    return profile.model_copy(update=changes)


def parser_computation(
    report: ArelleParseReportV1, action_key: str
) -> ParserComputationV1:
    return ParserComputationV1(
        action_key=action_key, report_digest=_computation_report_digest(report)
    )


def _computation_report_digest(report: ArelleParseReportV1) -> str:
    """Include full observations and validation; omit only execution coordinates.

    Finding messages are retained verbatim. Unexplained path/text differences
    therefore remain different computations rather than being broadly stripped.
    """
    payload = report.model_dump(
        mode="json",
        exclude={"filing_path", "parsed_at", "execution_evidence", "identity_protocol"},
    )
    payload["validation_profile"] = logical_profile(
        report.validation_profile
    ).model_dump(mode="json")
    payload["facts"] = sorted(payload["facts"], key=sha256_digest)
    payload["findings"] = sorted(payload["findings"], key=sha256_digest)
    payload["finding_codes"] = sorted(payload["finding_codes"])
    payload["validation_evidence"] = [
        value
        for value in execution_validation_evidence(report)
        if not value.startswith(("sec-parser-action-", "sec-parser-computation-"))
    ]
    return sha256_digest(payload)


def canonical_computation_report(report: ArelleParseReportV1) -> ArelleParseReportV1:
    """Deterministic downstream report; raw execution evidence remains separate."""
    from .parser_action_contracts import parser_action_markers

    if report.execution_evidence:
        report = report.model_copy(
            update={
                "validation_evidence": execution_validation_evidence(report),
                "execution_evidence": (),
            }
        )
    raw_markers = tuple(
        v for v in report.validation_evidence if v.startswith("sec-parser-action-")
    )
    markers = parser_action_markers(raw_markers)
    evidence = [
        value for value in report.validation_evidence if value not in raw_markers
    ]
    report_digest = _computation_report_digest(report) if markers else None
    for _, representation, key, _, _ in markers:
        assert report_digest is not None
        computation = ParserComputationV1(action_key=key, report_digest=report_digest)
        evidence.append(
            f"sec-parser-computation-v1:{representation}:{key}:{sha256_digest(computation)}"
        )
    return report.model_copy(
        update={
            "parsed_at": report.parsed_at.astimezone(UTC),
            "validation_profile": logical_profile(report.validation_profile),
            "validation_evidence": tuple(evidence),
            "execution_evidence": report.validation_evidence if raw_markers else (),
            "identity_protocol": "parser-report-computation-v1",
        }
    )


def execution_validation_evidence(report: ArelleParseReportV1) -> tuple[str, ...]:
    return report.execution_evidence or report.validation_evidence
