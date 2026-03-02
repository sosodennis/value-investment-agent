from __future__ import annotations

import logging
from typing import Protocol

from src.shared.kernel.tools.logger import log_event

from .extractor import SearchConfig


class MappingRegistryProtocol(Protocol):
    def resolve(self, field_key: str, *, industry: str | None, issuer: str | None): ...


def resolve_configs(
    *,
    field_key: str,
    industry: str | None,
    issuer: str | None,
    registry: MappingRegistryProtocol,
    logger_: logging.Logger,
) -> list[SearchConfig]:
    resolved = registry.resolve(field_key, industry=industry, issuer=issuer)
    if not resolved:
        log_event(
            logger_,
            event="fundamental_xbrl_mapping_missing",
            message="xbrl mapping missing for field",
            level=logging.DEBUG,
            fields={
                "field_key": field_key,
                "industry": industry,
                "issuer": issuer,
            },
        )
        return []

    log_event(
        logger_,
        event="fundamental_xbrl_mapping_resolved",
        message="xbrl mapping source resolved",
        level=logging.DEBUG,
        fields={
            "field_key": field_key,
            "industry": industry,
            "issuer": issuer,
            "source": resolved.source,
            "configs_count": len(resolved.spec.configs),
        },
    )
    return resolved.spec.configs
