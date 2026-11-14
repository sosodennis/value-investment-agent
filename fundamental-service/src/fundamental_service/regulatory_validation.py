"""Shared SEC EFM/DQC completion gate for ingestion and released evidence."""

from .arelle_parser import ArelleParseReportV1
from .historical_dqc import historical_profile
from .snapshots import SnapshotError
from .dqc_applicability import DqcFilingContextV1


def bind_dqc_filing_context(
    report: ArelleParseReportV1, context: DqcFilingContextV1
) -> ArelleParseReportV1:
    """Bind the SEC catalog date after full official validation has completed."""
    require_sec_validation_evidence(report)
    if report.dqc_filing_context is not None:
        if report.dqc_filing_context != context:
            raise SnapshotError(
                "DQC_FILING_CONTEXT_MISMATCH",
                "DQC report belongs to another original filing",
            )
        return report
    payload = report.model_dump(mode="json")
    payload["dqc_filing_context"] = context.model_dump(mode="json")
    payload["validation_evidence"].append(context.evidence_marker())
    return ArelleParseReportV1.model_validate(payload)


def require_sec_validation_evidence(report: ArelleParseReportV1) -> None:
    if report.validation_profile.validation_mode != "sec-efm-dqc":
        raise SnapshotError(
            "SEC_VALIDATION_REQUIRED",
            "SEC parser report was not produced by sec-efm-dqc",
        )
    if not {"sec-efm", "dqc-us"}.issubset(report.validation_engines):
        raise SnapshotError(
            "VALIDATION_EVIDENCE_MISSING",
            "SEC parser report lacks EFM/DQC engine evidence",
        )
    selected_historical = historical_profile(report.validation_profile.profile_id)
    if not {
        "strict-sec-efm-profile-selected",
        selected_historical.completion_marker
        if selected_historical is not None
        else "dqc-dqcrt-checks-completed",
    }.issubset(report.validation_evidence):
        raise SnapshotError(
            "VALIDATION_EVIDENCE_MISSING",
            "SEC parser report lacks EFM/DQC completion evidence",
        )
    if report.network_attempt_count != 0:
        raise SnapshotError(
            "OFFLINE_NETWORK_ATTEMPT",
            "SEC parser report records a network attempt",
        )
    catalog = report.validation_profile.dqc_ruleset_catalog
    if catalog is not None:
        try:
            selected = catalog.select(
                tuple(
                    sorted(
                        {
                            fact.namespace_uri
                            for fact in report.facts
                            if fact.namespace_uri
                        }
                    )
                )
            )
        except ValueError as error:
            raise SnapshotError(
                "DQC_TAXONOMY_RULESET_UNAVAILABLE", str(error)
            ) from error
        marker = (
            "dqc-full-taxonomy-ruleset-v1:"
            + selected.taxonomy_namespace
            + ":"
            + selected.sha256
        )
        if marker not in report.validation_evidence:
            raise SnapshotError(
                "VALIDATION_EVIDENCE_MISSING",
                "full DQC taxonomy selection evidence is missing",
            )
