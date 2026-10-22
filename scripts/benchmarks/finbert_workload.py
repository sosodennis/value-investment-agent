"""Measure the existing in-process FinBERT workload.

Run this script once per process for a cold-start sample. It intentionally uses
the application's existing singleton and analyzer instead of a service shim.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import platform
import resource
import statistics
import sys
import time
from contextlib import redirect_stdout
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from importlib import import_module
from typing import Protocol, cast


REPOSITORY_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
FINANCE_AGENT_ROOT = os.path.join(REPOSITORY_ROOT, "finance-agent-core")
if FINANCE_AGENT_ROOT not in sys.path:
    sys.path.insert(0, FINANCE_AGENT_ROOT)


TEXTS = (
    "Revenue growth accelerated and operating margins expanded this quarter.",
    "The company reported a loss and weaker demand in the latest quarter.",
    "Management expects stable demand and modest margin improvement next year.",
    "The filing describes a neutral outlook with no material change in guidance.",
)


def _rss_mib() -> float:
    value = float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    # macOS reports bytes. Linux reports KiB.
    if platform.system() == "Darwin":
        return round(value / (1024.0 * 1024.0), 3)
    return round(value / 1024.0, 3)


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(
        len(ordered) - 1, max(0, int(round((percentile / 100) * len(ordered))) - 1)
    )
    return round(ordered[index], 3)


@dataclass(frozen=True)
class CallResult:
    elapsed_ms: float
    ok: bool
    label: str | None
    score: float | None
    error: str | None


class AnalyzerResult(Protocol):
    label: str
    score: float


class Analyzer(Protocol):
    device: str | None
    load_error: str | None

    def is_available(self) -> bool: ...

    def analyze(self, text: str) -> AnalyzerResult | None: ...


class FinBERTModule(Protocol):
    FINBERT_MODEL_NAME: str

    def get_finbert_analyzer(self) -> Analyzer: ...


def _call(analyzer: Analyzer, text: str) -> CallResult:
    started = time.perf_counter()
    try:
        result = analyzer.analyze(text)
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        if result is None:
            return CallResult(round(elapsed_ms, 3), False, None, None, "no_result")
        return CallResult(
            round(elapsed_ms, 3),
            True,
            str(result.label),
            float(result.score),
            None,
        )
    except Exception as exc:  # pragma: no cover - protects the benchmark process
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        return CallResult(round(elapsed_ms, 3), False, None, None, type(exc).__name__)


def _summary(results: list[CallResult]) -> dict[str, object]:
    latencies = [item.elapsed_ms for item in results]
    successes = [item for item in results if item.ok]
    return {
        "requests": len(results),
        "successes": len(successes),
        "errors": len(results) - len(successes),
        "p50_ms": _percentile(latencies, 50),
        "p95_ms": _percentile(latencies, 95),
        "max_ms": round(max(latencies), 3) if latencies else 0.0,
        "mean_ms": round(statistics.fmean(latencies), 3) if latencies else 0.0,
        "labels": sorted({item.label for item in successes if item.label}),
        "scores": [
            round(item.score, 6) for item in successes if item.score is not None
        ],
        "raw": [asdict(item) for item in results],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sequential", type=int, default=8)
    parser.add_argument("--concurrency", type=int, nargs="+", default=[1, 2, 4, 8])
    parser.add_argument("--requests-per-level", type=int, default=8)
    args = parser.parse_args()

    log_sink = io.StringIO()
    with redirect_stdout(log_sink):
        import_started = time.perf_counter()
        module = cast(FinBERTModule, import_module("src.infrastructure.sentiment"))
        provider = import_module(
            "src.infrastructure.sentiment.finbert_sentiment_provider"
        )
        import_ms = (time.perf_counter() - import_started) * 1000.0
        analyzer = module.get_finbert_analyzer()

        load_started = time.perf_counter()
        available = bool(analyzer.is_available())
        load_ms = (time.perf_counter() - load_started) * 1000.0
    output: dict[str, object] = {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "cpu_count": os.cpu_count(),
        "torch_num_threads": None,
        "model": getattr(provider, "FINBERT_MODEL_NAME", None),
        "device": getattr(analyzer, "device", None),
        "available": available,
        "load_error": analyzer.load_error,
        "import_ms": round(import_ms, 3),
        "load_ms": round(load_ms, 3),
        "rss_after_load_mib": _rss_mib(),
        "sequential": None,
        "concurrent": {},
    }
    try:
        import torch

        output["torch_num_threads"] = int(torch.get_num_threads())
    except Exception:
        pass

    if not available:
        print(json.dumps(output, sort_keys=True))
        return

    with redirect_stdout(log_sink):
        sequential_results = [
            _call(analyzer, TEXTS[index % len(TEXTS)])
            for index in range(args.sequential)
        ]
    output["sequential"] = _summary(sequential_results)
    output["rss_after_sequential_mib"] = _rss_mib()

    for concurrency in args.concurrency:
        request_count = max(concurrency, args.requests_per_level)
        started = time.perf_counter()
        results: list[CallResult] = []
        with redirect_stdout(log_sink):
            with ThreadPoolExecutor(max_workers=concurrency) as executor:
                futures = [
                    executor.submit(_call, analyzer, TEXTS[index % len(TEXTS)])
                    for index in range(request_count)
                ]
                for future in as_completed(futures):
                    results.append(future.result())
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        summary = _summary(results)
        summary["wall_ms"] = round(elapsed_ms, 3)
        summary["throughput_rps"] = round(len(results) / (elapsed_ms / 1000.0), 3)
        output["concurrent"][str(concurrency)] = summary  # type: ignore[index]

    output["rss_after_concurrency_mib"] = _rss_mib()
    print(json.dumps(output, sort_keys=True))


if __name__ == "__main__":
    main()
