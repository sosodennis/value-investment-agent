from typing import Literal

from pydantic import BaseModel, Field

from .nodes.fundamental_analysis.extraction import IntentExtraction
from .nodes.fundamental_analysis.structures import TickerCandidate


class HumanTickerSelection(BaseModel):
    """Payload for ticker selection interrupt."""

    type: Literal["ticker_selection"] = "ticker_selection"
    candidates: list[TickerCandidate] = Field(default_factory=list)
    intent: IntentExtraction | None = None
    reason: str = "Multiple tickers found or ambiguity detected."

    def to_ui_payload(self) -> dict:
        """Generates a schema-driven UI payload for RJSF."""
        # Create enum for ticker selection
        ticker_options = [c.symbol for c in self.candidates]
        ticker_titles = [
            f"{c.symbol} - {c.name} ({(c.confidence*100):.0f}% match)"
            for c in self.candidates
        ]

        return {
            "type": self.type,
            "title": "Ticker Resolution",
            "description": self.reason,
            "data": {},
            "schema": {
                "title": "Select Correct Ticker",
                "type": "object",
                "properties": {
                    "selected_symbol": {
                        "type": "string",
                        "title": "Target Company",
                        "enum": ticker_options,
                        "enumNames": ticker_titles,
                    }
                },
                "required": ["selected_symbol"],
            },
            "ui_schema": {"selected_symbol": {"ui:widget": "radio"}},
        }


# Composite type for all possible interrupts
InterruptValue = HumanTickerSelection
