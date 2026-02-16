import json
from pathlib import Path

from src.interface.events.protocol import PROTOCOL_VERSION, AgentEvent


def _load_supported_fixture_sets() -> list[tuple[str, list[dict[str, object]]]]:
    repo_root = Path(__file__).resolve().parents[2]
    fixtures_dir = repo_root / "contracts" / "fixtures"
    manifest_path = fixtures_dir / "manifest.json"
    manifest_raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest_raw, dict):
        raise TypeError("manifest.json must be an object")

    supported = manifest_raw.get("supported_versions")
    if not isinstance(supported, list) or not supported:
        raise TypeError("supported_versions must be a non-empty list")

    fixture_sets: list[tuple[str, list[dict[str, object]]]] = []
    for entry in supported:
        if not isinstance(entry, dict):
            raise TypeError("Each supported version entry must be an object")
        version = entry.get("version")
        fixture_name = entry.get("fixture")
        if not isinstance(version, str) or not isinstance(fixture_name, str):
            raise TypeError("supported version entries require string version/fixture")

        fixture_path = fixtures_dir / fixture_name
        raw = json.loads(fixture_path.read_text(encoding="utf-8"))
        if not isinstance(raw, list):
            raise TypeError(f"{fixture_name} must contain a list of events")

        normalized: list[dict[str, object]] = []
        for item in raw:
            if not isinstance(item, dict):
                raise TypeError("Each fixture event must be an object")
            normalized.append(item)
        fixture_sets.append((version, normalized))

    return fixture_sets


def test_fixture_events_validate_against_backend_protocol() -> None:
    fixture_sets = _load_supported_fixture_sets()
    assert fixture_sets, "Supported fixture set should not be empty"

    for version, events in fixture_sets:
        assert events, f"Fixture event list should not be empty for {version}"
        if version != PROTOCOL_VERSION:
            continue

        seq_ids: list[int] = []
        for payload in events:
            event = AgentEvent.model_validate(payload)
            assert event.protocol_version == PROTOCOL_VERSION
            seq_ids.append(event.seq_id)
        assert seq_ids == sorted(seq_ids)
