from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, Protocol, TypeVar, cast

from pydantic import BaseModel

from src.artifacts.application.ports import ArtifactStoragePort
from src.artifacts.contracts.registry import (
    artifact_contract_dump_exclude_none,
    parse_artifact_data_model_as,
)
from src.shared.kernel.types import JSONObject

_ModelT = TypeVar("_ModelT", bound=BaseModel)


class TypedArtifactPort(Protocol[_ModelT]):
    async def save(
        self,
        data: JSONObject,
        *,
        produced_by: str,
        key_prefix: str | None = None,
    ) -> str: ...

    async def load(
        self, artifact_id: object, *, context: str | None = None
    ) -> _ModelT | None: ...

    async def load_json(
        self, artifact_id: object, *, context: str | None = None
    ) -> JSONObject | None: ...


@dataclass
class TypedArtifactStore(Generic[_ModelT]):
    storage: ArtifactStoragePort
    kind: str
    model: type[_ModelT]

    async def save(
        self,
        data: JSONObject,
        *,
        produced_by: str,
        key_prefix: str | None = None,
    ) -> str:
        return await self.storage.save_artifact(
            data=data,
            artifact_type=self.kind,
            produced_by=produced_by,
            key_prefix=key_prefix,
        )

    async def load(
        self, artifact_id: object, *, context: str | None = None
    ) -> _ModelT | None:
        if not isinstance(artifact_id, str):
            return None
        raw = await self.storage.get_artifact_data(
            artifact_id,
            expected_kind=self.kind,
        )
        if raw is None:
            return None
        return parse_artifact_data_model_as(
            self.kind,
            raw,
            model=self.model,
            context=context or f"artifact {artifact_id} {self.kind}",
        )

    async def load_json(
        self, artifact_id: object, *, context: str | None = None
    ) -> JSONObject | None:
        parsed = await self.load(artifact_id, context=context)
        if parsed is None:
            return None
        dumped = parsed.model_dump(
            mode="json",
            exclude_none=artifact_contract_dump_exclude_none(self.kind),
        )
        if not isinstance(dumped, dict):
            raise TypeError(
                (context or f"artifact {artifact_id} {self.kind}")
                + " must serialize to object"
            )
        return cast(JSONObject, dumped)
