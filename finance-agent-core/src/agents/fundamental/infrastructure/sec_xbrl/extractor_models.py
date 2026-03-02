from __future__ import annotations

import logging
from dataclasses import dataclass

from pydantic import BaseModel, Field

from src.shared.kernel.tools.logger import log_event


@dataclass
class SearchConfig:
    """搜尋配置對象：攜帶搜尋類型與選擇性的維度過濾器"""

    concept_regex: str
    type_name: str = "CONSOLIDATED"
    dimension_regex: str | None = None
    statement_types: list[str] | None = None
    period_type: str | None = None  # "instant" or "duration"
    unit_whitelist: list[str] | None = None
    unit_blacklist: list[str] | None = None
    respect_anchor_date: bool = True


class SearchType:
    """搜尋類型工廠：協助建立 SearchConfig"""

    @staticmethod
    def CONSOLIDATED(
        concept_regex: str,
        statement_types: list[str] | None = None,
        period_type: str | None = None,
        unit_whitelist: list[str] | None = None,
        unit_blacklist: list[str] | None = None,
        respect_anchor_date: bool = True,
    ) -> SearchConfig:
        return SearchConfig(
            concept_regex=concept_regex,
            type_name="CONSOLIDATED",
            statement_types=statement_types,
            period_type=period_type,
            unit_whitelist=unit_whitelist,
            unit_blacklist=unit_blacklist,
            respect_anchor_date=respect_anchor_date,
        )

    @staticmethod
    def DIMENSIONAL(
        concept_regex: str,
        dimension_regex: str,
        statement_types: list[str] | None = None,
        period_type: str | None = None,
        unit_whitelist: list[str] | None = None,
        unit_blacklist: list[str] | None = None,
        respect_anchor_date: bool = True,
    ) -> SearchConfig:
        return SearchConfig(
            concept_regex=concept_regex,
            type_name="DIMENSIONAL",
            dimension_regex=dimension_regex,
            statement_types=statement_types,
            period_type=period_type,
            unit_whitelist=unit_whitelist,
            unit_blacklist=unit_blacklist,
            respect_anchor_date=respect_anchor_date,
        )


class SECExtractResult(BaseModel):
    concept: str
    value: str | None
    label: str | None
    statement: str | None
    period_key: str
    dimensions: str | None
    dimension_detail: dict | None = Field(default_factory=dict)
    unit: str | None = None
    decimals: str | None = None
    scale: str | None = None


@dataclass
class Rejection:
    reason: str
    concept: str
    period_key: str
    statement_type: str | None
    unit: str | None
    value_preview: str | None


class SearchStats:
    def __init__(self) -> None:
        self.rejections: list[Rejection] = []

    def add(self, rejection: Rejection) -> None:
        self.rejections.append(rejection)

    def log(self, logger: logging.Logger) -> None:
        for rej in self.rejections:
            log_event(
                logger,
                event="fundamental_xbrl_search_rejection",
                message="xbrl row rejected by filters",
                level=logging.DEBUG,
                fields={
                    "reason": rej.reason,
                    "concept": rej.concept,
                    "period_key": rej.period_key,
                    "statement_type": rej.statement_type,
                    "unit": rej.unit,
                    "value_preview": rej.value_preview,
                },
            )
