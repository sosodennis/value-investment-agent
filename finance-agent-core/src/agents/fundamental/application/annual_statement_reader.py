"""Read prepared statements independently of valuation and retain exact evidence."""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime
from urllib.parse import quote
from uuid import NAMESPACE_URL, uuid5

from src.agents.fundamental.application.annual_statement_reader_contracts import (
    AnnualStatementArtifactResponse,
    AnnualStatementCatalogEntry,
    AnnualStatementCatalogResponse,
    AnnualStatementExistingThreadReadIntent,
    AnnualStatementReaderBinding,
    AnnualStatementReadIntent,
)
from src.agents.fundamental.application.fundamental_service_port import (
    FundamentalServiceClient,
    FundamentalServiceFailure,
)
from src.artifacts.public import ArtifactReference, ArtifactService
from src.shared.artifacts.annual_statement_contracts import (
    AnnualStatementsReadRequestV1,
)
from src.shared.artifacts.artifact_data_models import FinancialReportsArtifactData
from src.shared.internal_services import InternalPrincipal

logger = logging.getLogger(__name__)


class AnnualStatementReaderService:
    def __init__(
        self,
        *,
        client: FundamentalServiceClient,
        artifacts: ArtifactService,
        bindings: tuple[AnnualStatementReaderBinding, ...],
        owns_thread: Callable[[str, str, str], Awaitable[bool]],
        claim_thread: Callable[[str, str, str], Awaitable[bool]],
    ) -> None:
        self._client = client
        self._artifacts = artifacts
        self._bindings = {binding.issuer_id: binding for binding in bindings}
        self._owns_thread = owns_thread
        self._claim_thread = claim_thread

    def catalog(self) -> AnnualStatementCatalogResponse:
        return AnnualStatementCatalogResponse(
            entries=tuple(
                AnnualStatementCatalogEntry.model_validate(
                    binding.model_dump(
                        include={"issuer_id", "ticker", "company_name", "cutoff_at"}
                    )
                )
                for binding in self._bindings.values()
            )
        )

    async def read(
        self,
        intent: AnnualStatementReadIntent,
        *,
        principal: InternalPrincipal,
        correlation_id: str,
        deadline_at: datetime,
    ) -> AnnualStatementArtifactResponse:
        binding = self._bindings.get(intent.issuer_id)
        if binding is None:
            raise FundamentalServiceFailure(
                "STATEMENT_READER_UNAVAILABLE",
                "No prepared annual statement reader is configured for this issuer",
                retryable=False,
                status_code=404,
            )
        if isinstance(intent, AnnualStatementExistingThreadReadIntent):
            thread_id = intent.thread_id
            check = self._owns_thread
        else:
            identity = json.dumps(
                [
                    "annual-statement-thread-v1",
                    principal.subject_id,
                    principal.organization_id,
                    str(intent.creation_id),
                ],
                separators=(",", ":"),
            )
            thread_id = f"thread_{uuid5(NAMESPACE_URL, identity)}"
            check = self._claim_thread
        authorized = False
        if principal.organization_id:
            authorized = await check(
                principal.subject_id, thread_id, principal.organization_id
            )
        if not authorized:
            raise FundamentalServiceFailure(
                "THREAD_NOT_FOUND", "Thread not found", retryable=False, status_code=404
            )
        try:
            active = await self._client.read_active_release(
                binding.profile_id,
                principal=principal,
                correlation_id=correlation_id,
                deadline_at=deadline_at,
            )
            result = await self._client.read_annual_statements(
                AnnualStatementsReadRequestV1(
                    data_release_manifest_digest=active.active.manifest_digest,
                    cutoff_at=binding.cutoff_at,
                ),
                principal=principal,
                correlation_id=correlation_id,
                deadline_at=deadline_at,
            )
            if (
                result.statements.scope.issuer_id != binding.issuer_id
                or result.statements.scope.security_id != binding.security_id
                or result.statements.scope.security_scope != binding.security_scope
                or result.statements.cutoff_at != binding.cutoff_at
                or result.data_release_manifest_digest != active.active.manifest_digest
            ):
                raise FundamentalServiceFailure(
                    "STATEMENT_READ_BINDING_MISMATCH",
                    "Prepared statements do not match the requested issuer and cutoff",
                    retryable=False,
                    status_code=502,
                )
            payload = FinancialReportsArtifactData(
                annual_statements=result,
                ticker=binding.ticker,
                company_name=binding.company_name,
                model_type="annual_statements",
                status="done",
            )
            artifact_id = await self._artifacts.save_thread_artifact(
                data=payload.model_dump(mode="json"),
                artifact_type="financial_reports",
                produced_by="fundamental_analysis",
                thread_id=thread_id,
            )
        except FundamentalServiceFailure as error:
            logger.warning(
                "fundamental.annual_statements.read_failed",
                extra={"correlation_id": correlation_id, "code": error.code},
            )
            raise
        logger.info(
            "fundamental.annual_statements.read_completed",
            extra={
                "correlation_id": correlation_id,
                "quality": result.statements.quality_status,
            },
        )
        return AnnualStatementArtifactResponse(
            thread_id=thread_id,
            reference=ArtifactReference(
                artifact_id=artifact_id,
                download_url=f"/api/v1/artifacts/{artifact_id}?thread_id={quote(thread_id, safe='')}",
                type="financial_reports",
            ),
        )
