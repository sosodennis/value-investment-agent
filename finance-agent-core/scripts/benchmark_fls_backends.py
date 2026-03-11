# ruff: noqa: E402

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.agents.fundamental.forward_signals.infrastructure.sec_xbrl.filtering.fls_filter import (
    _FLSClassifier,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Benchmark FLS inference latency on torch backend."
    )
    parser.add_argument(
        "--sentences",
        type=int,
        default=953,
        help="Number of synthetic sentences for each benchmark run.",
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=8,
        help="Timed benchmark iterations per backend.",
    )
    parser.add_argument(
        "--warmup",
        type=int,
        default=2,
        help="Warmup iterations per backend before timing.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional path to write benchmark report JSON.",
    )
    return parser.parse_args()


def _build_sentences(total: int) -> list[str]:
    safe_total = max(1, total)
    templates = [
        "Management expects revenue growth in the next quarter.",
        "The company reported historical operating expenses last year.",
        "Guidance indicates margin expansion from productivity efforts.",
        "Executives anticipate higher demand for cloud services.",
        "Prior-year comparison showed stable gross margin.",
    ]
    return [templates[idx % len(templates)] for idx in range(safe_total)]


def _benchmark_latency_ms(
    *,
    run_once: callable,
    warmup: int,
    iterations: int,
) -> list[float]:
    for _ in range(max(0, warmup)):
        run_once()
    samples: list[float] = []
    for _ in range(max(1, iterations)):
        start = time.perf_counter()
        run_once()
        samples.append((time.perf_counter() - start) * 1000.0)
    return samples


def _summarize_samples(samples: list[float]) -> dict[str, float]:
    sorted_samples = sorted(samples)
    p50 = statistics.median(sorted_samples)
    p95_idx = min(
        len(sorted_samples) - 1,
        max(0, math.ceil(0.95 * len(sorted_samples)) - 1),
    )
    p95 = sorted_samples[p95_idx]
    mean = statistics.mean(sorted_samples)
    return {
        "latency_p50_ms": round(p50, 3),
        "latency_p95_ms": round(p95, 3),
        "latency_mean_ms": round(mean, 3),
    }


def main() -> None:
    args = _parse_args()
    sentences = _build_sentences(args.sentences)

    classifier = _FLSClassifier()

    load_start = time.perf_counter()
    loaded = classifier._ensure_loaded()
    load_ms = (time.perf_counter() - load_start) * 1000.0
    if not loaded:
        raise RuntimeError("FLS classifier failed to load; benchmark aborted.")

    report: dict[str, object] = {
        "sentences": len(sentences),
        "iterations": max(1, args.iterations),
        "warmup": max(0, args.warmup),
        "model_load_ms": round(load_ms, 3),
        "loaded_backend": classifier._backend,
    }

    torch_samples = _benchmark_latency_ms(
        run_once=lambda: classifier._predict_keep_flags_torch(sentences=sentences),
        warmup=args.warmup,
        iterations=args.iterations,
    )
    torch_summary = _summarize_samples(torch_samples)
    report["torch"] = torch_summary

    print(json.dumps(report, indent=2))
    if args.output is not None:
        output_path = Path(args.output).resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(report, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
