from src.workflow.nodes.auditor.mappers import summarize_auditor_for_preview
from src.workflow.nodes.auditor.structures import AuditOutput


def test_summarize_auditor_for_preview_passed():
    audit_output = AuditOutput(passed=True, messages=[])

    preview = summarize_auditor_for_preview(audit_output)

    assert preview["passed"] is True
    assert preview["finding_count"] == 0
    assert preview["status"] == "completed"


def test_summarize_auditor_for_preview_failed():
    audit_output = AuditOutput(
        passed=False, messages=["Revenue growth is negative", "Profit margin too low"]
    )

    preview = summarize_auditor_for_preview(audit_output)

    assert preview["passed"] is False
    assert preview["finding_count"] == 2
    assert preview["status"] == "completed"
