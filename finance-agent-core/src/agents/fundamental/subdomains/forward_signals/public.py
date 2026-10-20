"""Stable forward signal contracts, policies, and application service."""

from .application.extraction_service import extract_forward_signals
from .domain.policies.forward_signal_calibration_service import (
    DEFAULT_FORWARD_SIGNAL_CALIBRATION_CONFIG,
    ForwardSignalCalibrationConfig,
    calibrate_signal_basis_points,
    parse_forward_signal_calibration_config,
)
from .domain.policies.forward_signal_contracts import (
    ForwardSignal,
    ForwardSignalDecision,
    ForwardSignalEvidence,
    ForwardSignalPolicyResult,
    ForwardSignalSourceLocator,
)
from .domain.policies.forward_signal_parser_service import parse_forward_signals
from .domain.policies.forward_signal_policy import apply_forward_signal_policy
from .interface.contracts import (
    ForwardSignalPayload,
)
from .interface.contracts import (
    ForwardSignalSourceLocator as ForwardSignalPayloadSourceLocator,
)
from .interface.serializers import serialize_forward_signals

__all__ = [
    "DEFAULT_FORWARD_SIGNAL_CALIBRATION_CONFIG",
    "ForwardSignal",
    "ForwardSignalCalibrationConfig",
    "ForwardSignalDecision",
    "ForwardSignalEvidence",
    "ForwardSignalPayload",
    "ForwardSignalPayloadSourceLocator",
    "ForwardSignalPolicyResult",
    "ForwardSignalSourceLocator",
    "apply_forward_signal_policy",
    "calibrate_signal_basis_points",
    "extract_forward_signals",
    "parse_forward_signal_calibration_config",
    "parse_forward_signals",
    "serialize_forward_signals",
]
