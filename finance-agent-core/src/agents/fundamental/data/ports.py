from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from src.common.contracts import ARTIFACT_KIND_FINANCIAL_REPORTS
from src.common.types import JSONObject
from src.interface.artifact_api_models import FinancialReportsArtifactData
from src.services.artifact_manager import artifact_manager
from src.shared.data.typed_artifact_port import TypedArtifactPort


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
        self, artifact_id: str
    ) -> FinancialReportsArtifactData | None:
        return await self.financial_reports_port.load(
            artifact_id,
            context=f"artifact {artifact_id} financial_reports data",
        )

    async def load_financial_reports(self, artifact_id: str) -> list[JSONObject] | None:
        payload = await self.load_financial_reports_payload(artifact_id)
        if payload is None:
            return None
        dumped = payload.model_dump(mode="json")
        reports = dumped.get("financial_reports")
        if not isinstance(reports, list):
            raise TypeError(f"artifact {artifact_id} financial_reports must be a list")
        return cast(list[JSONObject], reports)


fundamental_artifact_port = FundamentalArtifactPort(
    financial_reports_port=TypedArtifactPort(
        manager=artifact_manager,
        kind=ARTIFACT_KIND_FINANCIAL_REPORTS,
        model=FinancialReportsArtifactData,
    )
)
