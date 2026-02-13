from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, TypeVar

from pydantic import BaseModel

from src.common.types import JSONObject
from src.interface.artifact_contract_registry import parse_artifact_data_model_as
from src.services.artifact_manager import ArtifactManager

_ModelT = TypeVar("_ModelT", bound=BaseModel)


@dataclass
class TypedArtifactPort(Generic[_ModelT]):
    manager: ArtifactManager
    kind: str
    model: type[_ModelT]

    async def save(
        self,
        data: JSONObject,
        *,
        produced_by: str,
        key_prefix: str | None = None,
    ) -> str:
        return await self.manager.save_artifact(
            data=data,
            artifact_type=self.kind,
            produced_by=produced_by,
            key_prefix=key_prefix,
        )

    async def load(
        self, artifact_id: str, *, context: str | None = None
    ) -> _ModelT | None:
        raw = await self.manager.get_artifact_data(artifact_id, expected_kind=self.kind)
        if raw is None:
            return None
        return parse_artifact_data_model_as(
            self.kind,
            raw,
            model=self.model,
            context=context or f"artifact {artifact_id} {self.kind}",
        )
