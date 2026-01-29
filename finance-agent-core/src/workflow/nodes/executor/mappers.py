from typing import Any


def summarize_executor_for_preview(
    extraction_output: dict[str, Any], model_type: str
) -> dict[str, Any]:
    """
    Summarizes the executor's output for UI preview.

    Args:
        extraction_output: The raw output from the executor node.
        model_type: The type of valuation model (e.g., 'saas', 'bank').

    Returns:
        dict: A dictionary matching the ExecutorPreview schema.
    """
    params = extraction_output.get("params", {})
    return {"model_type": model_type, "param_count": len(params), "status": "extracted"}
