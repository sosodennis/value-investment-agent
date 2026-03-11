from __future__ import annotations

from typing import Literal

from src.agents.fundamental.shared.contracts.traceable import (
    ComputedProvenance,
    ManualProvenance,
    TraceableField,
)

from .extension_token_normalizer import normalize_extension_type_token


def resolve_industry_type(sic_code: object) -> str:
    if not sic_code:
        return "General"
    try:
        sic = int(sic_code)
    except (ValueError, TypeError):
        return "General"

    if sic == 6798:
        return "Real Estate"
    if 6000 <= sic <= 6999:
        return "Financial Services"
    if 2000 <= sic <= 3999:
        return "Industrial"
    return "Industrial"


def resolve_extension_type(
    industry_type: object,
) -> Literal["Industrial", "FinancialServices", "RealEstate"]:
    extension_type = normalize_extension_type_token(
        industry_type,
        context="sec_xbrl.industry_type",
    )
    if extension_type is None:
        return "Industrial"
    return extension_type


def sum_fields(name: str, fields: list[TraceableField[float]]) -> TraceableField[float]:
    total = 0.0
    all_none = True
    inputs_map = {}
    field_names: list[str] = []

    for field in fields:
        inputs_map[field.name] = field
        field_names.append(field.name)
        if field.value is not None:
            total += field.value
            all_none = False

    if all_none:
        return TraceableField(
            name=name,
            value=None,
            provenance=ManualProvenance(
                description=f"All components missing for calculation: {', '.join(field_names)}"
            ),
        )

    return TraceableField(
        name=name,
        value=total,
        provenance=ComputedProvenance(
            op_code="SUM", expression=" + ".join(field_names), inputs=inputs_map
        ),
    )
