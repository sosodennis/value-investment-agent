"""Bind official lease-reconciliation diagnostics to their referenced facts."""

from __future__ import annotations

import re
from typing import Any

from fundamental_service.arelle_parser import ArelleParserError

DIAGNOSTIC_POLICY = "dqc-0090-bound-diagnostics-v1"
_SUM_CONCEPTS = {
    "DQC.US.0090.9374": "LesseeOperatingLeaseLiabilityPaymentsDue",
    "DQC.US.0090.9375": "FinanceLeaseLiabilityPaymentsDue",
}


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
        parameters.get("name") != concept
        or len(matches) != 1
        or not getattr(matches[0], "contextID", None)
        or not getattr(matches[0], "unitID", None)
    ):
        raise ArelleParserError(
            "DQC_DIAGNOSTIC_BINDING_UNAVAILABLE",
            "lease reconciliation diagnostic has no unique referenced sum fact",
        )
    parameters["contextID"] = matches[0].contextID
    parameters["unitID"] = matches[0].unitID
    return message


__pluginInfo__ = {
    "name": "Fundamental bound DQC lease diagnostics",
    "version": "1.0.0",
    "Logging.Message.Parameters": message_parameters,
}
