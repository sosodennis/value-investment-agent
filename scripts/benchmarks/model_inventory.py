"""Probe each model-backed workload in a fresh process."""

from __future__ import annotations

import argparse
import io
import json
import os
import platform
import resource
import sys
import time
from contextlib import redirect_stdout
from importlib import import_module
from typing import Protocol, cast


REPOSITORY_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
FINANCE_AGENT_ROOT = os.path.join(REPOSITORY_ROOT, "finance-agent-core")
if FINANCE_AGENT_ROOT not in sys.path:
    sys.path.insert(0, FINANCE_AGENT_ROOT)


class NewsAnalyzer(Protocol):
    device: str | None
    load_error: str | None

    def is_available(self) -> bool: ...


class NewsModule(Protocol):
    def get_finbert_analyzer(self) -> NewsAnalyzer: ...


class WarmupModule(Protocol):
    def warmup_forward_looking_filter(self) -> dict[str, object]: ...

    def warmup_dependency_matcher(self) -> dict[str, object]: ...


class DenseRetriever(Protocol):
    _load_error: str | None

    def rank(self, query: str, corpus: list[str]) -> list[int]: ...


class DenseModule(Protocol):
    _DenseRetriever: type[DenseRetriever]


class SycophancyDetector(Protocol):
    def check_consensus(
        self, bull_thesis: str, bear_thesis: str
    ) -> tuple[float, bool]: ...


class SycophancyModule(Protocol):
    def get_sycophancy_detector_provider(self) -> SycophancyDetector: ...


def _rss_mib() -> float:
    value = float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    if platform.system() == "Darwin":
        return round(value / (1024.0 * 1024.0), 3)
    return round(value / 1024.0, 3)


def _probe(workload: str) -> dict[str, object]:
    result: dict[str, object] = {
        "workload": workload,
        "available": False,
        "load_ms": None,
        "inference_ms": None,
        "rss_peak_mib": None,
        "error": None,
    }
    if workload == "news_finbert":
        module = cast(NewsModule, import_module("src.infrastructure.sentiment"))
        analyzer = module.get_finbert_analyzer()
        started = time.perf_counter()
        result["available"] = analyzer.is_available()
        result["load_ms"] = round((time.perf_counter() - started) * 1000.0, 3)
        result["model"] = "project-aps/finbert-finetune"
        result["device"] = analyzer.device
        result["error"] = analyzer.load_error
    elif workload == "sec_fls":
        module = cast(
            WarmupModule,
            import_module(
                "src.agents.fundamental.subdomains.forward_signals.infrastructure.sec_xbrl"
            ),
        )
        started = time.perf_counter()
        warmup = module.warmup_forward_looking_filter()
        result["load_ms"] = warmup.get("model_load_ms")
        result["inference_ms"] = warmup.get("inference_ms")
        result["available"] = bool(warmup.get("loaded"))
        result["model"] = os.getenv("SEC_TEXT_FLS_MODEL", "yiyanghkust/finbert-fls")
        result["details"] = warmup
        result["elapsed_ms"] = round((time.perf_counter() - started) * 1000.0, 3)
    elif workload == "sec_dense":
        module = cast(
            DenseModule,
            import_module(
                "src.agents.fundamental.subdomains.forward_signals.infrastructure.sec_xbrl.retrieval.hybrid_retriever_dense_service"
            ),
        )
        retriever = module._DenseRetriever()
        started = time.perf_counter()
        rankings = retriever.rank(
            "revenue outlook", ["Revenue growth is expected.", "Costs may increase."]
        )
        result["elapsed_ms"] = round((time.perf_counter() - started) * 1000.0, 3)
        result["available"] = bool(rankings)
        result["model"] = os.getenv(
            "SEC_TEXT_EMBED_MODEL", "sentence-transformers/all-MiniLM-L6-v2"
        )
        result["error"] = retriever._load_error
    elif workload == "dependency_matcher":
        module = cast(
            WarmupModule,
            import_module(
                "src.agents.fundamental.subdomains.forward_signals.infrastructure.sec_xbrl"
            ),
        )
        started = time.perf_counter()
        warmup = module.warmup_dependency_matcher()
        result["elapsed_ms"] = round((time.perf_counter() - started) * 1000.0, 3)
        result["available"] = bool(warmup.get("loaded"))
        result["model"] = os.getenv("SEC_TEXT_DEPENDENCY_MODEL", "en_core_web_sm")
        result["details"] = warmup
    elif workload == "sycophancy_embedding":
        module = cast(
            SycophancyModule,
            import_module("src.agents.debate.infrastructure.sycophancy"),
        )
        detector = module.get_sycophancy_detector_provider()
        started = time.perf_counter()
        similarity, flagged = detector.check_consensus(
            "Revenue growth will accelerate.", "Revenue growth will accelerate."
        )
        result["elapsed_ms"] = round((time.perf_counter() - started) * 1000.0, 3)
        result["available"] = True
        result["model"] = "sentence-transformers/all-MiniLM-L6-v2 (fastembed)"
        result["similarity"] = round(similarity, 6)
        result["flagged"] = flagged
    else:
        raise ValueError(f"unknown workload: {workload}")
    result["rss_peak_mib"] = _rss_mib()
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--workload",
        required=True,
        choices=(
            "news_finbert",
            "sec_fls",
            "sec_dense",
            "dependency_matcher",
            "sycophancy_embedding",
        ),
    )
    args = parser.parse_args()
    sink = io.StringIO()
    with redirect_stdout(sink):
        try:
            output = _probe(args.workload)
        except Exception as exc:
            output = {
                "workload": args.workload,
                "available": False,
                "error": f"{type(exc).__name__}: {exc}",
                "rss_peak_mib": _rss_mib(),
            }
    print(json.dumps(output, sort_keys=True))


if __name__ == "__main__":
    main()
