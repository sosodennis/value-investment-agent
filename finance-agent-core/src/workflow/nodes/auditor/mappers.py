from .structures import AuditOutput


def summarize_auditor_for_preview(audit_output: AuditOutput) -> dict:
    """
    Summarizes the auditor's output for UI preview.

    Args:
        audit_output: The output object from the auditor node.

    Returns:
        dict: A dictionary matching the AuditorPreview schema.
    """
    return {
        "passed": audit_output.passed,
        "finding_count": len(audit_output.messages),
        "status": "completed",
    }
