from __future__ import annotations

from dataclasses import dataclass

from src.agents.technical.interface.contracts import (
    TechnicalArtifactModel,
    parse_technical_artifact_model,
)
from src.interface.artifacts.artifact_data_models import (
    PriceSeriesArtifactData,
    TechnicalAlertsArtifactData,
    TechnicalChartArtifactData,
    TechnicalDirectionScorecardArtifactData,
    TechnicalFeaturePackArtifactData,
    TechnicalFusionReportArtifactData,
    TechnicalIndicatorSeriesArtifactData,
    TechnicalPatternPackArtifactData,
    TechnicalRegimePackArtifactData,
    TechnicalTimeseriesBundleArtifactData,
    TechnicalVerificationReportArtifactData,
)
from src.services.artifact_manager import artifact_manager
from src.shared.cross_agent.data.typed_artifact_port import TypedArtifactPort
from src.shared.kernel.contracts import (
    ARTIFACT_KIND_PRICE_SERIES,
    ARTIFACT_KIND_TA_ALERTS,
    ARTIFACT_KIND_TA_CHART_DATA,
    ARTIFACT_KIND_TA_DIRECTION_SCORECARD,
    ARTIFACT_KIND_TA_FEATURE_PACK,
    ARTIFACT_KIND_TA_FULL_REPORT,
    ARTIFACT_KIND_TA_FUSION_REPORT,
    ARTIFACT_KIND_TA_INDICATOR_SERIES,
    ARTIFACT_KIND_TA_PATTERN_PACK,
    ARTIFACT_KIND_TA_REGIME_PACK,
    ARTIFACT_KIND_TA_TIMESERIES_BUNDLE,
    ARTIFACT_KIND_TA_VERIFICATION_REPORT,
)
from src.shared.kernel.types import JSONObject


@dataclass
class TechnicalArtifactRepository:
    price_series_port: TypedArtifactPort[PriceSeriesArtifactData]
    chart_data_port: TypedArtifactPort[TechnicalChartArtifactData]
    indicator_series_port: TypedArtifactPort[TechnicalIndicatorSeriesArtifactData]
    alerts_port: TypedArtifactPort[TechnicalAlertsArtifactData]
    timeseries_bundle_port: TypedArtifactPort[TechnicalTimeseriesBundleArtifactData]
    feature_pack_port: TypedArtifactPort[TechnicalFeaturePackArtifactData]
    pattern_pack_port: TypedArtifactPort[TechnicalPatternPackArtifactData]
    regime_pack_port: TypedArtifactPort[TechnicalRegimePackArtifactData]
    fusion_report_port: TypedArtifactPort[TechnicalFusionReportArtifactData]
    direction_scorecard_port: TypedArtifactPort[TechnicalDirectionScorecardArtifactData]
    verification_report_port: TypedArtifactPort[TechnicalVerificationReportArtifactData]
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
        self, artifact_id: str | None
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
        self, artifact_id: str | None
    ) -> TechnicalChartArtifactData | None:
        return await self.chart_data_port.load(
            artifact_id,
            context=f"artifact {artifact_id} ta_chart_data",
        )

    async def save_indicator_series(
        self,
        data: JSONObject,
        *,
        produced_by: str,
        key_prefix: str | None = None,
    ) -> str:
        return await self.indicator_series_port.save(
            data,
            produced_by=produced_by,
            key_prefix=key_prefix,
        )

    async def load_indicator_series(
        self, artifact_id: str | None
    ) -> TechnicalIndicatorSeriesArtifactData | None:
        return await self.indicator_series_port.load(
            artifact_id,
            context=f"artifact {artifact_id} ta_indicator_series",
        )

    async def save_alerts(
        self,
        data: JSONObject,
        *,
        produced_by: str,
        key_prefix: str | None = None,
    ) -> str:
        return await self.alerts_port.save(
            data,
            produced_by=produced_by,
            key_prefix=key_prefix,
        )

    async def load_alerts(
        self, artifact_id: str | None
    ) -> TechnicalAlertsArtifactData | None:
        return await self.alerts_port.load(
            artifact_id,
            context=f"artifact {artifact_id} ta_alerts",
        )

    async def save_timeseries_bundle(
        self,
        data: JSONObject,
        *,
        produced_by: str,
        key_prefix: str | None = None,
    ) -> str:
        return await self.timeseries_bundle_port.save(
            data,
            produced_by=produced_by,
            key_prefix=key_prefix,
        )

    async def load_timeseries_bundle(
        self, artifact_id: str | None
    ) -> TechnicalTimeseriesBundleArtifactData | None:
        return await self.timeseries_bundle_port.load(
            artifact_id,
            context=f"artifact {artifact_id} ta_timeseries_bundle",
        )

    async def save_feature_pack(
        self,
        data: JSONObject,
        *,
        produced_by: str,
        key_prefix: str | None = None,
    ) -> str:
        return await self.feature_pack_port.save(
            data,
            produced_by=produced_by,
            key_prefix=key_prefix,
        )

    async def load_feature_pack(
        self, artifact_id: str | None
    ) -> TechnicalFeaturePackArtifactData | None:
        return await self.feature_pack_port.load(
            artifact_id,
            context=f"artifact {artifact_id} ta_feature_pack",
        )

    async def save_pattern_pack(
        self,
        data: JSONObject,
        *,
        produced_by: str,
        key_prefix: str | None = None,
    ) -> str:
        return await self.pattern_pack_port.save(
            data,
            produced_by=produced_by,
            key_prefix=key_prefix,
        )

    async def load_pattern_pack(
        self, artifact_id: str | None
    ) -> TechnicalPatternPackArtifactData | None:
        return await self.pattern_pack_port.load(
            artifact_id,
            context=f"artifact {artifact_id} ta_pattern_pack",
        )

    async def save_regime_pack(
        self,
        data: JSONObject,
        *,
        produced_by: str,
        key_prefix: str | None = None,
    ) -> str:
        return await self.regime_pack_port.save(
            data,
            produced_by=produced_by,
            key_prefix=key_prefix,
        )

    async def load_regime_pack(
        self, artifact_id: str | None
    ) -> TechnicalRegimePackArtifactData | None:
        return await self.regime_pack_port.load(
            artifact_id,
            context=f"artifact {artifact_id} ta_regime_pack",
        )

    async def save_fusion_report(
        self,
        data: JSONObject,
        *,
        produced_by: str,
        key_prefix: str | None = None,
    ) -> str:
        return await self.fusion_report_port.save(
            data,
            produced_by=produced_by,
            key_prefix=key_prefix,
        )

    async def load_fusion_report(
        self, artifact_id: str | None
    ) -> TechnicalFusionReportArtifactData | None:
        return await self.fusion_report_port.load(
            artifact_id,
            context=f"artifact {artifact_id} ta_fusion_report",
        )

    async def save_direction_scorecard(
        self,
        data: JSONObject,
        *,
        produced_by: str,
        key_prefix: str | None = None,
    ) -> str:
        return await self.direction_scorecard_port.save(
            data,
            produced_by=produced_by,
            key_prefix=key_prefix,
        )

    async def load_direction_scorecard(
        self, artifact_id: str | None
    ) -> TechnicalDirectionScorecardArtifactData | None:
        return await self.direction_scorecard_port.load(
            artifact_id,
            context=f"artifact {artifact_id} ta_direction_scorecard",
        )

    async def save_verification_report(
        self,
        data: JSONObject,
        *,
        produced_by: str,
        key_prefix: str | None = None,
    ) -> str:
        return await self.verification_report_port.save(
            data,
            produced_by=produced_by,
            key_prefix=key_prefix,
        )

    async def load_verification_report(
        self, artifact_id: str | None
    ) -> TechnicalVerificationReportArtifactData | None:
        return await self.verification_report_port.load(
            artifact_id,
            context=f"artifact {artifact_id} ta_verification_report",
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
        data: JSONObject,
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
        price_artifact_id: str | None,
        chart_artifact_id: str | None,
    ) -> tuple[PriceSeriesArtifactData | None, TechnicalChartArtifactData | None]:
        price_data = await self.load_price_series(price_artifact_id)
        chart_data = await self.load_chart_data(chart_artifact_id)
        return price_data, chart_data


def build_default_technical_artifact_repository() -> TechnicalArtifactRepository:
    return TechnicalArtifactRepository(
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
        indicator_series_port=TypedArtifactPort(
            manager=artifact_manager,
            kind=ARTIFACT_KIND_TA_INDICATOR_SERIES,
            model=TechnicalIndicatorSeriesArtifactData,
        ),
        alerts_port=TypedArtifactPort(
            manager=artifact_manager,
            kind=ARTIFACT_KIND_TA_ALERTS,
            model=TechnicalAlertsArtifactData,
        ),
        timeseries_bundle_port=TypedArtifactPort(
            manager=artifact_manager,
            kind=ARTIFACT_KIND_TA_TIMESERIES_BUNDLE,
            model=TechnicalTimeseriesBundleArtifactData,
        ),
        feature_pack_port=TypedArtifactPort(
            manager=artifact_manager,
            kind=ARTIFACT_KIND_TA_FEATURE_PACK,
            model=TechnicalFeaturePackArtifactData,
        ),
        pattern_pack_port=TypedArtifactPort(
            manager=artifact_manager,
            kind=ARTIFACT_KIND_TA_PATTERN_PACK,
            model=TechnicalPatternPackArtifactData,
        ),
        regime_pack_port=TypedArtifactPort(
            manager=artifact_manager,
            kind=ARTIFACT_KIND_TA_REGIME_PACK,
            model=TechnicalRegimePackArtifactData,
        ),
        fusion_report_port=TypedArtifactPort(
            manager=artifact_manager,
            kind=ARTIFACT_KIND_TA_FUSION_REPORT,
            model=TechnicalFusionReportArtifactData,
        ),
        direction_scorecard_port=TypedArtifactPort(
            manager=artifact_manager,
            kind=ARTIFACT_KIND_TA_DIRECTION_SCORECARD,
            model=TechnicalDirectionScorecardArtifactData,
        ),
        verification_report_port=TypedArtifactPort(
            manager=artifact_manager,
            kind=ARTIFACT_KIND_TA_VERIFICATION_REPORT,
            model=TechnicalVerificationReportArtifactData,
        ),
        full_report_port=TypedArtifactPort(
            manager=artifact_manager,
            kind=ARTIFACT_KIND_TA_FULL_REPORT,
            model=TechnicalArtifactModel,
        ),
    )


__all__ = ["TechnicalArtifactRepository", "build_default_technical_artifact_repository"]
