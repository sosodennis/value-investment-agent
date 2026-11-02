from __future__ import annotations

from dataclasses import dataclass

from src.agents.debate.interface.contracts import DebateArtifactModel
from src.artifacts.public import (
    ARTIFACT_KIND_DEBATE_FACTS,
    ARTIFACT_KIND_DEBATE_FINAL_REPORT,
    TypedArtifactPort,
    build_typed_artifact_port,
)
from src.shared.artifacts.artifact_data_models import DebateFactsArtifactData
from src.shared.kernel.types import JSONObject


@dataclass
class DebateArtifactRepository:
    facts_port: TypedArtifactPort[DebateFactsArtifactData]
    final_report_port: TypedArtifactPort[DebateArtifactModel]

    async def save_facts_bundle(
        self,
        data: JSONObject,
        *,
        produced_by: str,
        key_prefix: str | None = None,
    ) -> str:
        return await self.facts_port.save(
            data,
            produced_by=produced_by,
            key_prefix=key_prefix,
        )

    async def load_facts_bundle(
        self, artifact_id: str
    ) -> DebateFactsArtifactData | None:
        return await self.facts_port.load(
            artifact_id,
            context=f"artifact {artifact_id} debate_facts",
        )

    async def save_final_report(
        self,
        data: JSONObject,
        *,
        produced_by: str,
        key_prefix: str | None = None,
    ) -> str:
        return await self.final_report_port.save(
            data,
            produced_by=produced_by,
            key_prefix=key_prefix,
        )


debate_artifact_repository = DebateArtifactRepository(
    facts_port=build_typed_artifact_port(
        kind=ARTIFACT_KIND_DEBATE_FACTS,
        model=DebateFactsArtifactData,
    ),
    final_report_port=build_typed_artifact_port(
        kind=ARTIFACT_KIND_DEBATE_FINAL_REPORT,
        model=DebateArtifactModel,
    ),
)
