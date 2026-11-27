from __future__ import annotations

from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from src.shared.artifacts.annual_statement_contracts import (
    AnnualStatementsReadResponseV1,
    StatementScopeV1,
)
from src.shared.artifacts.fiscal_statement_contracts import (
    Digest,
    FiscalReadRequestV2,
    FiscalReadResultV2,
    fiscal_digest,
)

StatementFrequency = Literal["annual", "quarter", "ttm"]


class StatementWorkspaceModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class StatementEditionV2(StatementWorkspaceModel):
    edition_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    label: str = Field(min_length=1)
    ticker: str = Field(min_length=1, max_length=32, pattern=r"^[A-Z0-9.-]+$")
    company_name: str = Field(min_length=1)
    scope: StatementScopeV1
    cutoff_at: AwareDatetime
    annual_manifest_digest: Digest
    fiscal_manifest_digest: Digest
    frequencies: tuple[Literal["annual"], Literal["quarter"], Literal["ttm"]] = (
        "annual",
        "quarter",
        "ttm",
    )


class AnnualSavedReadV2(StatementWorkspaceModel):
    kind: Literal["annual"] = "annual"
    response: AnnualStatementsReadResponseV1


class FiscalSavedReadV3(StatementWorkspaceModel):
    kind: Literal["fiscal"] = "fiscal"
    request: FiscalReadRequestV2
    result: FiscalReadResultV2
    result_digest: Digest

    @model_validator(mode="after")
    def exact_read(self) -> FiscalSavedReadV3:
        binding = self.result.binding
        if (
            binding.manifest_digest != self.request.manifest_digest
            or binding.scope != self.request.scope
            or binding.cutoff_at != self.request.cutoff_at
            or binding.columns.frequency != self.request.frequency
            or fiscal_digest(self.result) != self.result_digest
        ):
            raise ValueError("fiscal artifact differs from its exact read request")
        return self


SavedStatementReadV3 = Annotated[
    AnnualSavedReadV2 | FiscalSavedReadV3, Field(discriminator="kind")
]


class StatementReadArtifactV3(StatementWorkspaceModel):
    contract_version: Literal["workspace.statement-read.v3"] = (
        "workspace.statement-read.v3"
    )
    edition: StatementEditionV2
    read: SavedStatementReadV3

    @classmethod
    def from_annual(
        cls, *, edition: StatementEditionV2, response: AnnualStatementsReadResponseV1
    ) -> StatementReadArtifactV3:
        return cls(edition=edition, read=AnnualSavedReadV2(response=response))

    @classmethod
    def from_fiscal(
        cls,
        *,
        edition: StatementEditionV2,
        request: FiscalReadRequestV2,
        result: FiscalReadResultV2,
    ) -> StatementReadArtifactV3:
        return cls(
            edition=edition,
            read=FiscalSavedReadV3(
                request=request, result=result, result_digest=fiscal_digest(result)
            ),
        )

    @model_validator(mode="after")
    def exact_selection(self) -> StatementReadArtifactV3:
        if isinstance(self.read, AnnualSavedReadV2):
            response = self.read.response
            matches = (
                response.data_release_manifest_digest
                == self.edition.annual_manifest_digest
                and response.statements.scope == self.edition.scope
                and response.statements.cutoff_at == self.edition.cutoff_at
            )
        else:
            request = self.read.request
            matches = (
                request.manifest_digest == self.edition.fiscal_manifest_digest
                and request.scope == self.edition.scope
                and request.cutoff_at == self.edition.cutoff_at
            )
        if not matches:
            raise ValueError("statement read differs from its saved edition")
        return self

    @property
    def frequency(self) -> StatementFrequency:
        return (
            "annual"
            if isinstance(self.read, AnnualSavedReadV2)
            else self.read.request.frequency
        )
