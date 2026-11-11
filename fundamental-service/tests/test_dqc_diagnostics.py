from decimal import Decimal
from types import SimpleNamespace

import pytest

from fundamental_service.arelle_parser import ArelleParserError
from fundamental_service.dqc_diagnostic_plugin import message_parameters


def _fact(
    name, context="actual-2024", *, namespace="http://fasb.org/us-gaap/2024", unit="USD"
):
    return SimpleNamespace(
        qname=SimpleNamespace(localName=name, namespaceURI=namespace),
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
