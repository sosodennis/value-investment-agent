from src.workflow.nodes.calculator.mappers import summarize_calculator_for_preview


def test_summarize_calculator_for_preview_positive():
    result = {"intrinsic_value": 150.50, "upside_potential": 0.25}
    model_type = "saas"

    preview = summarize_calculator_for_preview(result, model_type)

    assert preview["model_type"] == "saas"
    assert preview["intrinsic_value_display"] == "$150.50"
    assert preview["upside_display"] == "+25.0%"
    assert preview["confidence_display"] == "Medium"


def test_summarize_calculator_for_preview_negative():
    result = {"intrinsic_value": 80.00, "upside_potential": -0.10}
    model_type = "bank"

    preview = summarize_calculator_for_preview(result, model_type)

    assert preview["model_type"] == "bank"
    assert preview["intrinsic_value_display"] == "$80.00"
    assert preview["upside_display"] == "-10.0%"
