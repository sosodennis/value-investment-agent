from pathlib import Path

from fundamental_service.architecture_guard import check


def test_fundamental_service_boundary_has_no_legacy_auth_or_agent_imports():
    root = Path(__file__).resolve().parents[1]
    assert check(root) == []
