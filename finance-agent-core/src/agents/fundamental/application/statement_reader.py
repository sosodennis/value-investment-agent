from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from datetime import datetime
from urllib.parse import quote
from uuid import NAMESPACE_URL, uuid5

from pydantic import ValidationError

from src.agents.fundamental.application.fundamental_service_port import (
    FundamentalServiceClient,
    FundamentalServiceFailure,
)
from src.agents.fundamental.application.statement_reader_contracts import (
    StatementArtifactResponseV2,
    StatementCatalogV2,
    StatementExistingThreadIntentV2,
    StatementReadIntentV2,
    StatementSavedArtifactIntentV2,
)
from src.artifacts.public import (
    ArtifactCurrentReadFailure,
    ArtifactReference,
    ArtifactService,
)
from src.shared.artifacts.annual_statement_contracts import (
    AnnualStatementsReadRequestV1,
)
from src.shared.artifacts.artifact_data_models import FinancialReportsArtifactData
from src.shared.artifacts.fiscal_statement_contracts import (
    FiscalReadRequestV2,
    fiscal_digest,
)
from src.shared.artifacts.statement_read_artifact import (
    FiscalSavedReadV3,
    StatementEditionV2,
    StatementReadArtifactV3,
)
from src.shared.internal_services import InternalPrincipal


class StatementReaderService:
    def __init__(
        self,
        *,
        client: FundamentalServiceClient,
        artifacts: ArtifactService,
        editions: tuple[StatementEditionV2, ...],
        owns_thread: Callable[[str, str, str], Awaitable[bool]],
        claim_thread: Callable[[str, str, str], Awaitable[bool]],
    ) -> None:
        if len({item.edition_id for item in editions}) != len(editions):
            raise ValueError("Statement edition selectors must be unique")
        self._editions = {item.edition_id: item for item in editions}
        self._client = client
        self._artifacts = artifacts
        self._owns_thread = owns_thread
        self._claim_thread = claim_thread

    def catalog(self) -> StatementCatalogV2:
        return StatementCatalogV2(entries=tuple(self._editions.values()))

    async def read(
        self,
        intent: StatementReadIntentV2,
        *,
        principal: InternalPrincipal,
        correlation_id: str,
        deadline_at: datetime,
    ) -> StatementArtifactResponseV2:
        if isinstance(intent, StatementSavedArtifactIntentV2):
            thread_id = intent.thread_id
            edition = await self._saved_edition(intent, principal)
        else:
            selected = self._editions.get(intent.edition_id)
            if selected is None:
                raise FundamentalServiceFailure(
                    "STATEMENT_EDITION_NOT_FOUND",
                    "Statement edition not found",
                    retryable=False,
                    status_code=404,
                )
            edition = selected
            if isinstance(intent, StatementExistingThreadIntentV2):
                thread_id = intent.thread_id
                check = self._owns_thread
            else:
                identity = json.dumps(
                    [
                        "statement-thread-v2",
                        principal.subject_id,
                        principal.organization_id,
                        str(intent.creation_id),
                    ],
                    separators=(",", ":"),
                )
                thread_id = f"thread_{uuid5(NAMESPACE_URL, identity)}"
                check = self._claim_thread
            if not principal.organization_id or not await check(
                principal.subject_id, thread_id, principal.organization_id
            ):
                raise FundamentalServiceFailure(
                    "THREAD_NOT_FOUND",
                    "Thread not found",
                    retryable=False,
                    status_code=404,
                )
        if intent.frequency == "annual":
            annual = await self._client.read_annual_statements(
                AnnualStatementsReadRequestV1(
                    data_release_manifest_digest=edition.annual_manifest_digest,
                    cutoff_at=edition.cutoff_at,
                ),
                principal=principal,
                correlation_id=correlation_id,
                deadline_at=deadline_at,
            )
            try:
                saved = StatementReadArtifactV3.from_annual(
                    edition=edition, response=annual
                )
            except ValidationError as error:
                raise FundamentalServiceFailure(
                    "STATEMENT_READ_BINDING_MISMATCH",
                    "Annual statement scope differs from edition",
                    retryable=False,
                    status_code=502,
                ) from error
        else:
            request = FiscalReadRequestV2(
                manifest_digest=edition.fiscal_manifest_digest,
                scope=edition.scope,
                cutoff_at=edition.cutoff_at,
                frequency=intent.frequency,
            )
            result = await self._client.read_fiscal_statements(
                request,
                principal=principal,
                correlation_id=correlation_id,
                deadline_at=deadline_at,
            )
            try:
                saved = StatementReadArtifactV3.from_fiscal(
                    edition=edition, request=request, result=result
                )
            except ValidationError as error:
                raise FundamentalServiceFailure(
                    "STATEMENT_READ_BINDING_MISMATCH",
                    "Fiscal statements differ from edition request",
                    retryable=False,
                    status_code=502,
                ) from error
        payload = FinancialReportsArtifactData(
            statement_read=saved, model_type="statement_read", status="done"
        )
        artifact_id = await self._artifacts.save_thread_artifact(
            data=payload.model_dump(mode="json"),
            artifact_type="financial_reports",
            produced_by="fundamental_analysis",
            thread_id=thread_id,
        )
        return StatementArtifactResponseV2(
            edition_id=saved.edition.edition_id,
            frequency=saved.frequency,
            thread_id=thread_id,
            reference=ArtifactReference(
                artifact_id=artifact_id,
                download_url=f"/api/v1/artifacts/{artifact_id}?thread_id={quote(thread_id, safe='')}",
                type="financial_reports",
            ),
        )

    async def _saved_edition(
        self, intent: StatementSavedArtifactIntentV2, principal: InternalPrincipal
    ) -> StatementEditionV2:
        if not principal.organization_id or not await self._owns_thread(
            principal.subject_id, intent.thread_id, principal.organization_id
        ):
            raise FundamentalServiceFailure(
                "THREAD_NOT_FOUND", "Thread not found", retryable=False, status_code=404
            )
        if (
            await self._artifacts.get_artifact_thread_id(intent.artifact_id)
            != intent.thread_id
            or not await self._artifacts.belongs_to_organization(
                thread_id=intent.thread_id, organization_id=principal.organization_id
            )
            or await self._artifacts.is_agent_output_reference(
                artifact_id=intent.artifact_id, thread_id=intent.thread_id
            )
            or await self._artifacts.is_referenced_artifact_reference(
                artifact_id=intent.artifact_id, thread_id=intent.thread_id
            )
        ):
            raise FundamentalServiceFailure(
                "ARTIFACT_NOT_FOUND",
                "Artifact not found",
                retryable=False,
                status_code=404,
            )
        envelope = await self._artifacts.get_artifact_envelope(intent.artifact_id)
        if (
            envelope is None
            or envelope.kind != "financial_reports"
            or envelope.version != "v1"
            or envelope.produced_by != "fundamental_analysis"
        ):
            raise self._selection_unavailable()
        try:
            payload = FinancialReportsArtifactData.model_validate(envelope.data)
        except ValidationError as error:
            raise self._selection_unavailable() from error
        if payload.statement_read is None:
            raise self._selection_unavailable()
        return payload.statement_read.edition

    @staticmethod
    def _selection_unavailable() -> FundamentalServiceFailure:
        return FundamentalServiceFailure(
            "STATEMENT_SAVED_SELECTION_UNAVAILABLE",
            "Saved statement selection is unavailable",
            retryable=False,
            status_code=404,
        )


class FiscalArtifactCurrentReader:
    def __init__(self, client: FundamentalServiceClient) -> None:
        self._client = client

    async def check_current(
        self,
        artifact: FiscalSavedReadV3,
        *,
        principal: InternalPrincipal,
        correlation_id: str,
        deadline_at: datetime,
    ) -> None:
        try:
            current = await self._client.read_fiscal_statements(
                artifact.request,
                principal=principal,
                correlation_id=correlation_id,
                deadline_at=deadline_at,
            )
        except FundamentalServiceFailure as error:
            raise ArtifactCurrentReadFailure(
                error.code,
                retryable=error.retryable,
                status_code=error.status_code
                if error.status_code in {404, 408, 429, 503}
                else 502,
            ) from error
        if fiscal_digest(current) != artifact.result_digest:
            raise ArtifactCurrentReadFailure(
                "STATEMENT_ARTIFACT_CURRENT_MISMATCH", retryable=False, status_code=502
            )
