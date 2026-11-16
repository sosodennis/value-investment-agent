"""The opt-in local catalog uses the existing pinned deployment boundary."""

from contextlib import AbstractContextManager
from datetime import UTC, datetime
from importlib.resources import files
import json
from pathlib import Path

import pytest

from fundamental_service.free_source_policy import free_market_source_policy
from fundamental_service.quote_capture import (
    QuoteHttpResponsePort,
    quote_preparation_source_adapter,
)
from fundamental_service.snapshots import SnapshotError
from fundamental_service.source_use_deployment import load_runtime_source_use_policy
from fundamental_service.source_admission import SourceUsePolicyV1, check_source_use
from fundamental_service.source_evidence import RetainedSourceV1, SourceArtifactV1
from fundamental_service.yahoo_quote_source import (
    YAHOO_CLOSE_PROFILE,
    YAHOO_CLOSE_SOURCE,
    YAHOO_TERMS,
)

RESOURCE = "personal-local-source-use-v1.json"
URI = (
    "https://query2.finance.yahoo.com/v8/finance/chart/MSFT"
    "?period1=1794546000&period2=1794632400&interval=1d&events=div,splits,capitalGains"
)


def configured_policy(monkeypatch: pytest.MonkeyPatch) -> SourceUsePolicyV1:
    root = Path(__file__).resolve().parents[2]
    overlay = json.loads(
        (
            root / "compose/verification/docker-compose.personal-local-sources.json"
        ).read_bytes()
    )
    environment = overlay["services"]["fundamental-service"]["environment"]
    resource = files("fundamental_service").joinpath("resources", RESOURCE)
    assert environment["FUNDAMENTAL_SOURCE_USE_POLICY_FILE"] == (
        f"/app/src/fundamental_service/resources/{RESOURCE}"
    )
    monkeypatch.setenv("FUNDAMENTAL_SOURCE_USE_POLICY_FILE", str(resource))
    monkeypatch.setenv(
        "FUNDAMENTAL_SOURCE_USE_POLICY_DIGEST",
        environment["FUNDAMENTAL_SOURCE_USE_POLICY_DIGEST"],
    )
    return load_runtime_source_use_policy()


def test_opt_in_catalog_preserves_market_rules_and_records_owner_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    policy = configured_policy(monkeypatch)
    base = free_market_source_policy()
    assert all(rule in policy.rules for rule in base.rules)
    extra = tuple(rule for rule in policy.rules if rule not in base.rules)
    assert len(extra) == 1
    rule = extra[0]
    assert (
        rule.provider_id,
        rule.source_id,
        rule.source_version,
        rule.terms_reference,
        rule.metric_id,
        rule.population,
    ) == (
        YAHOO_CLOSE_SOURCE,
        YAHOO_CLOSE_SOURCE,
        YAHOO_CLOSE_PROFILE,
        YAHOO_TERMS,
        "common_share.price",
        "common-share",
    )
    assert rule.permitted_uses == (
        "valuation_preparation",
        "derived_valuation_display",
    )
    assert rule.terms[0].content_scope is not None
    assert rule.terms[0].content_scope.value == "node-content"
    assert "does not assert permission from Yahoo" in rule.basis
    assert "no separate Yahoo authorization" in rule.basis


def test_local_catalog_passes_capture_gate_before_intercepted_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    policy = configured_policy(monkeypatch)
    calls: list[str] = []

    class TransportBoundaryReached(Exception):
        pass

    def stop_before_network(
        *args: object, **kwargs: object
    ) -> AbstractContextManager[QuoteHttpResponsePort]:
        calls.append("transport")
        raise TransportBoundaryReached

    adapter = quote_preparation_source_adapter(
        user_agent="local-policy-check <check@example.invalid>",
        policy=policy,
        api_key_file=None,
        quote_opener=stop_before_network,
    )
    with pytest.raises(TransportBoundaryReached):
        adapter.capture(YAHOO_CLOSE_SOURCE, URI)
    assert calls == ["transport"]

    monkeypatch.delenv("FUNDAMENTAL_SOURCE_USE_POLICY_FILE")
    monkeypatch.delenv("FUNDAMENTAL_SOURCE_USE_POLICY_DIGEST")
    adapter = quote_preparation_source_adapter(
        user_agent="local-policy-check <check@example.invalid>",
        policy=load_runtime_source_use_policy(),
        api_key_file=None,
        quote_opener=stop_before_network,
    )
    with pytest.raises(SnapshotError) as error:
        adapter.capture(YAHOO_CLOSE_SOURCE, URI)
    assert error.value.code == "SOURCE_USE_POLICY_MISSING"
    assert calls == ["transport"]


def test_local_policy_still_refuses_missing_changed_terms_and_redistribution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    policy = configured_policy(monkeypatch)
    captured_at = datetime(2026, 11, 16, tzinfo=UTC)
    artifact = SourceArtifactV1(
        source_id=YAHOO_CLOSE_SOURCE,
        uri=URI,
        source_version=YAHOO_CLOSE_PROFILE,
        terms_reference=YAHOO_TERMS,
        captured_at=captured_at,
        content_sha256="0" * 64,
    )
    changed_terms = RetainedSourceV1(
        source_id="yahoo-finance-terms",
        uri=YAHOO_TERMS,
        source_version="publisher-terms-html-v1",
        terms_reference=YAHOO_TERMS,
        captured_at=captured_at,
        content=b'<section id="node-content">Changed terms</section>',
    )
    for terms, use, expected in (
        ((), "valuation_preparation", ("SOURCE_USE_TERMS_MISSING",)),
        ((changed_terms,), "valuation_preparation", ("SOURCE_USE_TERMS_CHANGED",)),
        (
            (),
            "raw_data_redistribution",
            ("SOURCE_USE_PURPOSE_UNSUPPORTED", "SOURCE_USE_TERMS_MISSING"),
        ),
    ):
        check = check_source_use(
            provider_id=YAHOO_CLOSE_SOURCE,
            metric_id="common_share.price",
            population="common-share",
            artifact=artifact,
            intended_use=use,
            terms=terms,
            policy=policy,
        )
        assert check.issue_codes == expected
