"""Load the deployment's pinned source-use catalog at composition boundaries."""

import os
from pathlib import Path

from .free_source_policy import free_market_source_policy
from .source_admission import SourceUsePolicyV1


def load_runtime_source_use_policy() -> SourceUsePolicyV1:
    """Replace the built-in catalog only with an explicit, exact deployment pin."""
    file_value = os.getenv("FUNDAMENTAL_SOURCE_USE_POLICY_FILE")
    expected_digest = os.getenv("FUNDAMENTAL_SOURCE_USE_POLICY_DIGEST")
    if file_value is None and expected_digest is None:
        return free_market_source_policy()
    if not file_value or not expected_digest:
        raise ValueError("source-use policy requires both deployment file and digest")
    try:
        policy = SourceUsePolicyV1.model_validate_json(Path(file_value).read_bytes())
    except (OSError, ValueError):
        raise ValueError(
            "source-use deployment policy is unreadable or invalid"
        ) from None
    if policy.digest != expected_digest:
        raise ValueError("source-use deployment policy digest differs")
    return policy
