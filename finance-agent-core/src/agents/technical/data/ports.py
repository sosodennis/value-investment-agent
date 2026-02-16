from __future__ import annotations

from dataclasses import dataclass

from src.agents.technical.interface.contracts import (
    TechnicalArtifactModel,
    parse_technical_artifact_model,
)
from src.interface.artifacts.artifact_data_models import (
    PriceSeriesArtifactData,
    TechnicalChartArtifactData,
)
from src.services.artifact_manager import artifact_manager
from src.shared.cross_agent.data.typed_artifact_port import TypedArtifactPort
from src.shared.kernel.contracts import (
    ARTIFACT_KIND_PRICE_SERIES,
    ARTIFACT_KIND_TA_CHART_DATA,
    ARTIFACT_KIND_TA_FULL_REPORT,
)
from src.shared.kernel.types import JSONObject


@dataclass
class TechnicalArtifactPort:
    price_series_port: TypedArtifactPort[PriceSeriesArtifactData]
    chart_data_port: TypedArtifactPort[TechnicalChartArtifactData]
    full_report_port: TypedArtifactPort[TechnicalArtifactModel]

    async def save_price_series(
        self,
        data: JSONObject,
        *,
        produced_by: str,
        key_prefix: str | None = None,
    ) -> str:
        return await self.price_series_port.save(
            data,
            produced_by=produced_by,
            key_prefix=key_prefix,
        )

    async def load_price_series(
        self, artifact_id: object
    ) -> PriceSeriesArtifactData | None:
        return await self.price_series_port.load(
            artifact_id,
            context=f"artifact {artifact_id} price_series data",
        )

    async def save_chart_data(
        self,
        data: JSONObject,
        *,
        produced_by: str,
        key_prefix: str | None = None,
    ) -> str:
        return await self.chart_data_port.save(
            data,
            produced_by=produced_by,
            key_prefix=key_prefix,
        )

    async def load_chart_data(
        self, artifact_id: object
    ) -> TechnicalChartArtifactData | None:
        return await self.chart_data_port.load(
            artifact_id,
            context=f"artifact {artifact_id} ta_chart_data",
        )

    async def save_full_report(
        self,
        data: JSONObject,
        *,
        produced_by: str,
        key_prefix: str | None = None,
    ) -> str:
        return await self.full_report_port.save(
            data,
            produced_by=produced_by,
            key_prefix=key_prefix,
        )

    async def save_full_report_canonical(
        self,
        data: object,
        *,
        produced_by: str,
        key_prefix: str | None = None,
    ) -> str:
        canonical = parse_technical_artifact_model(data)
        return await self.save_full_report(
            canonical,
            produced_by=produced_by,
            key_prefix=key_prefix,
        )

    async def load_price_and_chart_data(
        self,
        price_artifact_id: object,
        chart_artifact_id: object,
    ) -> tuple[PriceSeriesArtifactData | None, TechnicalChartArtifactData | None]:
        price_data = await self.load_price_series(price_artifact_id)
        chart_data = await self.load_chart_data(chart_artifact_id)
        return price_data, chart_data


technical_artifact_port = TechnicalArtifactPort(
    price_series_port=TypedArtifactPort(
        manager=artifact_manager,
        kind=ARTIFACT_KIND_PRICE_SERIES,
        model=PriceSeriesArtifactData,
    ),
    chart_data_port=TypedArtifactPort(
        manager=artifact_manager,
        kind=ARTIFACT_KIND_TA_CHART_DATA,
        model=TechnicalChartArtifactData,
    ),
    full_report_port=TypedArtifactPort(
        manager=artifact_manager,
        kind=ARTIFACT_KIND_TA_FULL_REPORT,
        model=TechnicalArtifactModel,
    ),
)
