"""Measure the existing SEC forward-looking statement classifier."""

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
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import redirect_stdout
from importlib import import_module
from typing import Protocol, cast


REPOSITORY_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
FINANCE_AGENT_ROOT = os.path.join(REPOSITORY_ROOT, "finance-agent-core")
if FINANCE_AGENT_ROOT not in sys.path:
    sys.path.insert(0, FINANCE_AGENT_ROOT)


class FLSModule(Protocol):
    def warmup_forward_looking_filter(self) -> dict[str, object]: ...

    def filter_forward_looking_sentences_with_stats(
        self, sentences: list[str]
    ) -> tuple[list[str], dict[str, float | int]]: ...


def rss_mib() -> float:
    value = float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    if platform.system() == "Darwin":
        return round(value / (1024.0 * 1024.0), 3)
    return round(value / 1024.0, 3)


def percentile(values: list[float], percentile_value: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    index = min(
        len(ordered) - 1, max(0, int(round(percentile_value / 100 * len(ordered))) - 1)
    )
    return round(ordered[index], 3)


def call(
    module: FLSModule, request_id: int, sentences_per_request: int
) -> dict[str, object]:
    sentences = [
        f"Management expects revenue growth to improve in outlook period {request_id}-{index}."
        for index in range(sentences_per_request)
    ]
    started = time.perf_counter()
    try:
        selected, stats = module.filter_forward_looking_sentences_with_stats(sentences)
        return {
            "elapsed_ms": round((time.perf_counter() - started) * 1000.0, 3),
            "ok": True,
            "selected": len(selected),
            "stats": stats,
            "error": None,
        }
    except Exception as exc:  # pragma: no cover - protects the benchmark process
        return {
            "elapsed_ms": round((time.perf_counter() - started) * 1000.0, 3),
            "ok": False,
            "selected": 0,
            "stats": {},
            "error": type(exc).__name__,
        }


def summarize(results: list[dict[str, object]]) -> dict[str, object]:
    latencies = [float(item["elapsed_ms"]) for item in results]
    successes = [item for item in results if bool(item["ok"])]
    return {
        "requests": len(results),
        "successes": len(successes),
        "errors": len(results) - len(successes),
        "p50_ms": percentile(latencies, 50),
        "p95_ms": percentile(latencies, 95),
        "max_ms": round(max(latencies), 3) if latencies else 0.0,
        "mean_ms": round(statistics.fmean(latencies), 3) if latencies else 0.0,
        "raw": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sequential", type=int, default=8)
    parser.add_argument("--concurrency", type=int, nargs="+", default=[1, 2, 4, 8])
    parser.add_argument("--requests-per-level", type=int, default=8)
    parser.add_argument("--sentences-per-request", type=int, default=16)
    parser.add_argument("--warmup-requests", type=int, default=0)
    args = parser.parse_args()

    sink = io.StringIO()
    output: dict[str, object]
    with redirect_stdout(sink):
        module = cast(
            FLSModule,
            import_module(
                "src.agents.fundamental.subdomains.forward_signals.infrastructure.sec_xbrl.filtering.fls_filter"
            ),
        )
        load_started = time.perf_counter()
        warmup = module.warmup_forward_looking_filter()
        load_ms = (time.perf_counter() - load_started) * 1000.0
        if not bool(warmup.get("loaded")):
            output = {
                "available": False,
                "warmup": warmup,
                "load_ms": round(load_ms, 3),
                "rss_peak_mib": rss_mib(),
            }
        else:
            warmup_inference = [
                call(module, index, args.sentences_per_request)
                for index in range(args.warmup_requests)
            ]
            sequential = [
                call(module, index, args.sentences_per_request)
                for index in range(args.sequential)
            ]
            output = {
                "available": True,
                "model": os.getenv("SEC_TEXT_FLS_MODEL", "yiyanghkust/finbert-fls"),
                "load_ms": round(load_ms, 3),
                "warmup": warmup,
                "warmup_inference": summarize(warmup_inference),
                "rss_after_load_mib": rss_mib(),
                "sequential": summarize(sequential),
                "concurrent": {},
                "cpu_count": os.cpu_count(),
                "platform": platform.platform(),
                "python": platform.python_version(),
            }
            concurrent_output = cast(dict[str, dict[str, object]], output["concurrent"])
            for concurrency in args.concurrency:
                request_count = max(concurrency, args.requests_per_level)
                started = time.perf_counter()
                results: list[dict[str, object]] = []
                with ThreadPoolExecutor(max_workers=concurrency) as executor:
                    futures = [
                        executor.submit(
                            call,
                            module,
                            concurrency * 100000 + index,
                            args.sentences_per_request,
                        )
                        for index in range(request_count)
                    ]
                    for future in as_completed(futures):
                        results.append(future.result())
                wall_ms = (time.perf_counter() - started) * 1000.0
                summary = summarize(results)
                summary["wall_ms"] = round(wall_ms, 3)
                summary["throughput_rps"] = round(len(results) / (wall_ms / 1000.0), 3)
                concurrent_output[str(concurrency)] = summary
            output["rss_after_concurrency_mib"] = rss_mib()
    print(json.dumps(output, sort_keys=True))


if __name__ == "__main__":
    main()
