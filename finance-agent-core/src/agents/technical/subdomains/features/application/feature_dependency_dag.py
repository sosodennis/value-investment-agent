from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

import pandas as pd

from src.agents.technical.domain.shared import IndicatorSnapshot


@dataclass
class FeatureExecutionContext:
    price_series: pd.Series
    volume_series: pd.Series
    high_series: pd.Series
    low_series: pd.Series
    latest_price: float | None
    outputs: dict[str, IndicatorSnapshot] = field(default_factory=dict)
    output_stages: dict[str, str] = field(default_factory=dict)
    cache: dict[str, object] = field(default_factory=dict)
    degraded: list[str] = field(default_factory=list)

    def add_output(self, name: str, snapshot: IndicatorSnapshot, stage: str) -> None:
        self.outputs[name] = snapshot
        self.output_stages[name] = stage


@dataclass(frozen=True)
class FeatureTask:
    name: str
    stage: str
    run: Callable[[FeatureExecutionContext], None]
    dependencies: tuple[str, ...] = ()


@dataclass(frozen=True)
class FeatureDagIssue:
    code: str
    message: str
    task: str | None = None
    dependency: str | None = None


@dataclass(frozen=True)
class FeatureDagPlan:
    ordered_tasks: list[FeatureTask]
    issues: list[FeatureDagIssue]


def build_feature_execution_plan(
    tasks: list[FeatureTask],
    *,
    stage_order: tuple[str, ...],
) -> FeatureDagPlan:
    task_map: dict[str, FeatureTask] = {}
    issues: list[FeatureDagIssue] = []
    for task in tasks:
        if task.name in task_map:
            issues.append(
                FeatureDagIssue(
                    code="FEATURE_DAG_DUPLICATE_TASK",
                    message=f"duplicate feature task: {task.name}",
                    task=task.name,
                )
            )
        task_map[task.name] = task

    stages: list[str] = list(stage_order)
    for task in tasks:
        if task.stage not in stages:
            stages.append(task.stage)
    stage_index = {stage: idx for idx, stage in enumerate(stages)}

    invalid_tasks: set[str] = set()
    for task in tasks:
        for dep in task.dependencies:
            if dep not in task_map:
                issues.append(
                    FeatureDagIssue(
                        code="FEATURE_DAG_MISSING_DEP",
                        message=f"missing dependency {dep} for task {task.name}",
                        task=task.name,
                        dependency=dep,
                    )
                )
                invalid_tasks.add(task.name)
                continue
            dep_stage = task_map[dep].stage
            if stage_index.get(dep_stage, 0) > stage_index.get(task.stage, 0):
                issues.append(
                    FeatureDagIssue(
                        code="FEATURE_DAG_INVALID_STAGE_ORDER",
                        message=(
                            f"dependency {dep} (stage {dep_stage}) occurs after "
                            f"task {task.name} (stage {task.stage})"
                        ),
                        task=task.name,
                        dependency=dep,
                    )
                )
                invalid_tasks.add(task.name)

    filtered_tasks = [task for task in tasks if task.name not in invalid_tasks]
    ordered: list[FeatureTask] = []
    if not filtered_tasks:
        return FeatureDagPlan(ordered_tasks=ordered, issues=issues)

    for stage in stages:
        stage_tasks = [task for task in filtered_tasks if task.stage == stage]
        if not stage_tasks:
            continue
        stage_plan, stage_issues = _toposort_stage(stage_tasks)
        if stage_issues:
            issues.extend(stage_issues)
            break
        ordered.extend(stage_plan)

    return FeatureDagPlan(ordered_tasks=ordered, issues=issues)


def _toposort_stage(
    tasks: list[FeatureTask],
) -> tuple[list[FeatureTask], list[FeatureDagIssue]]:
    task_map = {task.name: task for task in tasks}
    indegree: dict[str, int] = {task.name: 0 for task in tasks}
    adjacency: dict[str, list[str]] = {task.name: [] for task in tasks}

    for task in tasks:
        for dep in task.dependencies:
            if dep not in task_map:
                continue
            adjacency[dep].append(task.name)
            indegree[task.name] += 1

    ready = sorted([name for name, deg in indegree.items() if deg == 0])
    ordered: list[FeatureTask] = []

    while ready:
        name = ready.pop(0)
        ordered.append(task_map[name])
        for downstream in sorted(adjacency[name]):
            indegree[downstream] -= 1
            if indegree[downstream] == 0:
                ready.append(downstream)

    if len(ordered) != len(tasks):
        blocked = [name for name, deg in indegree.items() if deg > 0]
        return (
            ordered,
            [
                FeatureDagIssue(
                    code="FEATURE_DAG_CYCLE",
                    message=f"cycle detected among tasks: {', '.join(sorted(blocked))}",
                )
            ],
        )

    return ordered, []
