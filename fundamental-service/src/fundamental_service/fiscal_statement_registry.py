from __future__ import annotations

import hashlib
from datetime import date
from importlib.resources import files
from typing import Annotated, Literal

from pydantic import AwareDatetime, ConfigDict, Field, model_validator

from .contracts import StrictModel
from .fiscal_discovery import FiscalDiscoveryEvidenceV1
from .fiscal_statement_contracts import FiscalDurationPeriodV1, FiscalStatement
from .serialization import sha256_digest
from .snapshots import SnapshotError
from .statement_contracts import StatementRowId

Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class FiscalPrimaryFactScopeV1(StrictModel):
    model_config = ConfigDict(frozen=True)

    observation_id: str
    row_id: StatementRowId
    statement: FiscalStatement
    fact_index: int = Field(ge=0)
    fact_id: str
    table_index: int = Field(ge=0)
    row_index: int = Field(ge=0)
    context_id: str
    concept: str
    namespace_uri: str
    period_start: date | None = None
    period_end: date | None = None
    instant: date | None = None
    unit: str
    cash_basis: str | None = None


class FiscalDisclosureScopeV1(StrictModel):
    model_config = ConfigDict(frozen=True)

    purpose: str
    xpath: str
    text_sha256: Digest


class FiscalPrimaryTableV1(StrictModel):
    model_config = ConfigDict(frozen=True)

    statement: FiscalStatement
    table_index: int = Field(ge=0)
    table_sha256: Digest
    missing_rows: tuple[StatementRowId, ...] = ()


class FiscalPrimaryScopeV1(StrictModel):
    model_config = ConfigDict(frozen=True)

    protocol: Literal["fundamental.fiscal-primary-scope.v1"] = (
        "fundamental.fiscal-primary-scope.v1"
    )
    issuer_id: str
    accession_number: str
    form: Literal["10-Q", "10-K"]
    accepted_at: AwareDatetime
    report_date: date
    primary_document: str
    primary_member_sha256: Digest
    archive_sha256: Digest
    fiscal_year_focus: int
    fiscal_period_focus: Literal["Q1", "Q2", "Q3", "FY"]
    tables: tuple[FiscalPrimaryTableV1, ...] = Field(min_length=3, max_length=3)
    facts: tuple[FiscalPrimaryFactScopeV1, ...] = Field(min_length=1)
    disclosures: tuple[FiscalDisclosureScopeV1, ...] = Field(min_length=1)
    reviewed_source_digest: Digest

    @model_validator(mode="after")
    def unique_scopes(self) -> FiscalPrimaryScopeV1:
        if len({item.observation_id for item in self.facts}) != len(self.facts):
            raise ValueError("primary fact scopes must be unique")
        if {item.statement for item in self.tables} != {
            "income_statement",
            "balance_sheet",
            "cash_flow",
        }:
            raise ValueError("primary scope requires all statement tables")
        return self


class FiscalRowBasisPlanV1(StrictModel):
    model_config = ConfigDict(frozen=True)

    row_id: StatementRowId
    observation_ids: tuple[str, ...]
    comparative_pairs: tuple[tuple[str, str], ...] = ()


class FiscalReportedQuarterContextV1(StrictModel):
    model_config = ConfigDict(frozen=True)

    kind: Literal["reported_quarter_context"] = "reported_quarter_context"
    fact_index: int = Field(ge=0)
    context_id: str


class FiscalFourthQuarterBoundaryV1(StrictModel):
    model_config = ConfigDict(frozen=True)

    kind: Literal["annual_minus_prior_boundary"] = "annual_minus_prior_boundary"
    annual_context_id: str
    preceding_accession_number: str
    preceding_quarter_end: date


class FiscalQuarterReviewV1(StrictModel):
    model_config = ConfigDict(frozen=True)

    accession_number: str
    period: FiscalDurationPeriodV1
    period_source: Annotated[
        FiscalReportedQuarterContextV1 | FiscalFourthQuarterBoundaryV1,
        Field(discriminator="kind"),
    ]
    rows: tuple[FiscalRowBasisPlanV1, ...]


class FiscalWindowBasisPlanV1(StrictModel):
    model_config = ConfigDict(frozen=True)

    end: date
    quarter_ends: tuple[date, ...] = Field(min_length=4, max_length=4)
    rows: tuple[FiscalRowBasisPlanV1, ...]


class FiscalReviewedCoverageV1(StrictModel):
    model_config = ConfigDict(frozen=True)

    protocol: Literal["fundamental.fiscal-reviewed-coverage.v1"] = (
        "fundamental.fiscal-reviewed-coverage.v1"
    )
    issuer_id: str
    source_accessions: tuple[str, ...]
    quarters: tuple[FiscalQuarterReviewV1, ...] = Field(min_length=1)
    ttm_windows: tuple[FiscalWindowBasisPlanV1, ...]
    reviewed_basis_digest: Digest


class FiscalRegistryEntryV1(StrictModel):
    model_config = ConfigDict(frozen=True)

    filename: str = Field(pattern=r"^fiscal-(?:scope|coverage)-[a-zA-Z0-9-]+\.json$")
    sha256: Digest


class FiscalStatementRegistryV1(StrictModel):
    model_config = ConfigDict(frozen=True)

    protocol: Literal["fundamental.fiscal-statement-registry.v1"] = (
        "fundamental.fiscal-statement-registry.v1"
    )
    sources: tuple[FiscalRegistryEntryV1, ...]
    coverage: tuple[FiscalRegistryEntryV1, ...]

    @property
    def digest(self) -> str:
        return sha256_digest(self)


def _resource(entry: FiscalRegistryEntryV1) -> bytes:
    raw = (
        files("fundamental_service").joinpath("resources", entry.filename).read_bytes()
    )
    if len(raw) > 500_000 or hashlib.sha256(raw).hexdigest() != entry.sha256:
        raise SnapshotError("FISCAL_REGISTRY_INVALID", "installed fiscal scope differs")
    return raw


def fiscal_statement_registry() -> FiscalStatementRegistryV1:
    raw = (
        files("fundamental_service")
        .joinpath("resources", "fiscal-statement-registry-v1.json")
        .read_bytes()
    )
    if len(raw) > 100_000:
        raise SnapshotError(
            "FISCAL_REGISTRY_INVALID", "fiscal registry exceeds its bound"
        )
    return FiscalStatementRegistryV1.model_validate_json(raw)


def fiscal_primary_scopes(
    registry: FiscalStatementRegistryV1,
) -> tuple[FiscalPrimaryScopeV1, ...]:
    return tuple(
        FiscalPrimaryScopeV1.model_validate_json(_resource(item))
        for item in registry.sources
    )


def fiscal_reviewed_coverage(
    registry: FiscalStatementRegistryV1,
) -> tuple[FiscalReviewedCoverageV1, ...]:
    return tuple(
        FiscalReviewedCoverageV1.model_validate_json(_resource(item))
        for item in registry.coverage
    )


def selected_fiscal_coverage(
    discovery: FiscalDiscoveryEvidenceV1,
) -> FiscalReviewedCoverageV1:
    if discovery.selection.issue_codes or discovery.is_retry_attempt:
        raise SnapshotError(
            "FISCAL_PROJECTION_INVALID",
            "fiscal discovery does not have a complete eligible period set",
        )
    ends = tuple(
        sorted(filing.report_period_end for filing in discovery.selection.selected)
    )
    matches = [
        item
        for item in fiscal_reviewed_coverage(fiscal_statement_registry())
        if item.issuer_id == discovery.request.cik
        and tuple(quarter.period.end for quarter in item.quarters) == ends
    ]
    if len(matches) != 1:
        raise SnapshotError(
            "FISCAL_PRIMARY_SCOPE_UNREVIEWED",
            "the selected fiscal period set has no reviewed source scope",
        )
    return matches[0]
