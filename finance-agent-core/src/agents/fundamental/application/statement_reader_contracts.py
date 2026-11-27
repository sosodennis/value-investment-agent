from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from src.artifacts.public import ArtifactReference
from src.shared.artifacts.statement_read_artifact import (
    StatementEditionV2,
    StatementFrequency,
)


class StatementReaderModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class StatementCatalogV2(StatementReaderModel):
    contract_version: Literal["workspace.statement-reader.v2"] = (
        "workspace.statement-reader.v2"
    )
    entries: tuple[StatementEditionV2, ...]


class StatementReadSelectionV2(StatementReaderModel):
    contract_version: Literal["workspace.statement-reader.v2"]
    edition_id: str = Field(min_length=1, max_length=128)
    frequency: StatementFrequency


class StatementExistingThreadIntentV2(StatementReadSelectionV2):
    kind: Literal["existing_thread"]
    thread_id: str = Field(min_length=1, max_length=128)


class StatementNewThreadIntentV2(StatementReadSelectionV2):
    kind: Literal["new_thread"]
    creation_id: UUID


class StatementSavedArtifactIntentV2(StatementReaderModel):
    contract_version: Literal["workspace.statement-reader.v2"]
    kind: Literal["saved_artifact"]
    thread_id: str = Field(min_length=1, max_length=128)
    artifact_id: str = Field(min_length=1, max_length=128)
    frequency: StatementFrequency


StatementReadIntentV2 = Annotated[
    StatementExistingThreadIntentV2
    | StatementNewThreadIntentV2
    | StatementSavedArtifactIntentV2,
    Field(discriminator="kind"),
]


class StatementArtifactResponseV2(StatementReaderModel):
    contract_version: Literal["workspace.statement-reader.v2"] = (
        "workspace.statement-reader.v2"
    )
    edition_id: str
    frequency: StatementFrequency
    thread_id: str
    reference: ArtifactReference
