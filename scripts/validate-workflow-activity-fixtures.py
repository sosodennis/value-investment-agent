from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TypeError(f"{label} must be an object")
    return value


def _contract_file(
    contracts_dir: Path, fixtures_dir: Path, value: Any, label: str
) -> Path:
    if not isinstance(value, str) or not value:
        raise TypeError(f"{label} must be a non-empty path")
    path = (fixtures_dir / value).resolve()
    if not path.is_relative_to(contracts_dir.resolve()):
        raise ValueError(f"{label} must remain inside contracts/")
    if not path.is_file():
        raise FileNotFoundError(f"{label} does not exist: {value}")
    return path


def _validate_contract(
    entry: Any, *, index: int, contracts_dir: Path, fixtures_dir: Path
) -> None:
    label = f"manifest.activity_contracts[{index}]"
    contract = _object(entry, label)
    version = contract.get("version")
    event_name = contract.get("event_name")
    if not isinstance(version, str) or not version:
        raise TypeError(f"{label}.version must be a non-empty string")
    if not isinstance(event_name, str) or not event_name:
        raise TypeError(f"{label}.event_name must be a non-empty string")

    schema = _object(
        _load_json(
            _contract_file(
                contracts_dir, fixtures_dir, contract.get("schema"), f"{label}.schema"
            )
        ),
        f"{label}.schema",
    )
    fixture = _object(
        _load_json(
            _contract_file(
                contracts_dir, fixtures_dir, contract.get("fixture"), f"{label}.fixture"
            )
        ),
        f"{label}.fixture",
    )
    Draft202012Validator.check_schema(schema)

    properties = _object(schema.get("properties"), f"{label}.schema.properties")
    for field, expected in (("event_name", event_name),):
        definition = _object(
            properties.get(field), f"{label}.schema.properties.{field}"
        )
        if definition.get("const") != expected:
            raise ValueError(f"{label}.schema {field} does not match manifest")
    if fixture.get("contract_version") != version:
        raise ValueError(f"{label}.fixture contract_version does not match manifest")
    if fixture.get("event_name") != event_name:
        raise ValueError(f"{label}.fixture event_name does not match manifest")

    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    scenarios = fixture.get("scenarios")
    if not isinstance(scenarios, list) or not scenarios:
        raise ValueError(f"{label}.fixture.scenarios must be a non-empty array")
    errors = []
    for scenario_index, scenario in enumerate(scenarios):
        scenario_object = _object(
            scenario, f"{label}.fixture.scenarios[{scenario_index}]"
        )
        events = scenario_object.get("events")
        if not isinstance(events, list) or not events:
            raise ValueError(
                f"{label}.fixture.scenarios[{scenario_index}].events must be a non-empty array"
            )
        for event in events:
            errors.extend(validator.iter_errors(event))
    errors.sort(key=lambda error: list(error.path))
    if errors:
        details = "\n".join(
            f"{label}.fixture/{'/'.join(map(str, error.path)) or '<root>'}: {error.message}"
            for error in errors
        )
        raise ValueError(details)


def main() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    contracts_dir = repo_root / "contracts"
    fixtures_dir = contracts_dir / "fixtures"
    manifest = _object(_load_json(fixtures_dir / "manifest.json"), "manifest.json")
    contracts = manifest.get("activity_contracts")
    if not isinstance(contracts, list) or not contracts:
        raise TypeError("manifest.activity_contracts must be a non-empty array")

    versions: set[str] = set()
    for index, contract in enumerate(contracts):
        entry = _object(contract, f"manifest.activity_contracts[{index}]")
        version = entry.get("version")
        if not isinstance(version, str) or version in versions:
            raise ValueError(
                f"manifest.activity_contracts[{index}].version is missing or duplicated"
            )
        versions.add(version)
        _validate_contract(
            contract,
            index=index,
            contracts_dir=contracts_dir,
            fixtures_dir=fixtures_dir,
        )

    print("Workflow activity fixture validation passed.")


if __name__ == "__main__":
    main()
