from __future__ import annotations

from dataclasses import asdict
from datetime import datetime

from src.agents.technical.subdomains.calibration import (
    TECHNICAL_DIRECTION_CALIBRATION_METHOD,
    load_technical_direction_calibration_mapping,
)
from src.agents.technical.subdomains.interpretation import (
    INTERPRETATION_GUARDRAIL_VERSION,
)
from src.agents.technical.subdomains.signal_fusion import (
    FUSION_SCORECARD_MODEL_VERSION,
)

from .contracts import TechnicalGovernanceRegistry


def build_technical_governance_registry(
    *, as_of: str | None = None
) -> TechnicalGovernanceRegistry:
    calibration_load_result = load_technical_direction_calibration_mapping()
    config = calibration_load_result.config
    config_payload = {
        "mapping_version": config.mapping_version,
        "timeframe_multiplier": dict(config.timeframe_multiplier),
        "direction_multiplier": dict(config.direction_multiplier),
        "mapping_bins": [list(item) for item in config.mapping_bins],
    }
    return TechnicalGovernanceRegistry(
        schema_version="1.0",
        as_of=as_of or datetime.now().isoformat(),
        fusion_model_version=FUSION_SCORECARD_MODEL_VERSION,
        guardrail_version=INTERPRETATION_GUARDRAIL_VERSION,
        calibration_mapping_version=config.mapping_version,
        calibration_mapping_source=calibration_load_result.mapping_source,
        calibration_mapping_path=calibration_load_result.mapping_path,
        calibration_degraded_reason=calibration_load_result.degraded_reason,
        calibration_method=TECHNICAL_DIRECTION_CALIBRATION_METHOD,
        calibration_config=config_payload,
    )


def registry_to_payload(registry: TechnicalGovernanceRegistry) -> dict[str, object]:
    payload = asdict(registry)
    payload["calibration_config"] = dict(registry.calibration_config)
    return payload


def registry_from_payload(payload: dict[str, object]) -> TechnicalGovernanceRegistry:
    return TechnicalGovernanceRegistry(
        schema_version=str(payload.get("schema_version", "1.0")),
        as_of=str(payload.get("as_of", "")),
        fusion_model_version=str(payload.get("fusion_model_version", "")),
        guardrail_version=str(payload.get("guardrail_version", "")),
        calibration_mapping_version=str(payload.get("calibration_mapping_version", "")),
        calibration_mapping_source=str(payload.get("calibration_mapping_source", "")),
        calibration_mapping_path=payload.get("calibration_mapping_path")
        if isinstance(payload.get("calibration_mapping_path"), str)
        else None,
        calibration_degraded_reason=payload.get("calibration_degraded_reason")
        if isinstance(payload.get("calibration_degraded_reason"), str)
        else None,
        calibration_method=str(payload.get("calibration_method", "")),
        calibration_config=_coerce_config(payload.get("calibration_config")),
    )


def _coerce_config(raw: object) -> dict[str, object]:
    if isinstance(raw, dict):
        return dict(raw)
    return {}


__all__ = [
    "build_technical_governance_registry",
    "registry_to_payload",
    "registry_from_payload",
]
