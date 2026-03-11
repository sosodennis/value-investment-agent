from __future__ import annotations

from dataclasses import dataclass


@dataclass
class FLSFilterStats:
    model_load_ms: float = 0.0
    inference_ms: float = 0.0
    sentences_scored: int = 0
    prefilter_selected: int = 0
    batches: int = 0
    cache_hits: int = 0
    cache_misses: int = 0

    def to_fields(self) -> dict[str, float | int]:
        return {
            "model_load_ms": round(self.model_load_ms, 3),
            "inference_ms": round(self.inference_ms, 3),
            "sentences_scored": self.sentences_scored,
            "prefilter_selected": self.prefilter_selected,
            "batches": self.batches,
            "cache_hits": self.cache_hits,
            "cache_misses": self.cache_misses,
        }
