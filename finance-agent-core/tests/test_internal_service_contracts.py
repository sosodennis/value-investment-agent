from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from src.shared.internal_services import (
    INTERNAL_CONTRACT_VERSION,
    InternalAuthenticationError,
    InternalContextValidationError,
    InternalError,
    InternalErrorResponse,
    InternalPrincipal,
    InternalReadiness,
    InternalRequestContext,
    ReadinessStatus,
    authenticate_internal_request,
)


def _context() -> dict[str, object]:
    return {
        "principal": {"subject_id": "user-123"},
        "correlation_id": "correlation-123",
        "contract_version": INTERNAL_CONTRACT_VERSION,
        "deadline_at": "2026-10-23T18:30:00Z",
    }


def test_context_normalizes_aware_deadline_to_utc() -> None:
    context = InternalRequestContext.model_validate(
        {
            **_context(),
            "deadline_at": "2026-10-23T10:30:00-08:00",
        }
    )

    assert context.deadline_at == datetime(2026, 10, 23, 18, 30, tzinfo=timezone.utc)
    assert context.principal == InternalPrincipal(subject_id="user-123")


def test_context_rejects_naive_deadline_and_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        InternalRequestContext.model_validate(
            {**_context(), "deadline_at": "2026-10-23T18:30:00"}
        )
    with pytest.raises(ValidationError):
        InternalRequestContext.model_validate(
            {**_context(), "deadline_at": 1_798_091_400}
        )
    with pytest.raises(ValidationError):
        InternalRequestContext.model_validate({**_context(), "user_id": "user-123"})
    with pytest.raises(ValidationError):
        InternalRequestContext.model_validate(
            {
                key: value
                for key, value in _context().items()
                if key != "contract_version"
            }
        )


@pytest.mark.parametrize(
    ("authorization", "expected_token", "code"),
    [
        (None, "service-secret", "internal_auth_missing"),
        ("Basic service-secret", "service-secret", "internal_auth_missing"),
        ("Bearer wrong", "service-secret", "internal_auth_invalid"),
        ("Bearer service-secret", None, "internal_auth_unconfigured"),
    ],
)
def test_authentication_rejects_missing_invalid_or_unconfigured_credentials(
    authorization: str | None,
    expected_token: str | None,
    code: str,
) -> None:
    with pytest.raises(InternalAuthenticationError) as failure:
        authenticate_internal_request(
            authorization,
            expected_token=expected_token,
            raw_context=_context(),
        )

    assert failure.value.code == code
    assert "service-secret" not in str(failure.value)


def test_authentication_rejects_malformed_context_after_validating_caller() -> None:
    with pytest.raises(InternalContextValidationError):
        authenticate_internal_request(
            "Bearer service-secret",
            expected_token="service-secret",
            raw_context={**_context(), "principal": {"user_id": "user-123"}},
        )


def test_authentication_returns_typed_context_and_excludes_secrets() -> None:
    context = authenticate_internal_request(
        "Bearer service-secret",
        expected_token="service-secret",
        raw_context=_context(),
    )

    assert context.principal.subject_id == "user-123"
    assert "service-secret" not in context.model_dump_json()
    assert "cookie" not in context.model_dump_json().lower()


def test_error_and_readiness_envelopes_are_versioned_and_strict() -> None:
    error = InternalErrorResponse(
        correlation_id="correlation-123",
        contract_version=INTERNAL_CONTRACT_VERSION,
        error=InternalError(
            code="unavailable",
            message="service is unavailable",
            retryable=True,
            retry_after_ms=250,
        ),
    )
    readiness = InternalReadiness(
        status=ReadinessStatus.READY,
        contract_version=INTERNAL_CONTRACT_VERSION,
    )

    assert error.contract_version == INTERNAL_CONTRACT_VERSION
    assert error.error.retry_after_ms == 250
    assert readiness.model_dump() == {
        "status": "ready",
        "contract_version": INTERNAL_CONTRACT_VERSION,
    }
