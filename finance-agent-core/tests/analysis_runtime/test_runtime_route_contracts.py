import pytest
from pydantic import ValidationError

from src.analysis_runtime.interface.routes import ResumeRequest, RunRequest


def test_start_request_rejects_unbound_resume_payload() -> None:
    with pytest.raises(ValidationError):
        RunRequest.model_validate(
            {"message": "Apple", "resume_payload": {"selected_symbol": "AAPL"}}
        )


def test_resume_request_requires_activity_and_interaction_identity() -> None:
    with pytest.raises(ValidationError):
        ResumeRequest.model_validate(
            {
                "response": {
                    "type": "ticker_selection",
                    "selected_symbol": "AAPL",
                }
            }
        )

    request = ResumeRequest.model_validate(
        {
            "activity_id": "intent.clarifying",
            "interaction_id": "interaction-1",
            "response": {
                "type": "ticker_selection",
                "selected_symbol": "AAPL",
            },
        }
    )
    assert request.activity_id == "intent.clarifying"
    assert request.interaction_id == "interaction-1"
