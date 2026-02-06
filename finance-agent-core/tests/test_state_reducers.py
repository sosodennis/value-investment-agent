from src.workflow.state import append_logs


def test_append_logs_basic():
    a = [{"node": "n1", "error": "e1"}]
    b = [{"node": "n2", "error": "e2"}]
    result = append_logs(a, b)
    assert len(result) == 2
    assert result[0]["node"] == "n1"
    assert result[1]["node"] == "n2"


def test_append_logs_none_a():
    b = [{"node": "n2", "error": "e2"}]
    result = append_logs(None, b)
    assert result == b


def test_append_logs_none_b():
    a = [{"node": "n1", "error": "e1"}]
    result = append_logs(a, None)
    assert result == a


def test_append_logs_empty():
    result = append_logs([], [])
    assert result == []
