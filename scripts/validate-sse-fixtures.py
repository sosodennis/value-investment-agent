from __future__ import annotations

import json
from pathlib import Path


def _load_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    fixtures_dir = repo_root / "contracts" / "fixtures"
    manifest_path = fixtures_dir / "manifest.json"
    manifest_raw = _load_json(manifest_path)
    if not isinstance(manifest_raw, dict):
        raise TypeError("manifest.json must be a JSON object")

    supported_raw = manifest_raw.get("supported_versions")
    if not isinstance(supported_raw, list) or not supported_raw:
        raise ValueError("supported_versions must be a non-empty list")

    for entry in supported_raw:
        if not isinstance(entry, dict):
            raise TypeError("Each supported_versions entry must be an object")
        version = entry.get("version")
        fixture_name = entry.get("fixture")
        if not isinstance(version, str) or not version:
            raise TypeError("supported_versions.version must be a non-empty string")
        if not isinstance(fixture_name, str) or not fixture_name:
            raise TypeError("supported_versions.fixture must be a non-empty string")

        fixture_path = fixtures_dir / fixture_name
        if not fixture_path.exists():
            raise FileNotFoundError(f"Missing fixture file: {fixture_path}")
        fixture_raw = _load_json(fixture_path)
        if not isinstance(fixture_raw, list) or not fixture_raw:
            raise ValueError(f"Fixture must be a non-empty list: {fixture_path}")

        seq_ids: list[int] = []
        for idx, event in enumerate(fixture_raw):
            if not isinstance(event, dict):
                raise TypeError(f"{fixture_name}[{idx}] must be an object")
            protocol_version = event.get("protocol_version")
            if protocol_version != version:
                raise ValueError(
                    f"{fixture_name}[{idx}] protocol_version={protocol_version!r} "
                    f"does not match manifest version {version!r}"
                )
            seq_id = event.get("seq_id")
            if not isinstance(seq_id, int):
                raise TypeError(f"{fixture_name}[{idx}] seq_id must be int")
            seq_ids.append(seq_id)

        if seq_ids != sorted(seq_ids):
            raise ValueError(
                f"{fixture_name} seq_id values must be monotonically increasing"
            )

    print("SSE fixtures validation passed.")


if __name__ == "__main__":
    main()
