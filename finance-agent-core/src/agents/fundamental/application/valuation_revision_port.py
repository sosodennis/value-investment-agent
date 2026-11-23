"""Authenticated access to the retained source of one valuation revision."""

from typing import Protocol

from src.agents.fundamental.interface.request_contracts import (
    FundamentalValuationRevisionSourceV1,
)
from src.shared.artifacts.fundamental_contracts import FundamentalValuationReportV1
from src.shared.internal_services import InternalPrincipal


class FundamentalRevisionSourceReaderPort(Protocol):
    async def read_source(
        self,
        source: FundamentalValuationRevisionSourceV1,
        *,
        principal: InternalPrincipal,
        current_thread_id: str,
    ) -> FundamentalValuationReportV1: ...
