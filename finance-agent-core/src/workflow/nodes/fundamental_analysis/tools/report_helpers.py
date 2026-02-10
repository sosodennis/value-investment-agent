from __future__ import annotations

import textwrap

from src.common.traceable import ComputedProvenance, ManualProvenance, XBRLProvenance


def _wrap_text(text: str, width: int = 40) -> str:
    return "\n".join(textwrap.wrap(text, width=width))


def _value_of(value: object | None) -> object | None:
    if value is None:
        return None
    if hasattr(value, "value"):
        return value.value
    return value


def _src(value: object | None) -> str:
    if value is None or not hasattr(value, "provenance"):
        return ""
    provenance = value.provenance
    if isinstance(provenance, XBRLProvenance):
        return f" | [XBRL: {provenance.concept}]"
    if isinstance(provenance, ComputedProvenance):
        return f" | [Calc: {provenance.expression}]"
    if isinstance(provenance, ManualProvenance):
        return f" | [Manual: {provenance.description}]"
    return ""


def fmt_currency(value: object | None) -> str:
    if value is None:
        return "None"
    inner = _value_of(value)
    if inner is None:
        return "None"
    try:
        fval = float(inner)
        return _wrap_text(f"${fval:,.0f}{_src(value)}")
    except (ValueError, TypeError):
        return _wrap_text(f"{inner}{_src(value)}")


def fmt_num(value: object | None) -> str:
    if value is None:
        return "None"
    inner = _value_of(value)
    if inner is None:
        return "None"
    try:
        fval = float(inner)
        return _wrap_text(f"{fval:,.0f}{_src(value)}")
    except (ValueError, TypeError):
        return _wrap_text(f"{inner}{_src(value)}")


def fmt_str(value: object | None) -> str:
    if value is None:
        return "None"
    inner = _value_of(value)
    if inner is None:
        return "None"
    return _wrap_text(f"{inner}{_src(value)}")


def pct(value: object | None) -> str:
    if value is None:
        return "None"
    inner = _value_of(value)
    if inner is None:
        return "None"
    try:
        fval = float(inner)
        return _wrap_text(f"{fval:.2%}{_src(value)}")
    except (ValueError, TypeError):
        return _wrap_text(f"{inner}{_src(value)}")


def ratio(numerator: object | None, denominator: object | None) -> str:
    num_val = _value_of(numerator)
    den_val = _value_of(denominator)
    if num_val is None or den_val is None:
        return "None"
    try:
        n = float(num_val)
        d = float(den_val)
        if d == 0:
            return "None (Div0)"
        return _wrap_text(f"{n / d:.2f}")
    except (ValueError, TypeError):
        return "None"
