# ruff: noqa: E402

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.agents.fundamental.data.clients.sec_xbrl import (
    extract_forward_signals_from_sec_text,
)

DEFAULT_FIXTURE_PATH = (
    PROJECT_ROOT / "tests" / "fixtures" / "sec_forward_signals_eval_cases.json"
)


@dataclass(frozen=True)
class ExpectedSignal:
    source_type: str
    metric: str
    direction: str


@dataclass(frozen=True)
class EvalCase:
    case_id: str
    ticker: str
    records: list[BenchmarkFilingRecord]
    expected_signals: list[ExpectedSignal]


@dataclass(frozen=True)
class BenchmarkFilingRecord:
    form: str
    source_type: str
    text: str
    period: str | None = None
    accession_number: str | None = None
    filing_date: str | None = None
    cik: str | None = None
    focus_text: str | None = None
    focus_strategy: str | None = None


@dataclass(frozen=True)
class Score:
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


def _load_eval_cases(path: Path) -> list[EvalCase]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    cases: list[EvalCase] = []
    for raw_case in payload:
        records = [
            BenchmarkFilingRecord(
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
            ExpectedSignal(
                source_type=str(raw_expected["source_type"]),
                metric=str(raw_expected["metric"]),
                direction=str(raw_expected["direction"]),
            )
            for raw_expected in raw_case.get("expected_signals", [])
        ]
        cases.append(
            EvalCase(
                case_id=str(raw_case["case_id"]),
                ticker=str(raw_case["ticker"]),
                records=records,
                expected_signals=expected_signals,
            )
        )
    return cases


def _run_case(case: EvalCase) -> list[dict[str, object]]:
    return extract_forward_signals_from_sec_text(
        ticker=case.ticker,
        fetch_records_fn=lambda _ticker, _limit: case.records,
    )


def _score_cases(cases: list[EvalCase]) -> Score:
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
    return Score(
        true_positive=true_positive,
        false_positive=false_positive,
        false_negative=false_negative,
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Benchmark SEC text forward-signal extraction on fixed eval cases."
    )
    parser.add_argument(
        "--fixture",
        type=Path,
        default=DEFAULT_FIXTURE_PATH,
        help=f"Path to eval fixture JSON. Default: {DEFAULT_FIXTURE_PATH}",
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=8,
        help="Number of benchmark iterations after warmup.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional path to write benchmark report JSON.",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    fixture_path = Path(args.fixture).resolve()
    cases = _load_eval_cases(fixture_path)
    if not cases:
        raise ValueError(f"No eval cases found in fixture: {fixture_path}")

    for case in cases:
        _run_case(case)

    duration_ms: list[float] = []
    signal_count_samples: list[int] = []
    for _ in range(max(1, args.iterations)):
        start = time.perf_counter()
        total_signals = 0
        for case in cases:
            total_signals += len(_run_case(case))
        duration_ms.append((time.perf_counter() - start) * 1000.0)
        signal_count_samples.append(total_signals)

    score = _score_cases(cases)
    p50_ms = statistics.median(duration_ms)
    p95_ms = sorted(duration_ms)[int(0.95 * (len(duration_ms) - 1))]
    mean_ms = statistics.mean(duration_ms)

    report = {
        "fixture_path": str(fixture_path),
        "cases": len(cases),
        "iterations": max(1, args.iterations),
        "precision": round(score.precision, 4),
        "recall": round(score.recall, 4),
        "true_positive": score.true_positive,
        "false_positive": score.false_positive,
        "false_negative": score.false_negative,
        "latency_p50_ms": round(p50_ms, 3),
        "latency_p95_ms": round(p95_ms, 3),
        "latency_mean_ms": round(mean_ms, 3),
        "latency_p50_per_case_ms": round(p50_ms / len(cases), 3),
        "signals_per_run_median": int(statistics.median(signal_count_samples)),
    }

    print(json.dumps(report, indent=2))
    if args.output is not None:
        output_path = Path(args.output).resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(report, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
