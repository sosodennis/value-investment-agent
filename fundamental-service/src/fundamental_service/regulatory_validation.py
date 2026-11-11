"""Shared SEC EFM/DQC completion gate for ingestion and released evidence."""

from .arelle_parser import ArelleParseReportV1
from .historical_dqc import historical_profile
from .snapshots import SnapshotError


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
