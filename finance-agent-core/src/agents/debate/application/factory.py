from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from src.agents.debate.application.orchestrator import (
    DebateNodeResult,
    DebateOrchestrator,
)
from src.agents.debate.interface.prompt_specs import (
    BEAR_AGENT_SYSTEM_PROMPT,
    BEAR_R1_ADVERSARIAL,
    BEAR_R2_ADVERSARIAL,
    BULL_AGENT_SYSTEM_PROMPT,
    BULL_R1_ADVERSARIAL,
    BULL_R2_ADVERSARIAL,
    MODERATOR_SYSTEM_PROMPT,
)


@dataclass(frozen=True)
class DebateWorkflowRunner:
    orchestrator: DebateOrchestrator

    async def run_debate_aggregator(
        self, state: Mapping[str, object]
    ) -> DebateNodeResult:
        return await self.orchestrator.run_debate_aggregator(state)

    async def run_fact_extractor(self, state: Mapping[str, object]) -> DebateNodeResult:
        return await self.orchestrator.run_fact_extractor(state)

    async def run_r1_bull(self, state: Mapping[str, object]) -> DebateNodeResult:
        return await self.orchestrator.run_bull_round(
            state,
            round_num=1,
            adversarial_rule=BULL_R1_ADVERSARIAL,
            system_prompt_template=BULL_AGENT_SYSTEM_PROMPT,
            node_name="r1_bull",
            success_goto="r1_moderator",
            success_progress={"r1_bull": "done", "r1_bear": "running"},
            error_progress={"r1_bull": "error", "r1_bear": "running"},
        )

    async def run_r1_bear(self, state: Mapping[str, object]) -> DebateNodeResult:
        return await self.orchestrator.run_bear_round(
            state,
            round_num=1,
            adversarial_rule=BEAR_R1_ADVERSARIAL,
            system_prompt_template=BEAR_AGENT_SYSTEM_PROMPT,
            node_name="r1_bear",
            success_goto="r1_moderator",
            success_progress={"r1_bear": "done"},
            error_progress={"r1_bear": "error"},
        )

    async def run_r1_moderator(self, state: Mapping[str, object]) -> DebateNodeResult:
        return await self.orchestrator.run_moderator_round(
            state,
            round_num=1,
            system_prompt_template=MODERATOR_SYSTEM_PROMPT,
            node_name="r1_moderator",
            success_goto="r2_bull",
            success_progress={"r1_moderator": "done", "r2_bull": "running"},
            error_progress={"r1_moderator": "error", "r2_bull": "running"},
            progress_winning_thesis="Round 1 complete, synthesizing arguments...",
            progress_summary="Cognitive Debate: Round 1 moderator critique complete",
        )

    async def run_r2_bull(self, state: Mapping[str, object]) -> DebateNodeResult:
        return await self.orchestrator.run_bull_round(
            state,
            round_num=2,
            adversarial_rule=BULL_R2_ADVERSARIAL,
            system_prompt_template=BULL_AGENT_SYSTEM_PROMPT,
            node_name="r2_bull",
            success_goto="r2_bear",
            success_progress={"r2_bull": "done", "r2_bear": "running"},
            error_progress={"r2_bull": "error", "r2_bear": "running"},
        )

    async def run_r2_bear(self, state: Mapping[str, object]) -> DebateNodeResult:
        return await self.orchestrator.run_bear_round(
            state,
            round_num=2,
            adversarial_rule=BEAR_R2_ADVERSARIAL,
            system_prompt_template=BEAR_AGENT_SYSTEM_PROMPT,
            node_name="r2_bear",
            success_goto="r2_moderator",
            success_progress={"r2_bear": "done", "r2_moderator": "running"},
            error_progress={"r2_bear": "error", "r2_moderator": "running"},
        )

    async def run_r2_moderator(self, state: Mapping[str, object]) -> DebateNodeResult:
        return await self.orchestrator.run_moderator_round(
            state,
            round_num=2,
            system_prompt_template=MODERATOR_SYSTEM_PROMPT,
            node_name="r2_moderator",
            success_goto="r3_bear",
            success_progress={"r2_moderator": "done", "r3_bear": "running"},
            error_progress={"r2_moderator": "error", "r3_bear": "running"},
            progress_winning_thesis="Round 2 cross-review complete, assessing vulnerabilities...",
            progress_summary="Cognitive Debate: Round 2 adversarial analysis complete",
        )

    async def run_r3_bear(self, state: Mapping[str, object]) -> DebateNodeResult:
        return await self.orchestrator.run_bear_round(
            state,
            round_num=3,
            adversarial_rule=BEAR_R2_ADVERSARIAL,
            system_prompt_template=BEAR_AGENT_SYSTEM_PROMPT,
            node_name="r3_bear",
            success_goto="r3_bull",
            success_progress={"r3_bear": "done", "r3_bull": "running"},
            error_progress={"r3_bear": "error", "r3_bull": "running"},
        )

    async def run_r3_bull(self, state: Mapping[str, object]) -> DebateNodeResult:
        return await self.orchestrator.run_bull_round(
            state,
            round_num=3,
            adversarial_rule=BULL_R2_ADVERSARIAL,
            system_prompt_template=BULL_AGENT_SYSTEM_PROMPT,
            node_name="r3_bull",
            success_goto="verdict",
            success_progress={"r3_bull": "done", "verdict": "running"},
            error_progress={"r3_bull": "error", "verdict": "running"},
        )

    async def run_verdict(self, state: Mapping[str, object]) -> DebateNodeResult:
        return await self.orchestrator.run_verdict(state)


def build_debate_workflow_runner(
    orchestrator: DebateOrchestrator,
) -> DebateWorkflowRunner:
    return DebateWorkflowRunner(orchestrator=orchestrator)
