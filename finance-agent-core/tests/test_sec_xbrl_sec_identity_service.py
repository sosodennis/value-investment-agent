from __future__ import annotations

from src.agents.fundamental.infrastructure.sec_xbrl import (
    sec_identity_service as service,
)


def test_ensure_sec_identity_configures_http_timeout_and_identity_once(
    monkeypatch,
) -> None:
    configure_calls: list[float] = []
    identity_calls: list[str] = []

    monkeypatch.delenv("SEC_HTTP_TIMEOUT_SECONDS", raising=False)
    monkeypatch.setattr(service, "_SEC_HTTP_CONFIGURED", False)
    monkeypatch.setattr(service, "_SEC_IDENTITY_CONFIGURED", False)
    monkeypatch.setattr(
        service, "configure_http", lambda *, timeout: configure_calls.append(timeout)
    )
    monkeypatch.setattr(
        service, "set_identity", lambda value: identity_calls.append(value)
    )

    service.ensure_sec_identity()
    service.ensure_sec_identity()

    assert configure_calls == [45.0]
    assert identity_calls == ["ValueInvestmentAgent research@example.com"]


def test_ensure_sec_identity_uses_env_timeout_with_minimum(monkeypatch) -> None:
    configure_calls: list[float] = []
    identity_calls: list[str] = []

    monkeypatch.setenv("SEC_HTTP_TIMEOUT_SECONDS", "1")
    monkeypatch.setattr(service, "_SEC_HTTP_CONFIGURED", False)
    monkeypatch.setattr(service, "_SEC_IDENTITY_CONFIGURED", False)
    monkeypatch.setattr(
        service, "configure_http", lambda *, timeout: configure_calls.append(timeout)
    )
    monkeypatch.setattr(
        service, "set_identity", lambda value: identity_calls.append(value)
    )

    service.ensure_sec_identity()

    assert configure_calls == [5.0]
    assert identity_calls == ["ValueInvestmentAgent research@example.com"]
