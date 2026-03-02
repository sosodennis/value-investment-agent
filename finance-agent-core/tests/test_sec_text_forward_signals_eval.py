from __future__ import annotations

import json
import statistics
import time
from dataclasses import dataclass
from pathlib import Path

from src.agents.fundamental.infrastructure.sec_xbrl.forward_signals_text import (
    extract_forward_signals_from_sec_text,
)
from src.agents.fundamental.infrastructure.sec_xbrl.text_record import FilingTextRecord


@dataclass(frozen=True)
class _ExpectedSignal:
    source_type: str
    metric: str
    direction: str


@dataclass(frozen=True)
class _EvalCase:
    case_id: str
    ticker: str
    records: list[FilingTextRecord]
    expected_signals: list[_ExpectedSignal]


@dataclass(frozen=True)
class _Score:
    true_positive: int
    false_positive: int
    false_negative: int

    @property
    def precision(self) -> float:
        denominator = self.true_positive + self.false_positive
        if denominator == 0:
            return 1.0
        return self.true_positive / denominator

    @property
    def recall(self) -> float:
        denominator = self.true_positive + self.false_negative
        if denominator == 0:
            return 1.0
        return self.true_positive / denominator


def _fixture_path() -> Path:
    return Path(__file__).parent / "fixtures" / "sec_forward_signals_eval_cases.json"


def _load_eval_cases() -> list[_EvalCase]:
    payload = json.loads(_fixture_path().read_text(encoding="utf-8"))
    cases: list[_EvalCase] = []
    for raw_case in payload:
        records = [
            FilingTextRecord(
                form=str(raw_record["form"]),
                source_type=str(raw_record["source_type"]),
                text=str(raw_record["text"]),
                period=str(raw_record["period"]),
                filing_date=str(raw_record["filing_date"]),
                accession_number=str(raw_record["accession_number"]),
                cik=str(raw_record["cik"]),
            )
            for raw_record in raw_case.get("records", [])
        ]
        expected_signals = [
            _ExpectedSignal(
                source_type=str(raw_expected["source_type"]),
                metric=str(raw_expected["metric"]),
                direction=str(raw_expected["direction"]),
            )
            for raw_expected in raw_case.get("expected_signals", [])
        ]
        cases.append(
            _EvalCase(
                case_id=str(raw_case["case_id"]),
                ticker=str(raw_case["ticker"]),
                records=records,
                expected_signals=expected_signals,
            )
        )
    return cases


def _signal_triplets(signals: list[dict[str, object]]) -> set[tuple[str, str, str]]:
    triplets: set[tuple[str, str, str]] = set()
    for signal in signals:
        source_type = signal.get("source_type")
        metric = signal.get("metric")
        direction = signal.get("direction")
        if not isinstance(source_type, str):
            continue
        if not isinstance(metric, str):
            continue
        if not isinstance(direction, str):
            continue
        triplets.add((source_type, metric, direction))
    return triplets


def _run_case(case: _EvalCase) -> list[dict[str, object]]:
    return extract_forward_signals_from_sec_text(
        ticker=case.ticker,
        fetch_records_fn=lambda _ticker, _limit: case.records,
    )


def _score_cases(cases: list[_EvalCase]) -> _Score:
    true_positive = 0
    false_positive = 0
    false_negative = 0
    for case in cases:
        predicted = _signal_triplets(_run_case(case))
        expected = {
            (item.source_type, item.metric, item.direction)
            for item in case.expected_signals
        }
        true_positive += len(predicted & expected)
        false_positive += len(predicted - expected)
        false_negative += len(expected - predicted)
    return _Score(
        true_positive=true_positive,
        false_positive=false_positive,
        false_negative=false_negative,
    )


def test_sec_text_forward_signals_fixed_eval_precision_recall() -> None:
    cases = _load_eval_cases()
    score = _score_cases(cases)

    assert score.precision >= 0.85
    assert score.recall >= 0.85

    for case in cases:
        signals = _run_case(case)
        for signal in signals:
            evidence = signal.get("evidence")
            assert isinstance(evidence, list) and evidence
            for item in evidence:
                assert isinstance(item, dict)
                source_url = item.get("source_url")
                assert isinstance(source_url, str) and source_url.startswith(
                    "https://www.sec.gov/"
                )
                accession_number = item.get("accession_number")
                if isinstance(accession_number, str) and accession_number:
                    assert source_url.endswith("-index.html")


def test_sec_text_forward_signals_fixed_eval_latency_budget() -> None:
    cases = _load_eval_cases()

    # Warmup avoids one-time model initialization cost in the measured runs.
    for case in cases:
        _run_case(case)

    timings_ms: list[float] = []
    for _ in range(5):
        start = time.perf_counter()
        for case in cases:
            _run_case(case)
        timings_ms.append((time.perf_counter() - start) * 1000.0)

    p50_ms = statistics.median(timings_ms)
    per_case_p50_ms = p50_ms / max(1, len(cases))
    assert per_case_p50_ms < 900.0
