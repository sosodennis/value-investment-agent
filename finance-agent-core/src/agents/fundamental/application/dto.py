from __future__ import annotations

from dataclasses import dataclass

from src.common.types import JSONObject


@dataclass(frozen=True)
class FinancialHealthResult:
    reports: list[JSONObject]
    artifact_id: str | None


@dataclass(frozen=True)
class ModelSelectionResultDTO:
    model_type: str
    selected_model: str
    reasoning: str
    artifact_id: str | None
    selection_details: JSONObject
