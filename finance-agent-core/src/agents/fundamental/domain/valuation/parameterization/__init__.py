"""Valuation parameterization boundary.

This package owns parameter build orchestration, shared services, and
model-specific payload builders.
"""

from .contracts import ParamBuildResult
from .orchestrator import build_params

__all__ = ["ParamBuildResult", "build_params"]
