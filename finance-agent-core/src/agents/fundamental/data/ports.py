from __future__ import annotations

from dataclasses import dataclass

from src.agents.fundamental.interface.contracts import FinancialReportModel
from src.interface.artifacts.artifact_data_models import FinancialReportsArtifactData
from src.services.artifact_manager import artifact_manager
from src.shared.cross_agent.data.typed_artifact_port import TypedArtifactPort
from src.shared.kernel.contracts import ARTIFACT_KIND_FINANCIAL_REPORTS
from src.shared.kernel.types import JSONObject


@dataclass
class FundamentalArtifactPort:
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
        self, artifact_id: object
    ) -> FinancialReportsArtifactData | None:
        return await self.financial_reports_port.load(
            artifact_id,
            context=f"artifact {artifact_id} financial_reports data",
        )

    async def load_financial_report_models(
        self, artifact_id: object
    ) -> list[FinancialReportModel] | None:
        payload = await self.load_financial_reports_payload(artifact_id)
        if payload is None:
            return None
        return payload.financial_reports

    async def load_financial_reports(
        self, artifact_id: object
    ) -> list[JSONObject] | None:
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


fundamental_artifact_port = FundamentalArtifactPort(
    financial_reports_port=TypedArtifactPort(
        manager=artifact_manager,
        kind=ARTIFACT_KIND_FINANCIAL_REPORTS,
        model=FinancialReportsArtifactData,
    )
)
