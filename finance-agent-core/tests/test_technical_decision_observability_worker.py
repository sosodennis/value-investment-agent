from __future__ import annotations

import importlib.util
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pytest

from src.agents.technical.subdomains.decision_observability import (
    TechnicalDecisionObservabilityRuntimeService,
    TechnicalOutcomeLabelingWorkerService,
    build_prediction_event_record,
)
from src.agents.technical.subdomains.market_data.application.ports import (
    MarketDataCacheMetadata,
    MarketDataOhlcvFetchResult,
    MarketDataProviderFailure,
)


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


@dataclass
class _FakeRepository:
    events: list[object]
    insert_outcomes: list[object] = field(default_factory=list)
    return_inserted: bool = True

    async def append_prediction_event(self, record: object) -> None:
        raise AssertionError("not used in worker tests")

    async def fetch_unlabeled_prediction_events(
        self,
        *,
        labeling_method_version: str,
        limit: int = 100,
    ) -> list[object]:
        _ = (labeling_method_version, limit)
        return self.events

    async def append_outcome_path_if_missing(
        self, *, request: object, outcome: object
    ) -> bool:
        _ = request
        self.insert_outcomes.append(outcome)
        return self.return_inserted


@dataclass
class _FakeMarketDataReader:
    result: MarketDataOhlcvFetchResult
    calls: list[dict[str, object]] = field(default_factory=list)

    async def fetch_ohlcv(
        self,
        ticker_symbol: str,
        *,
        period: str = "6mo",
        interval: str = "1d",
    ) -> MarketDataOhlcvFetchResult:
        self.calls.append(
            {"ticker_symbol": ticker_symbol, "period": period, "interval": interval}
        )
        return self.result


@pytest.mark.asyncio
async def test_runtime_labels_matured_events_and_inserts_outcomes() -> None:
    event = _build_event(event_time=datetime(2026, 3, 10))
    frame = pd.DataFrame(
        {
            "open": [100.0, 101.0, 103.0],
            "high": [101.0, 106.0, 108.0],
            "low": [99.0, 100.0, 102.0],
            "close": [100.0, 105.0, 107.0],
        },
        index=pd.to_datetime(["2026-03-10", "2026-03-12", "2026-03-15"], utc=True),
    )
    runtime = TechnicalDecisionObservabilityRuntimeService(
        repository=_FakeRepository(events=[event])
    )
    reader = _FakeMarketDataReader(
        result=MarketDataOhlcvFetchResult(
            data=frame,
            cache=MarketDataCacheMetadata(cache_hit=False),
        )
    )

    result = await runtime.label_matured_prediction_events(
        market_data_reader=reader,
        as_of_time=datetime(2026, 3, 20),
    )

    assert result.scanned_event_count == 1
    assert result.matured_event_count == 1
    assert result.inserted_outcome_count == 1
    assert result.skipped_existing_count == 0
    assert result.failed_event_ids == ()
    assert len(runtime.repository.insert_outcomes) == 1
    assert reader.calls == [
        {"ticker_symbol": "AAPL", "period": "6mo", "interval": "1d"}
    ]


@pytest.mark.asyncio
async def test_runtime_skips_unmatured_events() -> None:
    event = _build_event(event_time=datetime(2026, 3, 19))
    runtime = TechnicalDecisionObservabilityRuntimeService(
        repository=_FakeRepository(events=[event])
    )
    reader = _FakeMarketDataReader(
        result=MarketDataOhlcvFetchResult(data=pd.DataFrame())
    )

    result = await runtime.label_matured_prediction_events(
        market_data_reader=reader,
        as_of_time=datetime(2026, 3, 20),
    )

    assert result.scanned_event_count == 1
    assert result.matured_event_count == 0
    assert result.inserted_outcome_count == 0
    assert reader.calls == []


@pytest.mark.asyncio
async def test_runtime_records_provider_failure_without_inserting() -> None:
    event = _build_event(event_time=datetime(2026, 3, 10))
    repository = _FakeRepository(events=[event])
    runtime = TechnicalDecisionObservabilityRuntimeService(repository=repository)
    reader = _FakeMarketDataReader(
        result=MarketDataOhlcvFetchResult(
            data=None,
            failure=MarketDataProviderFailure(
                failure_code="TECHNICAL_OHLCV_FETCH_FAILED",
                reason="provider_down",
            ),
        )
    )

    result = await runtime.label_matured_prediction_events(
        market_data_reader=reader,
        as_of_time=datetime(2026, 3, 20),
    )

    assert result.inserted_outcome_count == 0
    assert result.failed_event_ids == ("event-1",)
    assert result.provider_failures == ("TECHNICAL_OHLCV_FETCH_FAILED",)
    assert repository.insert_outcomes == []


@pytest.mark.asyncio
async def test_runtime_counts_existing_outcomes_as_skipped() -> None:
    event = _build_event(event_time=datetime(2026, 3, 10))
    repository = _FakeRepository(events=[event], return_inserted=False)
    runtime = TechnicalDecisionObservabilityRuntimeService(repository=repository)
    frame = pd.DataFrame(
        {
            "close": [100.0, 101.0, 102.0],
            "high": [100.0, 102.0, 103.0],
            "low": [99.0, 98.0, 97.0],
        },
        index=pd.to_datetime(["2026-03-10", "2026-03-12", "2026-03-15"], utc=True),
    )
    reader = _FakeMarketDataReader(result=MarketDataOhlcvFetchResult(data=frame))

    result = await runtime.label_matured_prediction_events(
        market_data_reader=reader,
        as_of_time=datetime(2026, 3, 20),
    )

    assert result.inserted_outcome_count == 0
    assert result.skipped_existing_count == 1
    assert len(repository.insert_outcomes) == 1


@pytest.mark.asyncio
async def test_worker_service_emits_completion_report() -> None:
    event = _build_event(event_time=datetime(2026, 3, 10))
    repository = _FakeRepository(events=[event])
    runtime = TechnicalDecisionObservabilityRuntimeService(repository=repository)
    frame = pd.DataFrame(
        {
            "close": [100.0, 101.0, 102.0],
            "high": [100.0, 102.0, 103.0],
            "low": [99.0, 98.0, 97.0],
        },
        index=pd.to_datetime(["2026-03-10", "2026-03-12", "2026-03-15"], utc=True),
    )
    worker = TechnicalOutcomeLabelingWorkerService(
        runtime_service=runtime,
        market_data_reader=_FakeMarketDataReader(
            result=MarketDataOhlcvFetchResult(data=frame)
        ),
    )

    result = await worker.run_once(as_of_time=datetime(2026, 3, 20))

    assert result.matured_event_count == 1
    assert result.inserted_outcome_count == 1


@pytest.mark.asyncio
async def test_market_data_reader_uses_labeling_cache_namespace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def _fake_fetch_ohlcv(
        ticker_symbol: str,
        *,
        period: str,
        interval: str,
        cache_base_dir: str | None,
        cache_key_prefix: str,
        max_retries: int,
        retry_delay_seconds: float,
    ) -> MarketDataOhlcvFetchResult:
        captured.update(
            {
                "ticker_symbol": ticker_symbol,
                "period": period,
                "interval": interval,
                "cache_base_dir": cache_base_dir,
                "cache_key_prefix": cache_key_prefix,
                "max_retries": max_retries,
                "retry_delay_seconds": retry_delay_seconds,
            }
        )
        return MarketDataOhlcvFetchResult(data=pd.DataFrame())

    monkeypatch.setattr(
        "src.agents.technical.subdomains.decision_observability.infrastructure.labeling_worker_service.fetch_ohlcv",
        _fake_fetch_ohlcv,
    )

    from src.agents.technical.subdomains.decision_observability import (
        TechnicalOutcomeLabelingMarketDataReader,
    )

    reader = TechnicalOutcomeLabelingMarketDataReader(
        cache_base_dir="/tmp/technical-labeling-cache",
        cache_key_prefix="decision_labeling",
        max_retries=3,
        retry_delay_seconds=1.25,
    )
    await reader.fetch_ohlcv("AAPL", period="6mo", interval="1d")

    assert captured == {
        "ticker_symbol": "AAPL",
        "period": "6mo",
        "interval": "1d",
        "cache_base_dir": "/tmp/technical-labeling-cache",
        "cache_key_prefix": "decision_labeling",
        "max_retries": 3,
        "retry_delay_seconds": 1.25,
    }


def _load_labeling_script_module():
    project_root = Path(__file__).resolve().parents[1]
    script_path = project_root / "scripts" / "run_technical_outcome_labeling.py"
    spec = importlib.util.spec_from_file_location(
        "run_technical_outcome_labeling",
        script_path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to load run_technical_outcome_labeling.py module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_run_technical_outcome_labeling_script_logs_batch_summary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_labeling_script_module()

    @dataclass
    class _FakeWorker:
        calls: list[dict[str, object]] = field(default_factory=list)

        async def run_once(
            self,
            *,
            as_of_time: datetime | None = None,
            limit: int = 100,
            labeling_method_version: str = "technical_outcome_labeling.v1",
        ) -> object:
            self.calls.append(
                {
                    "as_of_time": as_of_time,
                    "limit": limit,
                    "labeling_method_version": labeling_method_version,
                }
            )
            return type(
                "_BatchResult",
                (),
                {
                    "scanned_event_count": 7,
                    "matured_event_count": 5,
                    "inserted_outcome_count": 4,
                    "skipped_existing_count": 1,
                    "failed_event_ids": ("event-9",),
                    "provider_failures": ("TECHNICAL_OHLCV_FETCH_FAILED",),
                },
            )()

    fake_worker = _FakeWorker()
    logged: list[dict[str, object]] = []
    monkeypatch.setattr(
        module,
        "build_default_technical_outcome_labeling_worker_service",
        lambda: fake_worker,
    )
    monkeypatch.setattr(
        module,
        "log_event",
        lambda logger,
        *,
        event,
        message,
        fields,
        level=None,
        error_code=None: logged.append(
            {
                "logger": logger,
                "event": event,
                "message": message,
                "fields": fields,
                "level": level,
                "error_code": error_code,
            }
        ),
    )

    exit_code = module.main(
        [
            "--as-of-time",
            "2026-03-20T18:30:00",
            "--limit",
            "25",
            "--labeling-method-version",
            "technical_outcome_labeling.v2",
        ]
    )

    assert exit_code == 0
    assert fake_worker.calls == [
        {
            "as_of_time": datetime(2026, 3, 20, 18, 30),
            "limit": 25,
            "labeling_method_version": "technical_outcome_labeling.v2",
        }
    ]
    assert len(logged) == 1
    assert logged[0]["event"] == "technical_outcome_labeling_script_completed"
    assert logged[0]["message"] == "technical outcome labeling script completed"
    assert logged[0]["fields"] == {
        "status": "done",
        "scanned_event_count": 7,
        "matured_event_count": 5,
        "inserted_outcome_count": 4,
        "skipped_existing_count": 1,
        "failed_event_ids": ["event-9"],
        "provider_failures": ["TECHNICAL_OHLCV_FETCH_FAILED"],
    }
