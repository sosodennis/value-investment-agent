from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

from src.agents.debate.application.dto import DebateSourceData
from src.interface.artifacts.artifact_data_models import DebateFactsArtifactData
from src.shared.kernel.types import JSONObject
from src.shared.kernel.workflow_contracts import WorkflowFanoutNodeResult


class SycophancyDetectorPort(Protocol):
    def check_consensus(
        self, bull_thesis: str, bear_thesis: str, threshold: float = 0.8
    ) -> tuple[float, bool]: ...


class DebateSourceReaderPort(Protocol):
    async def load_debate_source_data(
        self,
        *,
        financial_reports_artifact_id: str | None,
        news_artifact_id: str | None,
        technical_artifact_id: str | None,
    ) -> DebateSourceData: ...


class DebateArtifactRepositoryPort(Protocol):
    async def save_facts_bundle(
        self,
        data: JSONObject,
        *,
        produced_by: str,
        key_prefix: str | None = None,
    ) -> str: ...


class DebateWorkflowPort(Protocol):
    async def run_debate_aggregator(
        self, state: Mapping[str, object]
    ) -> WorkflowFanoutNodeResult: ...

    async def run_fact_extractor(
        self, state: Mapping[str, object]
    ) -> WorkflowFanoutNodeResult: ...

    async def run_r1_bull(
        self, state: Mapping[str, object]
    ) -> WorkflowFanoutNodeResult: ...

    async def run_r1_bear(
        self, state: Mapping[str, object]
    ) -> WorkflowFanoutNodeResult: ...

    async def run_r1_moderator(
        self, state: Mapping[str, object]
    ) -> WorkflowFanoutNodeResult: ...

    async def run_r2_bull(
        self, state: Mapping[str, object]
    ) -> WorkflowFanoutNodeResult: ...

    async def run_r2_bear(
        self, state: Mapping[str, object]
    ) -> WorkflowFanoutNodeResult: ...

    async def run_r2_moderator(
        self, state: Mapping[str, object]
    ) -> WorkflowFanoutNodeResult: ...

    async def run_r3_bull(
        self, state: Mapping[str, object]
    ) -> WorkflowFanoutNodeResult: ...

    async def run_r3_bear(
        self, state: Mapping[str, object]
    ) -> WorkflowFanoutNodeResult: ...

    async def run_verdict(
        self, state: Mapping[str, object]
    ) -> WorkflowFanoutNodeResult: ...

    async def load_facts_bundle(
        self,
        artifact_id: str,
    ) -> DebateFactsArtifactData | None: ...

    async def save_final_report(
        self,
        data: JSONObject,
        *,
        produced_by: str,
        key_prefix: str | None = None,
    ) -> str: ...
