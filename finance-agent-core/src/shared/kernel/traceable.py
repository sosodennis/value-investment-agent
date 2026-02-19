from __future__ import annotations

import logging
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Generic, TypeVar

from pydantic import BaseModel

from src.shared.kernel.tools.logger import get_logger, log_event

T = TypeVar("T")
logger = get_logger(__name__)


class SourceType(str, Enum):
    XBRL = "XBRL"
    CALCULATION = "CALCULATION"
    MANUAL = "MANUAL"


class XBRLProvenance(BaseModel):
    type: SourceType = SourceType.XBRL
    concept: str
    period: str


class ComputedProvenance(BaseModel):
    type: SourceType = SourceType.CALCULATION
    op_code: str
    expression: str
    inputs: dict[str, TraceableField]


class ManualProvenance(BaseModel):
    type: SourceType = SourceType.MANUAL
    description: str
    author: str | None = "Analyst"
    modified_at: str = str(datetime.now())


class TraceableFieldBase(BaseModel):
    """
    Base class for TraceableField containing common logic and fields
    that do not depend on the Generic type T at runtime.
    """

    name: str
    provenance: XBRLProvenance | ComputedProvenance | ManualProvenance

    def explain(self, level: int = 0) -> None:
        indent = "  " * level
        val = getattr(self, "value", None)
        val_str = f"'{val}'" if isinstance(val, str) else str(val)

        p = self.provenance

        if isinstance(p, XBRLProvenance):
            log_event(
                logger,
                event="traceable_field_explained",
                message="traceable field explained",
                level=logging.INFO,
                fields={
                    "indent": indent,
                    "field_name": self.name,
                    "value": val_str,
                    "provenance_type": "XBRL",
                    "concept": p.concept,
                },
            )
        elif isinstance(p, ComputedProvenance):
            log_event(
                logger,
                event="traceable_field_explained",
                message="traceable field explained",
                level=logging.INFO,
                fields={
                    "indent": indent,
                    "field_name": self.name,
                    "value": val_str,
                    "provenance_type": "CALCULATION",
                    "expression": p.expression,
                },
            )
            for _, field in p.inputs.items():
                if isinstance(field, TraceableFieldBase):
                    field.explain(level + 1)
        elif isinstance(p, ManualProvenance):
            log_event(
                logger,
                event="traceable_field_explained",
                message="traceable field explained",
                level=logging.INFO,
                fields={
                    "indent": indent,
                    "field_name": self.name,
                    "value": val_str,
                    "provenance_type": "MANUAL",
                    "description": p.description,
                },
            )


if TYPE_CHECKING:

    class TraceableField(TraceableFieldBase, Generic[T]):
        value: T | None
else:

    class TraceableField(TraceableFieldBase):
        value: object | None

        @classmethod
        def __class_getitem__(cls, item: object):
            return cls


ComputedProvenance.model_rebuild()
TraceableField.model_rebuild()
