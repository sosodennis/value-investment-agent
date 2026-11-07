from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from src.agents.debate.application.dto import (
    DebateSourceData,
    DebateSourceLoadIssue,
)
from src.artifacts.public import (
    ARTIFACT_KIND_NEWS_ANALYSIS_REPORT,
    ARTIFACT_KIND_TA_FULL_REPORT,
    TypedArtifactPort,
    build_default_artifact_service,
    build_typed_artifact_port,
)
from src.shared.artifacts.news_contracts import NewsArtifactModel
from src.shared.artifacts.technical_contracts import TechnicalArtifactModel
from src.shared.kernel.types import JSONObject


@dataclass(frozen=True)
class _ArtifactLoadResult:
    payload: list[JSONObject] | JSONObject | None
    issue: DebateSourceLoadIssue | None
    valuation_preview: JSONObject | None = None


async def _load_news_items(
    port: TypedArtifactPort[NewsArtifactModel],
    artifact_id: str | None,
) -> _ArtifactLoadResult:
    if not isinstance(artifact_id, str):
        return _ArtifactLoadResult(
            payload=[],
            issue=DebateSourceLoadIssue(
                artifact="news",
                status="missing_artifact_id",
                artifact_id=None,
            ),
        )
    payload = await port.load(
        artifact_id,
        context=f"artifact {artifact_id} {ARTIFACT_KIND_NEWS_ANALYSIS_REPORT}",
    )
    if payload is None:
        return _ArtifactLoadResult(
            payload=[],
            issue=DebateSourceLoadIssue(
                artifact="news",
                status="artifact_not_found",
                artifact_id=artifact_id,
            ),
        )
    dumped = payload.model_dump(mode="json", exclude_none=True)
    news_items = dumped.get("news_items")
    if not isinstance(news_items, list):
        raise TypeError(
            f"artifact {artifact_id} {ARTIFACT_KIND_NEWS_ANALYSIS_REPORT} "
            "missing news_items list"
        )
    items = cast(list[JSONObject], news_items)
    if not items:
        return _ArtifactLoadResult(
            payload=items,
            issue=DebateSourceLoadIssue(
                artifact="news",
                status="empty_payload",
                artifact_id=artifact_id,
            ),
        )
    return _ArtifactLoadResult(payload=items, issue=None)


async def _load_technical_payload(
    port: TypedArtifactPort[TechnicalArtifactModel],
    artifact_id: str | None,
) -> _ArtifactLoadResult:
    if not isinstance(artifact_id, str):
        return _ArtifactLoadResult(
            payload=None,
            issue=DebateSourceLoadIssue(
                artifact="technical_analysis",
                status="missing_artifact_id",
                artifact_id=None,
            ),
        )
    payload = await port.load_json(
        artifact_id,
        context=f"artifact {artifact_id} {ARTIFACT_KIND_TA_FULL_REPORT}",
    )
    if payload is None:
        return _ArtifactLoadResult(
            payload=None,
            issue=DebateSourceLoadIssue(
                artifact="technical_analysis",
                status="artifact_not_found",
                artifact_id=artifact_id,
            ),
        )
    if not payload:
        return _ArtifactLoadResult(
            payload=payload,
            issue=DebateSourceLoadIssue(
                artifact="technical_analysis",
                status="empty_payload",
                artifact_id=artifact_id,
            ),
        )
    return _ArtifactLoadResult(payload=payload, issue=None)


@dataclass(frozen=True)
class DebateSourceReaderRepository:
    news_report_port: TypedArtifactPort[NewsArtifactModel]
    technical_report_port: TypedArtifactPort[TechnicalArtifactModel]

    async def load_debate_source_data(
        self,
        *,
        news_artifact_id: str | None,
        technical_artifact_id: str | None,
    ) -> DebateSourceData:
        news_items_result = await _load_news_items(
            self.news_report_port,
            news_artifact_id,
        )
        technical_payload_result = await _load_technical_payload(
            self.technical_report_port,
            technical_artifact_id,
        )
        load_issues = [
            DebateSourceLoadIssue(
                artifact="financial_reports",
                status="service_snapshot_unavailable",
                artifact_id=None,
            ),
            *[
                issue
                for issue in (
                    news_items_result.issue,
                    technical_payload_result.issue,
                )
                if issue is not None
            ],
        ]
        return DebateSourceData(
            financial_reports=[],
            news_items=cast(list[JSONObject], news_items_result.payload),
            technical_payload=cast(JSONObject | None, technical_payload_result.payload),
            valuation_preview=None,
            load_issues=load_issues,
        )


def build_default_debate_source_reader_repository() -> DebateSourceReaderRepository:
    storage = build_default_artifact_service()
    return DebateSourceReaderRepository(
        news_report_port=build_typed_artifact_port(
            storage=storage,
            kind=ARTIFACT_KIND_NEWS_ANALYSIS_REPORT,
            model=NewsArtifactModel,
        ),
        technical_report_port=build_typed_artifact_port(
            storage=storage,
            kind=ARTIFACT_KIND_TA_FULL_REPORT,
            model=TechnicalArtifactModel,
        ),
    )


debate_source_reader_repository = build_default_debate_source_reader_repository()


async def load_debate_source_data(
    *,
    news_artifact_id: str | None,
    technical_artifact_id: str | None,
) -> DebateSourceData:
    return await debate_source_reader_repository.load_debate_source_data(
        news_artifact_id=news_artifact_id,
        technical_artifact_id=technical_artifact_id,
    )
