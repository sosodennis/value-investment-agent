from decimal import Decimal
from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from fundamental_service.arelle_parser import ArelleParserError
from fundamental_service.arelle_parser import _finding_from_log
from fundamental_service.dqc_diagnostic_plugin import (
    message_parameters,
    preserve_rule_severity,
)


@dataclass
class _QName:
    localName: str
    namespaceURI: str

    def __str__(self):
        return f"us-gaap:{self.localName}"


def _fact(
    name, context="actual-2024", *, namespace="http://fasb.org/us-gaap/2024", unit="USD"
):
    return SimpleNamespace(
        qname=_QName(localName=name, namespaceURI=namespace),
        contextID=context,
        unitID=unit,
        xValue=Decimal("545906"),
        isNumeric=True,
        isNil=False,
    )


@pytest.mark.parametrize(
    "rule,name",
    [
        ("9374", "LesseeOperatingLeaseLiabilityPaymentsDue"),
        ("9375", "FinanceLeaseLiabilityPaymentsDue"),
    ],
)
@pytest.mark.parametrize("stale_context", ["unrelated-2022", "unrelated-2023"])
def test_warning_renders_actual_bound_fact_context_and_unit(rule, name, stale_context):
    message = "Context: %(contextID)s Unit: %(unitID)s Sum: %(sumValue)s Difference: %(differenceValue)s"
    parameters = {
        "name": name,
        "contextID": stale_context,
        "unitID": "unrelated-unit",
        "sumValue": "545906",
        "addendValue": "518706",
        "differenceValue": "27200",
    }
    original = dict(parameters)
    rendered = (
        message_parameters(f"DQC.US.0090.{rule}", message, [_fact(name)], parameters)
        % parameters
    )
    assert rendered == "Context: actual-2024 Unit: USD Sum: 545906 Difference: 27200"
    assert {
        k: v for k, v in parameters.items() if k not in {"contextID", "unitID"}
    } == {k: v for k, v in original.items() if k not in {"contextID", "unitID"}}


@pytest.mark.parametrize(
    "facts,parameters",
    [
        ([], {"name": "LesseeOperatingLeaseLiabilityPaymentsDue"}),
        ([_fact("Unrelated")], {"name": "LesseeOperatingLeaseLiabilityPaymentsDue"}),
        (
            [
                _fact(
                    "LesseeOperatingLeaseLiabilityPaymentsDue",
                    namespace="http://issuer.example/2024",
                )
            ],
            {"name": "LesseeOperatingLeaseLiabilityPaymentsDue"},
        ),
        (
            [
                _fact("LesseeOperatingLeaseLiabilityPaymentsDue"),
                _fact("LesseeOperatingLeaseLiabilityPaymentsDue", context="other-2023"),
            ],
            {"name": "LesseeOperatingLeaseLiabilityPaymentsDue"},
        ),
        (
            [_fact("LesseeOperatingLeaseLiabilityPaymentsDue", unit="")],
            {"name": "LesseeOperatingLeaseLiabilityPaymentsDue"},
        ),
        (
            [_fact("LesseeOperatingLeaseLiabilityPaymentsDue", context="")],
            {"name": "LesseeOperatingLeaseLiabilityPaymentsDue"},
        ),
        (
            [_fact("LesseeOperatingLeaseLiabilityPaymentsDue")],
            {"name": "FinanceLeaseLiabilityPaymentsDue"},
        ),
    ],
)
def test_unbound_or_ambiguous_warning_refuses(facts, parameters):
    with pytest.raises(ArelleParserError) as failure:
        message_parameters("DQC.US.0090.9374", "warning", facts, parameters)
    assert failure.value.code == "DQC_DIAGNOSTIC_BINDING_UNAVAILABLE"


@pytest.mark.parametrize(
    "code", ["DQC.US.0091.9374", "DQC.US.0090.0000", "EFM.6.01.01"]
)
def test_unrelated_diagnostics_are_unchanged(code):
    parameters = {"contextID": "original", "unitID": "original"}
    assert (
        message_parameters(code, "original message", [], parameters)
        == "original message"
    )
    assert parameters == {"contextID": "original", "unitID": "original"}


@pytest.mark.parametrize(
    "rule,name",
    (
        ("9374", "LesseeOperatingLeaseLiabilityPaymentsDue"),
        ("9375", "FinanceLeaseLiabilityPaymentsDue"),
    ),
)
def test_full_xule_message_keeps_official_text_and_binds_referenced_fact(rule, name):
    fact = _fact(name, context="E26Q1")
    message = (
        f"The element us-gaap:{name} with a value of 545,906 should be equal "
        "to the sum of the reported components.\nPeriod :2026-03-31\nUnit : USD"
    )
    parameters = {"severity": "warning", "cid": "opaque-xule-object-reference"}
    assert (
        message_parameters(f"DQC.US.0090.{rule}", message, [fact], parameters)
        == message
    )
    assert parameters == {
        "severity": "warning",
        "cid": "opaque-xule-object-reference",
        "contextID": "E26Q1",
        "unitID": "USD",
    }


@pytest.mark.parametrize(
    "text",
    (
        "The element us-gaap:Other with a value of 545,906 should be equal",
        "The element us-gaap:LesseeOperatingLeaseLiabilityPaymentsDue with a value of 1 should be equal",
        "unknown full-rule message",
    ),
)
def test_full_xule_message_with_unbound_name_or_value_refuses(text):
    with pytest.raises(ArelleParserError) as failure:
        message_parameters(
            "DQC.US.0090.9374",
            text,
            [_fact("LesseeOperatingLeaseLiabilityPaymentsDue")],
            {"severity": "error"},
        )
    assert failure.value.code == "DQC_DIAGNOSTIC_BINDING_UNAVAILABLE"


@pytest.mark.parametrize(
    "value", [None, True, "545906", Decimal("NaN"), Decimal("Infinity")]
)
def test_full_xule_message_with_invalid_numeric_fact_refuses(value):
    fact = _fact("LesseeOperatingLeaseLiabilityPaymentsDue")
    fact.xValue = value
    with pytest.raises(ArelleParserError) as failure:
        message_parameters("DQC.US.0090.9374", "unknown message", [fact], {})
    assert failure.value.code == "DQC_DIAGNOSTIC_BINDING_UNAVAILABLE"


@pytest.mark.parametrize("level", ["ERROR", "WARNING", "CRITICAL", "FATAL"])
def test_official_rule_severity_survives_efm_releveling(level):
    records = []

    def efm_log(level, codes, message, **parameters):
        records.append(
            {
                "level": "warning",
                "code": codes,
                "message": {"text": message, "args": parameters},
            }
        )

    model = SimpleNamespace(log=efm_log)
    preserve_rule_severity(None, None, model)
    model.log(
        level=level,
        codes="DQC.US.0090.9374",
        msg="official rule message",
        severity="warning",
    )
    finding = _finding_from_log(records[0])
    assert finding.severity == "warning"
    assert finding.rule_severity == level.lower()
    assert finding.message == "official rule message"


def test_unrelated_log_arguments_remain_unchanged():
    records = []
    model = SimpleNamespace(log=lambda *args, **kwargs: records.append((args, kwargs)))
    preserve_rule_severity(None, None, model)
    model.log("ERROR", "EFM.6.01.01", "official EFM message", severity="error")
    assert records == [
        (("ERROR", "EFM.6.01.01", "official EFM message"), {"severity": "error"})
    ]
