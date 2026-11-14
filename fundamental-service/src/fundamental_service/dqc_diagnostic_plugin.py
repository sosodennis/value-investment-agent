"""Bind official lease-reconciliation diagnostics to their referenced facts."""

from __future__ import annotations

import re
from collections.abc import Callable
from decimal import Decimal
from typing import Any, Protocol

from fundamental_service.arelle_parser import ArelleParserError

DIAGNOSTIC_POLICY = "dqc-0090-bound-diagnostics-v1"
_SUM_CONCEPTS = {
    "DQC.US.0090.9374": "LesseeOperatingLeaseLiabilityPaymentsDue",
    "DQC.US.0090.9375": "FinanceLeaseLiabilityPaymentsDue",
}


class DqcModel(Protocol):
    log: Callable[..., None]


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
    matches = [
        fact
        for fact in model_objects
        if getattr(getattr(fact, "qname", None), "localName", None) == concept
        and re.fullmatch(
            r"http://fasb\.org/us-gaap/20[0-9]{2}(?:-[0-9]{2}-[0-9]{2})?",
            getattr(fact.qname, "namespaceURI", ""),
        )
        and getattr(fact, "isNumeric", False)
        and not getattr(fact, "isNil", True)
    ]
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
        value = getattr(fact, "xValue", None)
        numeric = (
            isinstance(value, int)
            and not isinstance(value, bool)
            or isinstance(value, Decimal)
            and value.is_finite()
        )
        name_matches = numeric and message.startswith(
            f"The element {fact.qname} with a value of {value:,} "
        )
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
    "version": "1.0.0",
    "CntlrCmdLine.Xbrl.Loaded": preserve_rule_severity,
    "Logging.Message.Parameters": message_parameters,
}
