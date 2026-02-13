from __future__ import annotations

from dataclasses import dataclass

from src.agents.technical.interface.contracts import TechnicalArtifactModel
from src.common.contracts import (
    ARTIFACT_KIND_PRICE_SERIES,
    ARTIFACT_KIND_TA_CHART_DATA,
    ARTIFACT_KIND_TA_FULL_REPORT,
)
from src.common.types import JSONObject
from src.interface.artifact_api_models import (
    PriceSeriesArtifactData,
    TechnicalChartArtifactData,
)
from src.interface.canonical_serializers import canonicalize_technical_artifact_data
from src.services.artifact_manager import artifact_manager
from src.shared.data.typed_artifact_port import TypedArtifactPort


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
        self, artifact_id: str
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
        self, artifact_id: str
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
        canonical = canonicalize_technical_artifact_data(data)
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
        price_data = (
            await self.load_price_series(price_artifact_id)
            if isinstance(price_artifact_id, str)
            else None
        )
        chart_data = (
            await self.load_chart_data(chart_artifact_id)
            if isinstance(chart_artifact_id, str)
            else None
        )
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
