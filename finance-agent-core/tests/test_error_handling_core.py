from decimal import Decimal

from src.infrastructure.serialization import FinancialSafeSerializer
from src.workflow.nodes.auditor.nodes import auditor_node
from src.workflow.nodes.calculator.nodes import calculation_node
from src.workflow.nodes.executor.nodes import executor_node


def test_financial_safe_serializer_decimal():
    serializer = FinancialSafeSerializer()
    data = {"amount": Decimal("123.45")}
    serialized = serializer.dumps(data)
    deserialized = serializer.loads(serialized)
    assert deserialized["amount"] == Decimal("123.45")
    assert isinstance(deserialized["amount"], Decimal)


def test_executor_error_log():
    # Trigger unknown model type error
    state = {"fundamental_analysis": {"model_type": "unknown_type"}, "ticker": "AAPL"}

    command = executor_node(state)

    assert "error_logs" in command.update
    assert command.update["error_logs"][0]["node"] == "executor"
    assert "Unknown model type" in command.update["error_logs"][0]["error"]
    assert command.update["node_statuses"]["executor"] == "error"
    assert command.goto == "__end__"


def test_auditor_error_log():
    # Trigger no extraction_output error
    state = {
        "fundamental_analysis": {"model_type": "saas"},
    }

    command = auditor_node(state)

    assert "error_logs" in command.update
    assert command.update["error_logs"][0]["node"] == "auditor"
    assert "No extraction output found" in command.update["error_logs"][0]["error"]
    assert command.update["node_statuses"]["auditor"] == "error"


def test_calculator_error_log():
    # Trigger skill not found error
    state = {
        "fundamental_analysis": {"model_type": "invalid"},
    }

    command = calculation_node(state)

    assert "error_logs" in command.update
    assert command.update["error_logs"][0]["node"] == "calculator"
    assert "Skill not found" in command.update["error_logs"][0]["error"]
    assert command.update["node_statuses"]["calculator"] == "error"
