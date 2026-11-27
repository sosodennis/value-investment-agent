from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "finance-agent-core"), str(ROOT / "fundamental-service/src")]


def main() -> None:
    from fundamental_service import fiscal_read_contracts as owner
    from src.shared.artifacts.fiscal_statement_contracts import (
        FiscalReadRequestV2,
        FiscalReadResultV2,
    )

    for service, consumer in (
        (owner.FiscalReadRequestV2, FiscalReadRequestV2),
        (owner.FiscalReadResultV2, FiscalReadResultV2),
    ):
        for mode in ("validation", "serialization"):
            if service.model_json_schema(mode=mode) != consumer.model_json_schema(
                mode=mode
            ):
                raise SystemExit(f"Fiscal wire {mode} schema drift: {service.__name__}")
    print("Service/Core fiscal request and result input/output schemas match exactly.")


if __name__ == "__main__":
    main()
