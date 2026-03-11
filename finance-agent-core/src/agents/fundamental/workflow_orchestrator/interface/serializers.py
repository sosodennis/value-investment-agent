from __future__ import annotations

from src.agents.fundamental.artifacts_provenance.interface.contracts import (
    parse_fundamental_artifact_model,
)
from src.agents.fundamental.financial_statements.interface.contracts import (
    parse_financial_reports_model,
)
from src.agents.fundamental.forward_signals.interface.contracts import (
    ForwardSignalPayload,
)
from src.agents.fundamental.forward_signals.interface.serializers import (
    serialize_forward_signals,
)
from src.interface.events.schemas import ArtifactReference, build_artifact_payload
from src.shared.kernel.contracts import (
    ARTIFACT_KIND_FINANCIAL_REPORTS,
    OUTPUT_KIND_FUNDAMENTAL_ANALYSIS,
)
from src.shared.kernel.types import AgentOutputArtifactPayload, JSONObject


def normalize_model_selection_reports(
    financial_reports: list[JSONObject],
) -> list[JSONObject]:
    return parse_financial_reports_model(
        financial_reports, context="model_selection.financial_reports"
    )


def build_model_selection_report_payload(
    *,
    ticker: str,
    model_type: str,
    company_name: str,
    sector: str,
    industry: str,
    reasoning: str,
    normalized_reports: list[JSONObject],
    forward_signals: list[ForwardSignalPayload] | None = None,
) -> JSONObject:
    payload: JSONObject = {
        "ticker": ticker,
        "model_type": model_type,
        "company_name": company_name,
        "sector": sector,
        "industry": industry,
        "reasoning": reasoning,
        "financial_reports": normalized_reports,
        "status": "done",
    }
    if forward_signals:
        serialized_signals = serialize_forward_signals(forward_signals)
        if serialized_signals is not None:
            payload["forward_signals"] = serialized_signals
    return parse_fundamental_artifact_model(payload)


def build_model_selection_artifact(
    *,
    ticker: str,
    report_id: str,
    preview: JSONObject,
) -> AgentOutputArtifactPayload:
    reference = ArtifactReference(
        artifact_id=report_id,
        download_url=f"/api/artifacts/{report_id}",
        type=ARTIFACT_KIND_FINANCIAL_REPORTS,
    )
    return build_artifact_payload(
        kind=OUTPUT_KIND_FUNDAMENTAL_ANALYSIS,
        summary=f"基本面分析: {preview.get('company_name', ticker)} ({preview.get('selected_model')})",
        preview=preview,
        reference=reference,
    )


def build_valuation_artifact(
    *,
    ticker: str | None,
    model_type: str,
    reports_artifact_id: str,
    preview: JSONObject,
) -> AgentOutputArtifactPayload:
    reference = ArtifactReference(
        artifact_id=reports_artifact_id,
        download_url=f"/api/artifacts/{reports_artifact_id}",
        type=ARTIFACT_KIND_FINANCIAL_REPORTS,
    )
    return build_artifact_payload(
        kind=OUTPUT_KIND_FUNDAMENTAL_ANALYSIS,
        summary=f"估值完成: {ticker or 'UNKNOWN'} ({model_type})",
        preview=preview,
        reference=reference,
    )
