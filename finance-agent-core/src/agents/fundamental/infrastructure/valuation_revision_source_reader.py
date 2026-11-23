"""Read complete valuation sources through the authenticated artifact facade."""

from collections.abc import Awaitable, Callable

from src.agents.fundamental.application.fundamental_service_port import (
    FundamentalServiceFailure,
)
from src.agents.fundamental.interface.request_contracts import (
    FundamentalValuationRevisionSourceV1,
)
from src.artifacts.public import (
    ARTIFACT_KIND_FINANCIAL_REPORTS,
    ArtifactService,
    parse_artifact_data_model_as,
)
from src.shared.artifacts.artifact_data_models import FinancialReportsArtifactData
from src.shared.artifacts.fundamental_contracts import FundamentalValuationReportV1
from src.shared.internal_services import InternalPrincipal


class ArtifactFundamentalRevisionSourceReader:
    def __init__(
        self,
        *,
        artifacts: ArtifactService,
        owns_thread: Callable[[str, str], Awaitable[bool]],
    ) -> None:
        self._artifacts = artifacts
        self._owns_thread = owns_thread

    async def read_source(
        self,
        source: FundamentalValuationRevisionSourceV1,
        *,
        principal: InternalPrincipal,
        current_thread_id: str,
    ) -> FundamentalValuationReportV1:
        try:
            return await self._read_authenticated_source(
                source, principal=principal, current_thread_id=current_thread_id
            )
        except FundamentalServiceFailure:
            raise
        except Exception as error:
            raise FundamentalServiceFailure(
                "REVISION_SOURCE_UNAVAILABLE",
                "Retained valuation source storage is unavailable",
                retryable=True,
                status_code=503,
            ) from error

    async def _read_authenticated_source(
        self,
        source: FundamentalValuationRevisionSourceV1,
        *,
        principal: InternalPrincipal,
        current_thread_id: str,
    ) -> FundamentalValuationReportV1:
        if source.thread_id != current_thread_id:
            raise self._not_found()
        thread_id = await self._artifacts.get_run_thread_id(
            run_id=source.run_id, organization_id=principal.organization_id
        )
        if thread_id != source.thread_id or not await self._owns_thread(
            principal.subject_id, source.thread_id
        ):
            raise self._not_found()
        if (
            await self._artifacts.get_artifact_thread_id(source.artifact_id)
            != source.thread_id
        ):
            raise self._not_found()
        if not await self._artifacts.is_agent_output_for_run(
            artifact_id=source.artifact_id,
            thread_id=source.thread_id,
            run_id=source.run_id,
        ):
            raise self._not_found()
        try:
            data = await self._artifacts.get_artifact_data(
                source.artifact_id, expected_kind=ARTIFACT_KIND_FINANCIAL_REPORTS
            )
            if data is None:
                raise self._not_found()
            parsed = parse_artifact_data_model_as(
                ARTIFACT_KIND_FINANCIAL_REPORTS,
                data,
                model=FinancialReportsArtifactData,
                context="retained valuation revision source",
            )
        except (TypeError, ValueError) as error:
            raise FundamentalServiceFailure(
                "REVISION_SOURCE_INVALID",
                "Retained valuation source is incomplete or invalid",
                retryable=False,
                status_code=422,
            ) from error
        if not isinstance(parsed.fundamental_service, FundamentalValuationReportV1):
            raise FundamentalServiceFailure(
                "REVISION_SOURCE_INVALID",
                "Revision source must be a complete valuation report",
                retryable=False,
                status_code=422,
            )
        return parsed.fundamental_service

    @staticmethod
    def _not_found() -> FundamentalServiceFailure:
        return FundamentalServiceFailure(
            "REVISION_SOURCE_NOT_FOUND",
            "Retained valuation source is unavailable for this run and principal",
            retryable=False,
            status_code=404,
        )
