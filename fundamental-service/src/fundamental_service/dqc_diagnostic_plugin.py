"""Bind official lease-reconciliation diagnostics to their referenced facts."""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import datetime, time, timedelta
from decimal import Decimal
from typing import Any, Protocol

from fundamental_service.arelle_parser import ArelleParserError

DIAGNOSTIC_POLICY = "dqc-0090-bound-diagnostics-v2"
_SUM_CONCEPTS = {
    "DQC.US.0090.9374": "LesseeOperatingLeaseLiabilityPaymentsDue",
    "DQC.US.0090.9375": "FinanceLeaseLiabilityPaymentsDue",
}
_RENDERED_CONTEXT = re.compile(
    r"\nPeriod :(?P<period>[0-9]{4}-[0-9]{2}-[0-9]{2})"
    r"(?:\nDimensions :(?P<dimensions>[ \t]*))?\nUnit : (?P<currency>[A-Z]{3})"
    r"\nDecimals: (?P<decimals>inf|-?[0-9]+)"
    r"\n\nRule Element Id:(?P<rule>9374|9375)\nRule version: 31\.0\.3\Z"
)


class DqcModel(Protocol):
    log: Callable[..., None]


def _is_sum_fact(fact: object, concept: str) -> bool:
    qname = getattr(fact, "qname", None)
    return (
        getattr(qname, "localName", None) == concept
        and re.fullmatch(
            r"http://fasb\.org/us-gaap/20[0-9]{2}(?:-[0-9]{2}-[0-9]{2})?",
            getattr(qname, "namespaceURI", ""),
        )
        is not None
        and bool(getattr(fact, "isNumeric", False))
        and not getattr(fact, "isNil", True)
    )


def _has_rendered_value(fact: object, message: str) -> bool:
    value = getattr(fact, "xValue", None)
    numeric = (
        isinstance(value, int)
        and not isinstance(value, bool)
        or isinstance(value, Decimal)
        and value.is_finite()
    )
    return numeric and message.startswith(
        f"The element {getattr(fact, 'qname', None)} with a value of {value:,} "
    )


def _matches_rendered_context(fact: object, signature: re.Match[str]) -> bool:
    context = getattr(fact, "context", None)
    instant = getattr(context, "instantDatetime", None)
    measures = getattr(getattr(fact, "unit", None), "measures", None)
    if measures is None:
        return False
    return (
        getattr(context, "isInstantPeriod", False)
        and isinstance(instant, datetime)
        and instant.tzinfo is None
        and instant.time() == time()
        and instant > datetime.min
        # Arelle represents an XBRL instant as the following day's midnight.
        and (instant - timedelta(days=1)).date().isoformat() == signature["period"]
        and getattr(context, "qnameDims", None) == {}
        and getattr(context, "segNonDimValues", None) == []
        and getattr(context, "scenNonDimValues", None) == []
        and len(measures) == 2
        and len(measures[0]) == 1
        and not measures[1]
        and getattr(measures[0][0], "namespaceURI", None)
        == "http://www.xbrl.org/2003/iso4217"
        and getattr(measures[0][0], "localName", None) == signature["currency"]
        and _matches_rendered_decimals(fact, signature["decimals"])
    )


def _matches_rendered_decimals(fact: object, rendered: str) -> bool:
    decimals = getattr(fact, "decimals", None)
    if decimals == "INF":
        return rendered == "inf"
    if not isinstance(decimals, str) or re.fullmatch(r"[+-]?[0-9]+", decimals) is None:
        return False
    return Decimal(decimals) == Decimal(rendered)


def _original_model_matches(
    message_code: str, message: str, model_objects: list[object], concept: str
) -> list[object]:
    signature = _RENDERED_CONTEXT.search(message)
    if signature is None or not message_code.endswith("." + signature["rule"]):
        return []
    if (signature["dimensions"] is not None) != (signature["rule"] == "9374"):
        return []
    models = {
        id(model): model
        for obj in model_objects
        if (model := getattr(obj, "modelXbrl", None)) is not None
    }
    if len(models) != 1:
        return []
    model = next(iter(models.values()))
    return [
        fact
        for fact in getattr(model, "facts", ())
        if getattr(fact, "modelXbrl", None) is model
        and _is_sum_fact(fact, concept)
        and _has_rendered_value(fact, message)
        and _matches_rendered_context(fact, signature)
    ]


def preserve_rule_severity(
    controller: object,
    options: object,
    model: DqcModel,
    *args: object,
    **kwargs: object,
) -> None:
    original_log = model.log

    def observed_log(level: str, codes: object, msg: str, **parameters: object) -> None:
        if isinstance(codes, str) and codes.startswith("DQC."):
            # EFM relevels DQC errors before the logging-parameter hooks run.
            parameters["fundamental_rule_severity"] = level.lower()
        original_log(level, codes, msg, **parameters)

    model.log = observed_log


def message_parameters(
    message_code: str,
    message: str,
    model_objects: list[Any],
    parameters: dict[str, Any],
) -> str:
    concept = _SUM_CONCEPTS.get(message_code)
    if concept is None:
        return message
    matches = [fact for fact in model_objects if _is_sum_fact(fact, concept)]
    if not matches and "name" not in parameters:
        matches = _original_model_matches(message_code, message, model_objects, concept)
    if (
        len(matches) != 1
        or not getattr(matches[0], "contextID", None)
        or not getattr(matches[0], "unitID", None)
    ):
        raise ArelleParserError(
            "DQC_DIAGNOSTIC_BINDING_UNAVAILABLE",
            "lease reconciliation diagnostic has no unique referenced sum fact",
        )
    fact = matches[0]
    if "name" in parameters:
        name_matches = parameters["name"] == concept
    else:
        name_matches = _has_rendered_value(fact, message)
    if not name_matches:
        raise ArelleParserError(
            "DQC_DIAGNOSTIC_BINDING_UNAVAILABLE",
            "lease reconciliation message differs from its referenced sum fact",
        )
    parameters["contextID"] = fact.contextID
    parameters["unitID"] = fact.unitID
    return message


__pluginInfo__ = {
    "name": "Fundamental bound DQC lease diagnostics",
    "version": "2.0.0",
    "CntlrCmdLine.Xbrl.Loaded": preserve_rule_severity,
    "Logging.Message.Parameters": message_parameters,
}
