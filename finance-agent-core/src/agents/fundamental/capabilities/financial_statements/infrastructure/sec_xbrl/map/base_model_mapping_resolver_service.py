from __future__ import annotations

import logging
from typing import Protocol

from src.shared.kernel.tools.logger import log_event

from ..extract.extractor import SearchConfig
from .field_resolution_service import enrich_configs_with_resolution_metadata


class MappingRegistryProtocol(Protocol):
    def resolve(self, field_key: str, *, industry: str | None, issuer: str | None): ...

    def resolve_with_reason(
        self, field_key: str, *, industry: str | None, issuer: str | None
    ): ...


def resolve_configs(
    *,
    field_key: str,
    industry: str | None,
    issuer: str | None,
    registry: MappingRegistryProtocol,
    logger_: logging.Logger,
) -> list[SearchConfig]:
    resolved = registry.resolve(
        field_key,
        industry=industry,
        issuer=issuer,
    )
    unresolved_reason: str | None = None
    if resolved is None:
        resolution = registry.resolve_with_reason(
            field_key,
            industry=industry,
            issuer=issuer,
        )
        resolved = resolution.resolved
        unresolved_reason = resolution.unresolved_reason

    if resolved is None:
        log_event(
            logger_,
            event="fundamental_xbrl_mapping_missing",
            message="xbrl mapping missing for field",
            level=logging.DEBUG,
            fields={
                "field_key": field_key,
                "industry": industry,
                "issuer": issuer,
                "unresolved_reason": unresolved_reason,
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
            "anchor_source": resolved.anchor_source,
            "anchor_rule_count": resolved.anchor_rule_count,
            "configs_count": len(resolved.spec.configs),
        },
    )
    return enrich_configs_with_resolution_metadata(
        configs=resolved.spec.configs,
        source=resolved.source,
        anchor_source=resolved.anchor_source,
        anchor_rule_count=resolved.anchor_rule_count,
    )
