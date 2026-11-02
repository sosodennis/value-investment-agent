from src.workflow.state import merge_resettable_dict, merge_resettable_logs


def test_transport_map_reducer_merges_parallel_branch_updates() -> None:
    assert merge_resettable_dict({"fundamental": "fa-1"}, {"news": "news-1"}) == {
        "fundamental": "fa-1",
        "news": "news-1",
    }


def test_transport_map_reducer_clears_previous_run_when_reset() -> None:
    assert merge_resettable_dict({"old-run": "artifact-1"}, None) == {}


def test_error_log_reducer_merges_new_entries_without_duplication() -> None:
    existing = [{"node": "fundamental", "error": "unavailable"}]
    assert merge_resettable_logs(
        existing, [*existing, {"node": "news", "error": "timeout"}]
    ) == [
        existing[0],
        {"node": "news", "error": "timeout"},
    ]


def test_error_log_reducer_clears_previous_run_when_reset() -> None:
    assert merge_resettable_logs([{"node": "old", "error": "stale"}], None) == []
