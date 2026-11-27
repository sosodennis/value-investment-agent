"""Export standalone serialization schemas from the Core statement reader models."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pydantic.json_schema import GenerateJsonSchema
from pydantic_core import core_schema

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "finance-agent-core"))


class StatementSerializationSchema(GenerateJsonSchema):
    def field_is_required(
        self,
        field: core_schema.ModelField
        | core_schema.DataclassField
        | core_schema.TypedDictField,
        total: bool,
    ) -> bool:
        if self.mode == "serialization":
            return field.get("serialization_exclude_if") is None
        return super().field_is_required(field, total)


def render() -> dict[Path, str]:
    from src.agents.fundamental.application.statement_reader_contracts import (
        StatementCatalogV2,
    )
    from src.shared.artifacts.statement_read_artifact import StatementReadArtifactV3

    outputs = {}
    for filename, model in (
        ("statement-read-artifact.schema.v3.json", StatementReadArtifactV3),
        ("statement-catalog.schema.v2.json", StatementCatalogV2),
    ):
        schema = model.model_json_schema(
            mode="serialization", schema_generator=StatementSerializationSchema
        )
        schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        outputs[ROOT / "frontend" / "src" / "types" / "generated" / filename] = (
            json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        )
    return outputs


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    outputs = render()
    if args.check:
        for path, rendered in outputs.items():
            if not path.exists() or path.read_text(encoding="utf-8") != rendered:
                raise SystemExit(
                    f"Statement reader schema drift: {path.relative_to(ROOT)}. "
                    "Run scripts/generate-statement-reader-schema.py."
                )
        print("Generated statement reader schemas are current.")
    else:
        for path, rendered in outputs.items():
            path.write_text(rendered, encoding="utf-8")
            print(f"Generated {path}")


if __name__ == "__main__":
    main()
