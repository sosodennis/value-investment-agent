from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol, cast


@dataclass(frozen=True)
class ModelStatus:
    loaded: bool
    model_revision: str
    error: str | None = None


class InferenceRunner(Protocol):
    operation: str
    model_revision: str

    def load(self) -> ModelStatus: ...

    def warmup(self) -> None: ...

    def infer(self, payload: object) -> dict[str, object]: ...


def _local_files_only() -> bool:
    return os.getenv("HF_LOCAL_FILES_ONLY", "1").strip().lower() not in {
        "0",
        "false",
        "no",
    }


def _configure_torch() -> None:
    import torch

    raw_threads = os.getenv("TORCH_NUM_THREADS", "1")
    try:
        thread_count = max(1, int(raw_threads))
    except ValueError:
        thread_count = 1
    torch.set_num_threads(thread_count)


class NewsRunner:
    operation = "news.sentiment"

    def __init__(self, *, model_name: str, revision: str) -> None:
        self.model_name = model_name
        self.model_revision = revision
        self._tokenizer: object | None = None
        self._model: object | None = None
        self._load_error: str | None = None

    def load(self) -> ModelStatus:
        if self._model is not None and self._tokenizer is not None:
            return ModelStatus(True, self.model_revision)
        if self._load_error is not None:
            return ModelStatus(False, self.model_revision, self._load_error)
        try:
            _configure_torch()
            from transformers import AutoModelForSequenceClassification, AutoTokenizer

            self._tokenizer = AutoTokenizer.from_pretrained(
                self.model_name,
                revision=self.model_revision,
                local_files_only=_local_files_only(),
            )
            self._model = AutoModelForSequenceClassification.from_pretrained(
                self.model_name,
                revision=self.model_revision,
                local_files_only=_local_files_only(),
            )
            cast(object, self._model).eval()  # type: ignore[attr-defined]
            return ModelStatus(True, self.model_revision)
        except Exception as exc:
            self._load_error = str(exc)
            return ModelStatus(False, self.model_revision, self._load_error)

    def warmup(self) -> None:
        result = self.infer({"text": "Management expects higher revenue growth."})
        if result.get("label") not in {"positive", "negative", "neutral"}:
            raise RuntimeError("news model warmup returned an unsupported label")

    def infer(self, payload: object) -> dict[str, object]:
        if self._model is None or self._tokenizer is None:
            raise RuntimeError("news model is not loaded")
        values = cast(Mapping[str, object], payload)
        text = str(values["text"])
        import torch

        tokenizer = self._tokenizer
        model = self._model
        inputs = tokenizer(  # type: ignore[operator]
            text,
            return_tensors="pt",
            padding=True,
            truncation=True,
            max_length=512,
        )
        with torch.no_grad():
            outputs = model(**inputs)  # type: ignore[operator]
        probabilities = torch.nn.functional.softmax(outputs.logits, dim=-1)[0]
        labels = ["neutral", "negative", "positive"]
        scores = {
            labels[index]: float(probabilities[index].item())
            for index in range(min(len(labels), len(probabilities)))
        }
        index = int(torch.argmax(probabilities).item())
        label = labels[index] if index < len(labels) else "neutral"
        return {"label": label, "confidence": scores.get(label, 0.0), "scores": scores}


class FLSRunner:
    operation = "sec.fls"

    def __init__(self, *, model_name: str, revision: str) -> None:
        self.model_name = model_name
        self.model_revision = revision
        self._tokenizer: object | None = None
        self._model: object | None = None
        self._keep_ids: set[int] = {0, 1}
        self._load_error: str | None = None

    def load(self) -> ModelStatus:
        if self._model is not None and self._tokenizer is not None:
            return ModelStatus(True, self.model_revision)
        if self._load_error is not None:
            return ModelStatus(False, self.model_revision, self._load_error)
        try:
            _configure_torch()
            from transformers import AutoModelForSequenceClassification, AutoTokenizer

            self._tokenizer = AutoTokenizer.from_pretrained(
                self.model_name,
                revision=self.model_revision,
                local_files_only=_local_files_only(),
            )
            self._model = AutoModelForSequenceClassification.from_pretrained(
                self.model_name,
                revision=self.model_revision,
                local_files_only=_local_files_only(),
            )
            cast(object, self._model).eval()  # type: ignore[attr-defined]
            config = getattr(self._model, "config", None)
            labels = getattr(config, "id2label", {})
            if isinstance(labels, dict):
                keep_ids = set()
                for raw_id, raw_label in labels.items():
                    normalized = str(raw_label).lower().replace(" ", "")
                    if "not" not in normalized and "fls" in normalized:
                        try:
                            keep_ids.add(int(raw_id))
                        except (TypeError, ValueError):
                            continue
                if keep_ids:
                    self._keep_ids = keep_ids
            return ModelStatus(True, self.model_revision)
        except Exception as exc:
            self._load_error = str(exc)
            return ModelStatus(False, self.model_revision, self._load_error)

    def warmup(self) -> None:
        result = self.infer(
            {
                "sentences": [
                    "Management expects higher revenue growth." for _ in range(32)
                ]
            }
        )
        predictions = result.get("predictions")
        if not isinstance(predictions, list) or len(predictions) != 32:
            raise RuntimeError("FLS model warmup returned an invalid result")

    def infer(self, payload: object) -> dict[str, object]:
        if self._model is None or self._tokenizer is None:
            raise RuntimeError("FLS model is not loaded")
        values = cast(Mapping[str, object], payload)
        sentences = [str(value) for value in cast(list[object], values["sentences"])]
        import torch

        predictions: list[dict[str, object]] = []
        for offset in range(0, len(sentences), 32):
            batch = sentences[offset : offset + 32]
            predictions.extend(self._infer_batch(batch, torch))
        return {"predictions": predictions}

    def _infer_batch(
        self, sentences: list[str], torch: object
    ) -> list[dict[str, object]]:
        tokenizer = self._tokenizer
        model = self._model
        inputs = tokenizer(  # type: ignore[operator]
            sentences,
            return_tensors="pt",
            padding=True,
            truncation=True,
            max_length=int(os.getenv("SEC_TEXT_FLS_MAX_LENGTH", "192")),
        )
        with torch.no_grad():  # type: ignore[attr-defined]
            logits = model(**inputs).logits  # type: ignore[operator]
        probabilities = torch.nn.functional.softmax(  # type: ignore[attr-defined]
            logits, dim=-1
        )
        predictions: list[dict[str, object]] = []
        for row in probabilities:
            label_id = int(torch.argmax(row).item())  # type: ignore[attr-defined]
            predictions.append(
                {
                    "keep": label_id in self._keep_ids,
                    "confidence": float(row[label_id].item()),
                }
            )
        return predictions


def make_default_runners() -> dict[str, InferenceRunner]:
    runners: dict[str, InferenceRunner] = {
        "news.sentiment": NewsRunner(
            model_name=os.getenv("NEWS_FINBERT_MODEL", "project-aps/finbert-finetune"),
            revision=os.getenv(
                "NEWS_FINBERT_REVISION",
                "2db55b5439cef6253c12a4973f3a9e823ff90b79",
            ),
        ),
        "sec.fls": FLSRunner(
            model_name=os.getenv("SEC_FLS_MODEL", "yiyanghkust/finbert-fls"),
            revision=os.getenv(
                "SEC_FLS_REVISION",
                "443586dc31c765c0aaf1c4daaed8cf3643c92fa5",
            ),
        ),
    }
    requested = os.getenv("INFERENCE_OPERATIONS", "").strip()
    if not requested:
        return runners
    allowed = {value.strip() for value in requested.split(",") if value.strip()}
    selected = {
        operation: runner
        for operation, runner in runners.items()
        if operation in allowed
    }
    unknown = allowed - runners.keys()
    if unknown:
        raise ValueError(
            f"unsupported inference operations: {', '.join(sorted(unknown))}"
        )
    if not selected:
        raise ValueError("INFERENCE_OPERATIONS must select at least one operation")
    return selected
