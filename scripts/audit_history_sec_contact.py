"""Read the complete declared SEC contact for offline history research tools."""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from pathlib import Path

from fundamental_service.sec_source import SecRequestPolicy
from validate_compose_inputs import PLACEHOLDER_USER_AGENTS, read_env_file

SEC_USER_AGENT = "FUNDAMENTAL_SEC_USER_AGENT"


def load_sec_user_agent(
    env_files: Sequence[Path], *, environ: Mapping[str, str] | None = None
) -> str:
    """Prefer an explicit process value, then the first file defining the key.

    A selected invalid value fails before network access; another file cannot
    silently replace it. Reading configuration never mutates the environment.
    """
    environment = os.environ if environ is None else environ
    value = environment.get(SEC_USER_AGENT)
    if value is None:
        for path in env_files:
            if not path.is_file():
                continue
            value = read_env_file(path).get(SEC_USER_AGENT)
            if value is not None:
                break
    value = (value or "").strip()
    if value in PLACEHOLDER_USER_AGENTS or "example.com" in value.lower():
        raise ValueError("SEC contact must be configured with a declared contact")
    SecRequestPolicy(user_agent=value)
    return value
