"""Generate Core fiscal transport declarations from the service-owned wire.

Only reachable DTO declarations are copied. Service policy/projection code and
internal runtime dependencies stay outside Core. The consumer adds string-only
Decimal validation and fixed-point JSON serialization at its decode boundary.
"""

from __future__ import annotations

import argparse
import ast
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "fundamental-service/src/fundamental_service"
OUTPUT = ROOT / "finance-agent-core/src/shared/artifacts/fiscal_statement_contracts.py"
HEADER = r'''"""Generated consumer of the Fundamental fiscal-statements.v2 wire.

Regenerate with scripts/generate-fiscal-wire-contract.py; service declarations
own the shape. Consumer-only Decimal string validation is added at decoding.

Field shapes and wire validators follow the service-owned DTO. No projection,
selection, financial calculation, or admission policy is implemented here.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Annotated, Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)

from src.shared.artifacts.annual_statement_contracts import (
    StatementRowId,
    StatementScopeV1,
)

Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class FiscalTransportModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _wire_decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    if not isinstance(value, (str, Decimal)):
        raise ValueError("fiscal wire amounts require decimal strings")
    try:
        parsed = Decimal(value)
    except InvalidOperation as error:
        raise ValueError("fiscal wire amount is not a decimal") from error
    if not parsed.is_finite():
        raise ValueError("fiscal wire amount must be finite")
    return parsed




def _canonical(value: object) -> object:
    if isinstance(value, BaseModel):
        return _canonical(value.model_dump(mode="python"))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _canonical(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_canonical(item) for item in value]
    return value


def fiscal_digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            _canonical(value),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode()
    ).hexdigest()


'''


def render() -> str:
    declarations: dict[str, tuple[str, ast.AST]] = {}
    for filename in (
        "fiscal_statement_contracts.py",
        "fiscal_read_contracts.py",
        "fiscal_statement_policy.py",
        "fiscal_release_contracts.py",
        "data_releases.py",
        "contracts.py",
    ):
        source = (SOURCE / filename).read_text()
        for node in ast.parse(source).body:
            if filename == "contracts.py" and not (
                isinstance(node, ast.ClassDef) and node.name == "QualityStatus"
            ):
                continue
            if isinstance(node, (ast.ClassDef, ast.FunctionDef)):
                declarations[node.name] = (source, node)
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        declarations[target.id] = (source, node)
    seen: set[str] = set()
    ordered: list[str] = []

    def visit(name: str) -> None:
        if (
            name in seen
            or name not in declarations
            or name in {"ReleaseModel", "StrictModel", "Digest"}
        ):
            return
        seen.add(name)
        source, node = declarations[name]
        for item in ast.walk(node):
            if isinstance(item, ast.Name) and item.id != name:
                visit(item.id)
        segment = ast.get_source_segment(source, node)
        assert segment is not None
        ordered.append(segment)

    visit("FiscalReadRequestV2")
    visit("FiscalReadResultV2")
    text = HEADER + "\n\n".join(ordered) + "\n"
    text = (
        text.replace("(ReleaseModel)", "(FiscalTransportModel)")
        .replace("(StrictModel)", "(FiscalTransportModel)")
        .replace("sha256_digest(", "fiscal_digest(")
    )
    lines = text.splitlines(keepends=True)
    remove = []
    for node in ast.parse(text).body:
        if isinstance(node, ast.ClassDef):
            for method in node.body:
                if isinstance(method, ast.FunctionDef) and method.name in {
                    "overlaps",
                    "same_accounting_scope",
                    "basis_digest",
                    "observation_digest",
                }:
                    first = min(
                        [
                            method.lineno,
                            *(decorator.lineno for decorator in method.decorator_list),
                        ]
                    )
                    remove.append((first - 1, method.end_lineno))
    for start, end in sorted(remove, reverse=True):
        del lines[start:end]
    text = "".join(lines)
    for name, fields in (
        ("FiscalValueNodeV1", '"value"'),
        ("FiscalPrecisionIntervalV1", '"lower", "upper"'),
        ("FiscalReconciliationV1", '"residual"'),
    ):
        marker = f"class {name}(FiscalTransportModel):\n"
        text = text.replace(
            marker,
            marker
            + f"""    @field_validator({fields}, mode="before")
    @classmethod
    def decimal_wire_boundary(cls, value: object) -> Decimal | None:
        return _wire_decimal(value)

    @field_serializer({fields}, when_used="json")
    def decimal_wire(self, value: Decimal | None) -> str | None:
        return format(value, "f") if value is not None else None

""",
        )
    text = text.replace(
        '    @field_serializer("lower", "upper", when_used="json")\n'
        "    def decimal_wire(self, value: Decimal | None) -> str | None:\n"
        '        return format(value, "f") if value is not None else None',
        '    @field_serializer("lower", "upper", when_used="json")\n'
        "    def decimal_wire(self, value: Decimal) -> str:\n"
        '        return format(value, "f")',
    )
    text = text.replace(
        "class FiscalObservationV1(FiscalTransportModel):\n",
        """class FiscalObservationV1(FiscalTransportModel):
    @field_serializer("value", when_used="json")
    def decimal_wire(self, value: Decimal | None) -> str | None:
        return format(value, "f") if value is not None else None

""",
    )
    text = text.replace(
        """        if value is None or isinstance(value, Decimal):
            return value
        if isinstance(value, str):
            return Decimal(value)
        raise ValueError("fiscal amounts require a Decimal or decimal string")""",
        """        return _wire_decimal(value)""",
    )
    lines = text.splitlines(keepends=True)
    replacements = []
    for node in ast.walk(ast.parse(text)):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "isinstance"
            and len(node.args) == 2
            and isinstance(node.args[1], ast.Tuple)
            and all(isinstance(item, ast.Name) for item in node.args[1].elts)
        ):
            types = node.args[1]
            start = sum(map(len, lines[: types.lineno - 1])) + types.col_offset
            end = sum(map(len, lines[: types.end_lineno - 1])) + types.end_col_offset
            replacements.append(
                (start, end, " | ".join(item.id for item in types.elts))
            )
    for start, end, union in sorted(replacements, reverse=True):
        text = text[:start] + union + text[end:]
    process = subprocess.run(
        [sys.executable, "-m", "ruff", "format", "--stdin-filename", str(OUTPUT)],
        input=text,
        text=True,
        capture_output=True,
        check=True,
    )
    return process.stdout


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    rendered = render()
    if args.check:
        if OUTPUT.read_text() != rendered:
            raise SystemExit(
                "Fiscal transport drift: regenerate scripts/generate-fiscal-wire-contract.py"
            )
        print("Generated fiscal transport is current.")
    else:
        OUTPUT.write_text(rendered)
        print(f"Generated {OUTPUT}")


if __name__ == "__main__":
    main()
