from __future__ import annotations

from typing import cast

import pytest

from src.agents.fundamental.subdomains.artifacts_provenance.infrastructure.fundamental_artifact_repository import (
    FundamentalArtifactRepository,
)
from src.agents.fundamental.subdomains.artifacts_provenance.interface.contracts import (
    parse_fundamental_artifact_model,
)
from src.shared.cross_agent.data.typed_artifact_port import TypedArtifactPort
from src.shared.kernel.types import JSONObject


def test_parse_fundamental_artifact_applies_canonical_defaults() -> None:
    payload = parse_fundamental_artifact_model(
        {
            "ticker": "AAPL",
            "model_type": "dcf_standard",
            "company_name": None,
            "sector": None,
            "industry": None,
            "reasoning": None,
            "financial_reports": [],
            "status": "done",
        }
    )

    assert payload["company_name"] == "AAPL"
    assert payload["sector"] == "Unknown"
    assert payload["industry"] == "Unknown"
    assert payload["reasoning"] == ""
    assert payload["financial_reports"] == []


def test_parse_fundamental_artifact_rejects_noncompleted_status() -> None:
    with pytest.raises(TypeError, match="fundamental artifact.status"):
        parse_fundamental_artifact_model(
            {
                "ticker": "AAPL",
                "model_type": "dcf_standard",
                "financial_reports": [],
                "status": "pending",
            }
        )


@pytest.mark.asyncio
async def test_repository_loads_report_bundle_and_discards_invalid_signals() -> None:
    class ArtifactPort:
        async def load_json(
            self, artifact_id: object, *, context: str | None = None
        ) -> JSONObject | None:
            assert artifact_id == "artifact-1"
            return {
                "financial_reports": [
                    {"industry_type": "General", "base": {"fiscal_year": None}}
                ],
                "forward_signals": [
                    {
                        "signal_id": "growth-1",
                        "source_type": "SEC_XBRL",
                        "metric": "revenue_growth",
                        "direction": "up",
                        "value": 0.12,
                        "unit": "ratio",
                        "confidence": 0.8,
                        "as_of": "2026-01-01",
                        "evidence": [],
                    },
                    {"signal_id": "invalid"},
                ],
            }

    repository = FundamentalArtifactRepository(
        financial_reports_port=cast(TypedArtifactPort, ArtifactPort())
    )

    bundle = await repository.load_financial_reports_bundle("artifact-1")

    assert bundle is not None
    reports, signals = bundle
    assert reports == [{"industry_type": "General", "base": {"fiscal_year": None}}]
    assert signals is not None
    assert [signal.signal_id for signal in signals] == ["growth-1"]
