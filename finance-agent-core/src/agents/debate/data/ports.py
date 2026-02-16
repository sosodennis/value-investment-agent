from __future__ import annotations

from dataclasses import dataclass

from src.agents.debate.interface.contracts import DebateArtifactModel
from src.interface.artifacts.artifact_data_models import DebateFactsArtifactData
from src.services.artifact_manager import artifact_manager
from src.shared.cross_agent.data.typed_artifact_port import TypedArtifactPort
from src.shared.kernel.contracts import (
    ARTIFACT_KIND_DEBATE_FACTS,
    ARTIFACT_KIND_DEBATE_FINAL_REPORT,
)
from src.shared.kernel.types import JSONObject


@dataclass
class DebateArtifactPort:
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
        self, artifact_id: object
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


debate_artifact_port = DebateArtifactPort(
    facts_port=TypedArtifactPort(
        manager=artifact_manager,
        kind=ARTIFACT_KIND_DEBATE_FACTS,
        model=DebateFactsArtifactData,
    ),
    final_report_port=TypedArtifactPort(
        manager=artifact_manager,
        kind=ARTIFACT_KIND_DEBATE_FINAL_REPORT,
        model=DebateArtifactModel,
    ),
)
