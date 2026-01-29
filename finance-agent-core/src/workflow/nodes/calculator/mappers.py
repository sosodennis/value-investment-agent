from typing import Any


def summarize_calculator_for_preview(
    result: dict[str, Any], model_type: str
) -> dict[str, Any]:
    """
    Summarizes the calculation result for UI preview.

    Args:
        result: The calculation result dictionary.
        model_type: The model type used.

    Returns:
        dict: A dictionary matching the CalculatorPreview schema.
    """
    iv = result.get("intrinsic_value", 0)
    upside = result.get("upside_potential", 0)

    return {
        "model_type": model_type,
        # Format as string for display stability in preview
        "intrinsic_value_display": f"${iv:,.2f}",
        "upside_display": f"{upside:+.1%}",
        # Simple confidence logic for now
        "confidence_display": "Medium",
    }
