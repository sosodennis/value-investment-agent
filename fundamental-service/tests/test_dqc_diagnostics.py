from decimal import Decimal
from dataclasses import dataclass
from datetime import date, datetime
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


def _document_type_only_diagnostic(
    rule="9374", name="LesseeOperatingLeaseLiabilityPaymentsDue"
):
    fact = _fact(name, context="E23Q1")
    fact.context = SimpleNamespace(
        isInstantPeriod=True,
        instantDatetime=datetime(2023, 4, 1),
        qnameDims={},
        segNonDimValues=[],
        scenNonDimValues=[],
    )
    fact.unit = SimpleNamespace(
        measures=([_QName("USD", "http://www.xbrl.org/2003/iso4217")], [])
    )
    fact.decimals = "INF"
    model = SimpleNamespace(facts=[fact])
    fact.modelXbrl = model
    document_type = SimpleNamespace(modelXbrl=model)
    message = (
        f"The element us-gaap:{name} with a value of 545,906 should be equal "
        "to the sum of the reported components. A difference of 27,200.\n"
        "Period :2023-03-31\nDimensions : \nUnit : USD\nDecimals: inf\n\n"
        f"Rule Element Id:{rule}\nRule version: 31.0.3"
    )
    return fact, document_type, message


@pytest.mark.parametrize(
    "rule,name",
    [
        ("9374", "LesseeOperatingLeaseLiabilityPaymentsDue"),
        ("9375", "FinanceLeaseLiabilityPaymentsDue"),
    ],
)
def test_document_type_reference_binds_unique_original_fact_and_preserves_error(
    rule, name
):
    _, document_type, message = _document_type_only_diagnostic(rule, name)
    parameters = {
        "contextID": "stale-document-type-context",
        "unitID": "stale-unit",
        "fundamental_rule_severity": "error",
    }
    assert (
        message_parameters(f"DQC.US.0090.{rule}", message, [document_type], parameters)
        == message
    )
    assert parameters == {
        "contextID": "E23Q1",
        "unitID": "USD",
        "fundamental_rule_severity": "error",
    }


@pytest.mark.parametrize(
    "before,after",
    [
        ("545,906", "545,907"),
        ("2023-03-31", "2023-04-01"),
        ("2023-03-31", "2023-02-30"),
        ("Dimensions : ", "Dimensions : issuer:Axis=issuer:Member"),
        ("Unit : USD", "Unit : EUR"),
        ("Decimals: inf", "Decimals: -3"),
        ("Rule Element Id:9374", "Rule Element Id:9375"),
        ("Rule version: 31.0.3", "Rule version: 99.0.0"),
        (
            "us-gaap:LesseeOperatingLeaseLiabilityPaymentsDue",
            "issuer:LesseeOperatingLeaseLiabilityPaymentsDue",
        ),
    ],
)
def test_original_model_binding_refuses_altered_or_unsupported_rendered_signature(
    before, after
):
    _, document_type, message = _document_type_only_diagnostic()
    parameters = {"contextID": "unchanged"}
    with pytest.raises(ArelleParserError) as failure:
        message_parameters(
            "DQC.US.0090.9374",
            message.replace(before, after),
            [document_type],
            parameters,
        )
    assert failure.value.code == "DQC_DIAGNOSTIC_BINDING_UNAVAILABLE"
    assert parameters == {"contextID": "unchanged"}


@pytest.mark.parametrize(
    "defect",
    [
        "missing",
        "duplicate",
        "cross_model",
        "multiple_models",
        "nil",
        "extension",
        "duration",
        "instant_time",
        "dimension",
        "segment",
        "scenario",
        "unit_namespace",
        "divided_unit",
        "decimals",
    ],
)
def test_original_model_binding_refuses_ambiguous_or_mismatched_original_fact(defect):
    fact, document_type, message = _document_type_only_diagnostic()
    references = [document_type]
    if defect == "missing":
        document_type.modelXbrl.facts = []
    elif defect == "duplicate":
        from copy import copy

        document_type.modelXbrl.facts.append(copy(fact))
    elif defect == "cross_model":
        fact.modelXbrl = SimpleNamespace()
    elif defect == "multiple_models":
        references.append(SimpleNamespace(modelXbrl=SimpleNamespace(facts=[])))
    elif defect == "nil":
        fact.isNil = True
    elif defect == "extension":
        fact.qname.namespaceURI = "http://issuer.example/2023"
    elif defect == "duration":
        fact.context.isInstantPeriod = False
    elif defect == "instant_time":
        fact.context.instantDatetime = datetime(2023, 4, 1, 12)
    elif defect == "dimension":
        fact.context.qnameDims = {"issuer:Axis": "issuer:Member"}
    elif defect == "segment":
        fact.context.segNonDimValues = ["unmodeled-segment"]
    elif defect == "scenario":
        fact.context.scenNonDimValues = ["unmodeled-scenario"]
    elif defect == "unit_namespace":
        fact.unit.measures[0][0].namespaceURI = "http://issuer.example/unit"
    elif defect == "divided_unit":
        fact.unit.measures[1].append(
            _QName("shares", "http://www.xbrl.org/2003/instance")
        )
    elif defect == "decimals":
        fact.decimals = "-3"
    with pytest.raises(ArelleParserError) as failure:
        message_parameters("DQC.US.0090.9374", message, references, {})
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


def test_official_rule_effective_date_survives_log_normalization():
    record = {
        "level": "warning",
        "code": "DQC.US.0099.9533",
        "message": {
            "text": "official rule message",
            "args": {
                "fundamental_rule_severity": "error",
                "effectiveDate": "2021-01-01",
            },
        },
    }
    finding = _finding_from_log(record)
    assert finding.rule_effective_date == date(2021, 1, 1)
    assert finding.rule_severity == "error"
    assert finding.severity == "warning"
    assert type(finding).model_validate_json(finding.model_dump_json()) == finding


@pytest.mark.parametrize("value", [None, "", "None"])
def test_unknown_official_rule_effective_date_stays_unknown(value):
    finding = _finding_from_log(
        {
            "level": "warning",
            "code": "DQC.US.0249.10961",
            "message": {"args": {"effectiveDate": value}},
        }
    )
    assert finding.rule_effective_date is None
    assert "rule_effective_date" not in finding.model_dump(mode="json")


@pytest.mark.parametrize(
    "value", [True, 20260101, "2026-02-30", "20260101", "2026-01-01T00:00:00Z"]
)
def test_malformed_official_rule_effective_date_refuses(value):
    with pytest.raises(ArelleParserError) as failure:
        _finding_from_log(
            {
                "level": "warning",
                "code": "DQC.US.0249.10961",
                "message": {"args": {"effectiveDate": value}},
            }
        )
    assert failure.value.code == "DQC_EFFECTIVE_DATE_INVALID"


def test_non_dqc_message_parameter_cannot_assert_rule_effective_date():
    finding = _finding_from_log(
        {
            "level": "error",
            "code": "EFM.6.08.05.firstLetter",
            "message": {"args": {"effectiveDate": "2099-01-01"}},
        }
    )
    assert finding.rule_effective_date is None


def test_unrelated_log_arguments_remain_unchanged():
    records = []
    model = SimpleNamespace(log=lambda *args, **kwargs: records.append((args, kwargs)))
    preserve_rule_severity(None, None, model)
    model.log("ERROR", "EFM.6.01.01", "official EFM message", severity="error")
    assert records == [
        (("ERROR", "EFM.6.01.01", "official EFM message"), {"severity": "error"})
    ]
