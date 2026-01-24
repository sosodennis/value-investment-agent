from src.workflow.state import IntentExtractionContext, merge_intent_extraction_context


def test_merge_with_extra_fields():
    """
    Verify that merging a dictionary with extra fields (like 'node_statuses')
    into IntentExtractionContext does not raise a ValueError.
    """
    current = IntentExtractionContext(status="extraction")
    update_payload = {
        "status": "done",
        "node_statuses": {"intent_extraction": "done"},  # Extra field that caused crash
        "unexpected_field": "some_value",
    }

    try:
        updated = merge_intent_extraction_context(current, update_payload)

        # Assert valid fields are updated
        assert updated.status == "done"

        # Assert extra fields are IGNORED and do not cause crash
        assert not hasattr(updated, "node_statuses")
        assert not hasattr(updated, "unexpected_field")

        print("✅ test_merge_with_extra_fields PASSED")
    except Exception as e:
        print(f"❌ test_merge_with_extra_fields FAILED: {e}")
        raise e


if __name__ == "__main__":
    test_merge_with_extra_fields()
