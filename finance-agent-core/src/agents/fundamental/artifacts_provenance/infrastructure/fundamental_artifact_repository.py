from __future__ import annotations

from dataclasses import dataclass

from src.agents.fundamental.financial_statements.interface.contracts import (
    FinancialReportModel,
)
from src.interface.artifacts.artifact_data_models import FinancialReportsArtifactData
from src.services.artifact_manager import artifact_manager
from src.shared.cross_agent.data.typed_artifact_port import TypedArtifactPort
from src.shared.kernel.contracts import ARTIFACT_KIND_FINANCIAL_REPORTS
from src.shared.kernel.types import JSONObject


def _normalize_forward_signals(raw: object) -> list[JSONObject] | None:
    if not isinstance(raw, list):
        return None
    normalized: list[JSONObject] = []
    for item in raw:
        if isinstance(item, dict):
            normalized.append(item)
    return normalized or None


@dataclass
class FundamentalArtifactRepository:
    financial_reports_port: TypedArtifactPort[FinancialReportsArtifactData]

    async def save_financial_reports(
        self,
        data: JSONObject,
        *,
        produced_by: str,
        key_prefix: str | None = None,
    ) -> str:
        return await self.financial_reports_port.save(
            data,
            produced_by=produced_by,
            key_prefix=key_prefix,
        )

    async def load_financial_reports_payload(
        self, artifact_id: str
    ) -> FinancialReportsArtifactData | None:
        return await self.financial_reports_port.load(
            artifact_id,
            context=f"artifact {artifact_id} financial_reports data",
        )

    async def load_financial_report_models(
        self, artifact_id: str
    ) -> list[FinancialReportModel] | None:
        payload = await self.load_financial_reports_payload(artifact_id)
        if payload is None:
            return None
        return payload.financial_reports

    async def load_financial_reports(self, artifact_id: str) -> list[JSONObject] | None:
        payload = await self.financial_reports_port.load_json(
            artifact_id,
            context=f"artifact {artifact_id} financial_reports data",
        )
        if payload is None:
            return None
        financial_reports = payload.get("financial_reports")
        if not isinstance(financial_reports, list):
            raise TypeError(
                f"artifact {artifact_id} financial_reports data missing financial_reports list"
            )
        return financial_reports

    async def load_financial_reports_bundle(
        self, artifact_id: str
    ) -> tuple[list[JSONObject], list[JSONObject] | None] | None:
        payload = await self.financial_reports_port.load_json(
            artifact_id,
            context=f"artifact {artifact_id} financial_reports data",
        )
        if payload is None:
            return None
        reports_raw = payload.get("financial_reports")
        if not isinstance(reports_raw, list):
            raise TypeError(
                f"artifact {artifact_id} financial_reports data missing financial_reports list"
            )
        forward_signals = _normalize_forward_signals(payload.get("forward_signals"))
        return reports_raw, forward_signals


fundamental_artifact_repository = FundamentalArtifactRepository(
    financial_reports_port=TypedArtifactPort(
        manager=artifact_manager,
        kind=ARTIFACT_KIND_FINANCIAL_REPORTS,
        model=FinancialReportsArtifactData,
    )
)


__all__ = ["FundamentalArtifactRepository", "fundamental_artifact_repository"]
