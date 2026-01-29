from src.workflow.nodes.executor.mappers import summarize_executor_for_preview


def test_summarize_executor_for_preview_saas():
    extraction_output = {
        "params": {"revenue_growth": 0.20, "margin": 0.15, "retention": 0.90}
    }
    model_type = "saas"

    preview = summarize_executor_for_preview(extraction_output, model_type)

    assert preview["model_type"] == "saas"
    assert preview["param_count"] == 3
    assert preview["status"] == "extracted"


def test_summarize_executor_for_preview_empty():
    extraction_output = {"params": {}}
    model_type = "bank"

    preview = summarize_executor_for_preview(extraction_output, model_type)

    assert preview["model_type"] == "bank"
    assert preview["param_count"] == 0
    assert preview["status"] == "extracted"
