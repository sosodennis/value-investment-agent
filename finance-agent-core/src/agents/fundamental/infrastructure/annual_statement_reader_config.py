"""Explicit deployment selectors for published annual statement readers."""

from __future__ import annotations

import os

from pydantic import TypeAdapter

from src.agents.fundamental.application.annual_statement_reader_contracts import (
    AnnualStatementReaderBinding,
)


def load_annual_statement_reader_bindings() -> tuple[AnnualStatementReaderBinding, ...]:
    raw = os.getenv("FUNDAMENTAL_ANNUAL_STATEMENT_READERS", "[]")
    bindings = TypeAdapter(tuple[AnnualStatementReaderBinding, ...]).validate_json(raw)
    if len({binding.issuer_id for binding in bindings}) != len(bindings):
        raise ValueError("Annual statement reader issuer selectors must be unique")
    return bindings
