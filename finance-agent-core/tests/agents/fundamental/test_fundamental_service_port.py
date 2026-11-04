import pytest
from pydantic import ValidationError

from src.agents.fundamental.application.fundamental_service_port import (
    FundamentalServiceFailure,
)
from src.agents.fundamental.interface.fundamental_service_contracts import (
    FundamentalServiceResponseV1,
)


def test_client_projection_requires_both_shared_and_service_contract_versions():
    response = FundamentalServiceResponseV1(
        correlation_id="correlation-1",
        contract_version="internal.v1",
        schema_version="fundamental.v1",
        result={"quality_status": "verified", "result_hash": "a" * 64},
    )
    assert response.result["quality_status"] == "verified"

    with pytest.raises(ValidationError):
        FundamentalServiceResponseV1(
            correlation_id="correlation-1",
            contract_version="legacy.v0",
            schema_version="fundamental.v1",
            result={},
        )


def test_client_failure_is_explicitly_retryable_without_local_calculation():
    failure = FundamentalServiceFailure(
        "service_unavailable", "service unavailable", retryable=True
    )
    assert failure.code == "service_unavailable"
    assert failure.retryable is True
