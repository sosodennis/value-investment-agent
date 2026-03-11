from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from .text_record import FilingTextRecord


class _FocusExtractorFn(Protocol):
    def __call__(self, *, form: str, text: str) -> str | None: ...


class _Is8KFormFn(Protocol):
    def __call__(self, form: str) -> bool: ...


class _Refined8KResult(Protocol):
    text: str | None
    sections_selected: int
    noise_sentences_skipped: int


class _Refine8KAnalysisTextFn(Protocol):
    def __call__(self, text: str) -> _Refined8KResult: ...


class _SplitTextIntoSentencesFn(Protocol):
    def __call__(self, text: str) -> list[str]: ...


class _ShouldFastSkipFlsFn(Protocol):
    def __call__(self, analysis_sentences: list[str]) -> bool: ...


class _FilterForwardLookingSentencesWithStatsFn(Protocol):
    def __call__(
        self,
        sentences: list[str],
    ) -> tuple[list[str], dict[str, float | int]]: ...


class _AsFloatFn(Protocol):
    def __call__(self, value: object) -> float: ...


class _AsIntFn(Protocol):
    def __call__(self, value: object) -> int: ...


class _BuildDocTypeFn(Protocol):
    def __call__(self, form: str, *, used_focus: bool) -> str: ...


class _BuildSecSourceUrlFn(Protocol):
    def __call__(
        self,
        *,
        ticker: str,
        accession_number: str | None,
        cik: str | None,
    ) -> str: ...


@dataclass(frozen=True)
class PreparedRecordPayload:
    analysis_text: str
    analysis_sentences: list[str]
    retrieval_corpus: list[str]
    doc_type: str
    source_url: str


@dataclass(frozen=True)
class PreparedRecordDiagnostics:
    split_ms: float
    fls_ms: float
    fls_model_load_ms: float
    fls_inference_ms: float
    fls_sentences_scored: int
    fls_prefilter_selected: int
    fls_batches: int
    fls_cache_hits: int
    fls_cache_misses: int
    fls_fast_skip_records: int
    fls_fast_skip_sentences: int
    eight_k_sections_selected: int
    eight_k_noise_sentences_skipped: int


def prepare_record_processing_payload(
    *,
    ticker: str,
    record: FilingTextRecord,
    extract_focus_text_fn: _FocusExtractorFn,
    is_8k_form_fn: _Is8KFormFn,
    refine_8k_analysis_text_fn: _Refine8KAnalysisTextFn,
    split_text_into_sentences_fn: _SplitTextIntoSentencesFn,
    should_fast_skip_fls_fn: _ShouldFastSkipFlsFn,
    filter_forward_looking_sentences_with_stats_fn: _FilterForwardLookingSentencesWithStatsFn,
    as_float_fn: _AsFloatFn,
    as_int_fn: _AsIntFn,
    build_doc_type_fn: _BuildDocTypeFn,
    build_sec_source_url_fn: _BuildSecSourceUrlFn,
) -> tuple[PreparedRecordPayload, PreparedRecordDiagnostics]:
    focused_section = record.focus_text or extract_focus_text_fn(
        form=record.form,
        text=record.text,
    )
    analysis_text = focused_section or record.text

    eight_k_sections_selected = 0
    eight_k_noise_sentences_skipped = 0
    if is_8k_form_fn(record.form):
        refined_8k = refine_8k_analysis_text_fn(analysis_text)
        analysis_text = refined_8k.text or analysis_text
        eight_k_sections_selected = refined_8k.sections_selected
        eight_k_noise_sentences_skipped = refined_8k.noise_sentences_skipped

    split_started = time.perf_counter()
    analysis_sentences = split_text_into_sentences_fn(analysis_text)
    split_ms = (time.perf_counter() - split_started) * 1000.0

    fls_ms = 0.0
    fls_stats: dict[str, float | int] = {}
    fls_fast_skip_records = 0
    fls_fast_skip_sentences = 0

    if should_fast_skip_fls_fn(analysis_sentences):
        forward_sentences: list[str] = []
        fls_fast_skip_records = 1
        fls_fast_skip_sentences = len(analysis_sentences)
    else:
        fls_started = time.perf_counter()
        forward_sentences, fls_stats = filter_forward_looking_sentences_with_stats_fn(
            analysis_sentences
        )
        fls_ms = (time.perf_counter() - fls_started) * 1000.0

    retrieval_corpus = forward_sentences if forward_sentences else analysis_sentences
    doc_type = build_doc_type_fn(record.form, used_focus=focused_section is not None)
    source_url = build_sec_source_url_fn(
        ticker=ticker,
        accession_number=record.accession_number,
        cik=record.cik,
    )

    payload = PreparedRecordPayload(
        analysis_text=analysis_text,
        analysis_sentences=analysis_sentences,
        retrieval_corpus=retrieval_corpus,
        doc_type=doc_type,
        source_url=source_url,
    )
    diagnostics = PreparedRecordDiagnostics(
        split_ms=split_ms,
        fls_ms=fls_ms,
        fls_model_load_ms=as_float_fn(fls_stats.get("model_load_ms")),
        fls_inference_ms=as_float_fn(fls_stats.get("inference_ms")),
        fls_sentences_scored=as_int_fn(fls_stats.get("sentences_scored")),
        fls_prefilter_selected=as_int_fn(fls_stats.get("prefilter_selected")),
        fls_batches=as_int_fn(fls_stats.get("batches")),
        fls_cache_hits=as_int_fn(fls_stats.get("cache_hits")),
        fls_cache_misses=as_int_fn(fls_stats.get("cache_misses")),
        fls_fast_skip_records=fls_fast_skip_records,
        fls_fast_skip_sentences=fls_fast_skip_sentences,
        eight_k_sections_selected=eight_k_sections_selected,
        eight_k_noise_sentences_skipped=eight_k_noise_sentences_skipped,
    )
    return payload, diagnostics
