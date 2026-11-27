from __future__ import annotations

from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, model_validator

from .data_releases import ArtifactRefV1, ReleaseModel
from .fiscal_release_contracts import Digest, FiscalPublishV2
from .fiscal_statement_contracts import (
    FiscalCashContinuityV1,
    FiscalObservationV1,
    FiscalPeriodTargetV1,
    FiscalReconciliationV1,
    FiscalTtmWindowV1,
    FiscalValueNodeV1,
)
from .fiscal_statement_policy import FiscalRowPolicyV1
from .serialization import sha256_digest
from .statement_contracts import StatementScopeV1


class FiscalReadRequestV2(ReleaseModel):
    contract_version: Literal["fundamental.fiscal-statements.v2"] = (
        "fundamental.fiscal-statements.v2"
    )
    manifest_digest: Digest
    scope: StatementScopeV1
    cutoff_at: AwareDatetime
    frequency: Literal["quarter", "ttm"]


class FiscalQuarterColumnsV1(ReleaseModel):
    frequency: Literal["quarter"] = "quarter"
    periods: tuple[FiscalPeriodTargetV1, ...] = Field(min_length=1)


class FiscalTtmColumnsV1(ReleaseModel):
    frequency: Literal["ttm"] = "ttm"
    windows: tuple[FiscalTtmWindowV1, ...] = Field(min_length=1)


FiscalColumnsV1 = Annotated[
    FiscalQuarterColumnsV1 | FiscalTtmColumnsV1, Field(discriminator="frequency")
]


class FiscalReadBindingV2(ReleaseModel):
    manifest_digest: Digest
    approved: FiscalPublishV2
    projection_digest: Digest
    scope: StatementScopeV1
    cutoff_at: AwareDatetime
    columns: FiscalColumnsV1
    selected_period_set_digest: Digest

    @model_validator(mode="after")
    def exact_period_set(self) -> FiscalReadBindingV2:
        if self.selected_period_set_digest != sha256_digest(self.columns):
            raise ValueError("fiscal read selected period set differs")
        return self


class FiscalReportedCellV1(ReleaseModel):
    kind: Literal["reported"] = "reported"
    node_id: str
    decimal: str = Field(pattern=r"^-?(0|[1-9][0-9]*)(\.[0-9]+)?$")
    source_observation_ids: tuple[str, ...] = Field(min_length=1)


class FiscalDerivedCellV1(ReleaseModel):
    kind: Literal["derived"] = "derived"
    node_id: str
    decimal: str = Field(pattern=r"^-?(0|[1-9][0-9]*)(\.[0-9]+)?$")


class FiscalMissingCellV1(ReleaseModel):
    kind: Literal["unavailable", "conflict"]
    node_id: str
    reason_code: str


FiscalCellV1 = Annotated[
    FiscalReportedCellV1 | FiscalDerivedCellV1 | FiscalMissingCellV1,
    Field(discriminator="kind"),
]


class FiscalDisplayRowV1(ReleaseModel):
    row: FiscalRowPolicyV1
    cells: tuple[FiscalCellV1, ...] = Field(min_length=1)


class FiscalSourceDocumentV1(ReleaseModel):
    issuer_id: str = Field(pattern=r"^[0-9]{10}$")
    accession_number: str = Field(pattern=r"^[0-9]{10}-[0-9]{2}-[0-9]{6}$")
    primary_document_url: str = Field(min_length=1)
    primary_document_sha256: Digest
    archive_member_sha256: Digest


class FiscalSourceInspectionV1(ReleaseModel):
    source_validation_ref: ArtifactRefV1
    source_document: FiscalSourceDocumentV1
    validation_kind: Literal["complete_matched", "complete_refused"]
    source_binding_digest: Digest
    raw_report_digest: Digest
    parser_action_refs: tuple[ArtifactRefV1, ...]
    witness_ref: ArtifactRefV1 | None
    classification_refs: tuple[ArtifactRefV1, ...]
    mapping_ref: ArtifactRefV1
    mapping_approval_ref: ArtifactRefV1


class FiscalDisplayGraphV1(ReleaseModel):
    nodes: tuple[FiscalValueNodeV1, ...]
    observations: tuple[FiscalObservationV1, ...]
    source_uses: tuple[FiscalSourceInspectionV1, ...]
    reconciliations: tuple[FiscalReconciliationV1, ...]
    cash_continuities: tuple[FiscalCashContinuityV1, ...]


class FiscalReadResultV2(ReleaseModel):
    contract_version: Literal["fundamental.fiscal-statements.v2"] = (
        "fundamental.fiscal-statements.v2"
    )
    binding: FiscalReadBindingV2
    rows: tuple[FiscalDisplayRowV1, ...]
    evidence: FiscalDisplayGraphV1
    supported_history_threshold: None = None
    valuation_eligibility: Literal["not_evaluated"] = "not_evaluated"

    @model_validator(mode="after")
    def exact_graph_and_cells(self) -> FiscalReadResultV2:
        nodes = {node.node_id: node for node in self.evidence.nodes}
        observations = {
            item.observation_id: item for item in self.evidence.observations
        }
        if len(nodes) != len(self.evidence.nodes) or len(observations) != len(
            self.evidence.observations
        ):
            raise ValueError("fiscal transport repeats a graph identity")
        sources = {
            item.source_validation_ref.artifact_id: item
            for item in self.evidence.source_uses
        }
        if len(sources) != len(self.evidence.source_uses) or any(
            item.source_document.issuer_id != self.binding.scope.issuer_id
            for item in sources.values()
        ):
            raise ValueError("fiscal transport source identity differs")
        for observation in observations.values():
            source = sources.get(observation.source_artifact_id)
            if source is None or (
                observation.source_binding_digest != source.source_binding_digest
                or observation.issuer_id != source.source_document.issuer_id
                or observation.basis.issuer_id != source.source_document.issuer_id
                or observation.accession_number
                != source.source_document.accession_number
                or observation.source_locator.primary_document_sha256
                != source.source_document.archive_member_sha256
            ):
                raise ValueError("fiscal transport observation source differs")
        for node in nodes.values():
            if (
                any(
                    edge.input_id not in nodes and edge.input_id not in observations
                    for edge in (*node.input_edges, *node.verification_edges)
                )
                or any(identity not in nodes for identity in node.verification_node_ids)
                or any(
                    identity not in observations
                    for identity in (
                        *node.source_observation_ids,
                        *node.verification_observation_ids,
                    )
                )
            ):
                raise ValueError("fiscal transport graph has an unresolved dependency")
        columns = self.binding.columns
        count = (
            len(columns.periods)
            if isinstance(columns, FiscalQuarterColumnsV1)
            else len(columns.windows)
        )
        if len({row.row.row_id for row in self.rows}) != len(self.rows):
            raise ValueError("fiscal transport repeats a row")
        for row in self.rows:
            if len(row.cells) != count:
                raise ValueError(
                    "fiscal transport row differs from its selected columns"
                )
            for cell in row.cells:
                root = nodes.get(cell.node_id)
                if (
                    root is None
                    or root.row_id != row.row.row_id
                    or root.frequency != columns.frequency
                    or root.availability != cell.kind
                ):
                    raise ValueError(
                        "fiscal transport cell differs from its graph root"
                    )
                if isinstance(cell, (FiscalReportedCellV1, FiscalDerivedCellV1)) and (
                    root.value is None or cell.decimal != format(root.value, "f")
                ):
                    raise ValueError(
                        "fiscal transport decimal differs from its source node"
                    )
                if (
                    isinstance(cell, FiscalReportedCellV1)
                    and cell.source_observation_ids != root.source_observation_ids
                ):
                    raise ValueError("fiscal reported cell source differs")
                if (
                    isinstance(cell, FiscalMissingCellV1)
                    and cell.reason_code != root.reason_code
                ):
                    raise ValueError("fiscal missing cell reason differs")
        if any(
            identity not in nodes
            for item in self.evidence.reconciliations
            for identity in item.input_node_ids
        ) or any(
            identity not in nodes
            for item in self.evidence.cash_continuities
            for identity in item.input_node_ids
        ):
            raise ValueError("fiscal transport reconciliation has an unresolved node")
        return self
