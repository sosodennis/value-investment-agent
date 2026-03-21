from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd
import pytest

from src.agents.technical.subdomains.decision_observability import (
    SqlAlchemyTechnicalDecisionObservabilityRepository,
    build_outcome_labeling_request,
    build_prediction_event_record,
    compute_outcome_label,
    filter_matured_events,
    resolve_horizon,
)
from src.infrastructure.models import TechnicalOutcomePath


def _build_event(
    *,
    event_id: str = "event-1",
    direction: str = "BULLISH_EXTENSION",
    horizon: str = "5d",
    event_time: datetime | None = None,
) -> object:
    record = build_prediction_event_record(
        ticker="AAPL",
        technical_context={"target_horizon": horizon, "confidence_calibrated": 0.7},
        full_report_payload={
            "schema_version": "2.0",
            "direction": direction,
            "artifact_refs": {"feature_pack_id": "feature-1"},
            "evidence_bundle": {"primary_timeframe": "1d"},
        },
        report_artifact_id="report-1",
        run_type="workflow",
    )
    return type(record)(
        event_id=event_id,
        agent_source=record.agent_source,
        event_time=event_time or datetime(2026, 3, 10, tzinfo=UTC).replace(tzinfo=None),
        ticker=record.ticker,
        timeframe=record.timeframe,
        horizon=record.horizon,
        direction=record.direction,
        raw_score=record.raw_score,
        confidence=record.confidence,
        reliability_level=record.reliability_level,
        logic_version=record.logic_version,
        feature_contract_version=record.feature_contract_version,
        run_type=record.run_type,
        full_report_artifact_id=record.full_report_artifact_id,
        source_artifact_refs=record.source_artifact_refs,
        context_payload=record.context_payload,
    )


def test_resolve_horizon_maps_supported_values() -> None:
    assert resolve_horizon("1d").delta.days == 1
    assert resolve_horizon("5d").delta.days == 5
    assert resolve_horizon("20d").delta.days == 20


def test_filter_matured_events_only_returns_due_requests() -> None:
    matured_event = _build_event(event_time=datetime(2026, 3, 10))
    not_due_event = _build_event(event_id="event-2", event_time=datetime(2026, 3, 20))

    requests = filter_matured_events(
        events=[matured_event, not_due_event],
        as_of_time=datetime(2026, 3, 16),
    )

    assert [request.event.event_id for request in requests] == ["event-1"]


def test_compute_outcome_label_builds_bullish_metrics() -> None:
    event = _build_event(
        direction="BULLISH_EXTENSION", event_time=datetime(2026, 3, 10)
    )
    request = build_outcome_labeling_request(
        event=event,
        as_of_time=datetime(2026, 3, 20),
    )
    frame = pd.DataFrame(
        {
            "open": [100.0, 101.0, 103.0],
            "high": [101.0, 106.0, 108.0],
            "low": [99.0, 100.0, 102.0],
            "close": [100.0, 105.0, 107.0],
        },
        index=pd.to_datetime(["2026-03-10", "2026-03-12", "2026-03-15"], utc=True),
    )

    result = compute_outcome_label(request=request, price_frame=frame)

    assert result.outcome.event_id == event.event_id
    assert result.outcome.forward_return == pytest.approx(0.07)
    assert result.outcome.mfe == pytest.approx(0.08)
    assert result.outcome.mae == pytest.approx(-0.01)
    assert result.outcome.realized_volatility is not None
    assert result.source_row_count == 3


def test_compute_outcome_label_builds_bearish_metrics() -> None:
    event = _build_event(
        direction="BEARISH_BREAKDOWN", event_time=datetime(2026, 3, 10)
    )
    request = build_outcome_labeling_request(
        event=event,
        as_of_time=datetime(2026, 3, 20),
    )
    frame = pd.DataFrame(
        {
            "open": [100.0, 99.0, 96.0],
            "high": [101.0, 100.0, 97.0],
            "low": [98.0, 94.0, 92.0],
            "close": [100.0, 95.0, 93.0],
        },
        index=pd.to_datetime(["2026-03-10", "2026-03-12", "2026-03-15"], utc=True),
    )

    result = compute_outcome_label(request=request, price_frame=frame)

    assert result.outcome.forward_return == pytest.approx(0.07)
    assert result.outcome.mfe == pytest.approx(0.08)
    assert result.outcome.mae == pytest.approx(-0.01)


@pytest.mark.asyncio
async def test_repository_fetch_unlabeled_prediction_events_returns_unresolved_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    due_event = _build_event(event_time=datetime(2026, 3, 10))
    later_event = _build_event(event_id="event-2", event_time=datetime(2026, 3, 19))

    class _ScalarResult:
        def all(self) -> list[object]:
            return [due_event, later_event]

    class _ExecuteResult:
        def scalars(self) -> _ScalarResult:
            return _ScalarResult()

    class _FakeSession:
        async def execute(self, _query: object) -> _ExecuteResult:
            return _ExecuteResult()

    class _FakeSessionContext:
        async def __aenter__(self) -> _FakeSession:
            return _FakeSession()

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

    monkeypatch.setattr(
        "src.agents.technical.subdomains.decision_observability.infrastructure.repository.AsyncSessionLocal",
        lambda: _FakeSessionContext(),
    )

    repository = SqlAlchemyTechnicalDecisionObservabilityRepository()
    events = await repository.fetch_unlabeled_prediction_events(
        labeling_method_version="technical_outcome_labeling.v1",
        limit=10,
    )

    assert [event.event_id for event in events] == ["event-1", "event-2"]


@pytest.mark.asyncio
async def test_repository_append_outcome_path_if_missing_returns_false_when_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    event = _build_event()
    request = build_outcome_labeling_request(
        event=event,
        as_of_time=datetime(2026, 3, 20),
    )
    frame = pd.DataFrame(
        {"close": [100.0, 101.0], "high": [100.0, 101.0], "low": [100.0, 99.0]},
        index=pd.to_datetime(["2026-03-10", "2026-03-12"], utc=True),
    )
    outcome = compute_outcome_label(request=request, price_frame=frame).outcome

    class _ExistingResult:
        def scalar_one_or_none(self) -> str:
            return "existing"

    class _FakeSession:
        def __init__(self) -> None:
            self.added: list[object] = []

        async def execute(self, _query: object) -> _ExistingResult:
            return _ExistingResult()

        def add(self, obj: object) -> None:
            self.added.append(obj)

        async def commit(self) -> None:
            raise AssertionError("commit should not run when an outcome already exists")

    class _FakeSessionContext:
        def __init__(self, session: _FakeSession) -> None:
            self._session = session

        async def __aenter__(self) -> _FakeSession:
            return self._session

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

    fake_session = _FakeSession()
    monkeypatch.setattr(
        "src.agents.technical.subdomains.decision_observability.infrastructure.repository.AsyncSessionLocal",
        lambda: _FakeSessionContext(fake_session),
    )

    repository = SqlAlchemyTechnicalDecisionObservabilityRepository()
    inserted = await repository.append_outcome_path_if_missing(
        request=request,
        outcome=outcome,
    )

    assert inserted is False
    assert fake_session.added == []


@pytest.mark.asyncio
async def test_repository_append_outcome_path_if_missing_inserts_when_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    event = _build_event()
    request = build_outcome_labeling_request(
        event=event,
        as_of_time=datetime(2026, 3, 20),
    )
    frame = pd.DataFrame(
        {"close": [100.0, 101.0], "high": [100.0, 102.0], "low": [99.0, 98.0]},
        index=pd.to_datetime(["2026-03-10", "2026-03-12"], utc=True),
    )
    outcome = compute_outcome_label(request=request, price_frame=frame).outcome

    class _MissingResult:
        def scalar_one_or_none(self) -> None:
            return None

    class _FakeSession:
        def __init__(self) -> None:
            self.added: list[object] = []
            self.committed = False

        async def execute(self, _query: object) -> _MissingResult:
            return _MissingResult()

        def add(self, obj: object) -> None:
            self.added.append(obj)

        async def commit(self) -> None:
            self.committed = True

    class _FakeSessionContext:
        def __init__(self, session: _FakeSession) -> None:
            self._session = session

        async def __aenter__(self) -> _FakeSession:
            return self._session

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

    fake_session = _FakeSession()
    monkeypatch.setattr(
        "src.agents.technical.subdomains.decision_observability.infrastructure.repository.AsyncSessionLocal",
        lambda: _FakeSessionContext(fake_session),
    )

    repository = SqlAlchemyTechnicalDecisionObservabilityRepository()
    inserted = await repository.append_outcome_path_if_missing(
        request=request,
        outcome=outcome,
    )

    assert inserted is True
    assert fake_session.committed is True
    assert len(fake_session.added) == 1
    assert isinstance(fake_session.added[0], TechnicalOutcomePath)
    assert fake_session.added[0].event_id == event.event_id
