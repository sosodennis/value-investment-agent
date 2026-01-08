import logging
import re
from dataclasses import asdict, dataclass
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Model chosen from research: project-aps/finbert-finetune
FINBERT_MODEL_NAME = "project-aps/finbert-finetune"


@dataclass
class FinBERTResult:
    label: str  # "positive", "negative", "neutral"
    score: float  # Confidence 0.0 - 1.0
    all_scores: dict[str, float]
    has_numbers: bool  # Detected numerical values (weakness flag)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class FinBERTAnalyzer:
    """
    Lazy-loading FinBERT sentiment analyzer.
    Optimized for cost/latency by providing a 'skip LLM' recommendation.
    """

    _instance: Optional["FinBERTAnalyzer"] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self.tokenizer = None
        self.model = None
        self.load_error = None
        self.device = None
        self._initialized = True

    def _lazy_load(self) -> bool:
        """Loads model and dependencies into memory only when needed."""
        if self.model is not None:
            return True
        if self.load_error:
            return False

        try:
            # Conditional imports to prevent startup crashes if dependencies are missing
            import torch
            from transformers import AutoModelForSequenceClassification, AutoTokenizer

            self.device = "cuda" if torch.cuda.is_available() else "cpu"
            logger.info(f"Loading FinBERT model: {FINBERT_MODEL_NAME} on {self.device}")
            self.tokenizer = AutoTokenizer.from_pretrained(FINBERT_MODEL_NAME)
            self.model = AutoModelForSequenceClassification.from_pretrained(
                FINBERT_MODEL_NAME
            ).to(self.device)
            self.model.eval()
            return True
        except ImportError as e:
            self.load_error = (
                f"Missing dependencies: {e}. Please install transformers and torch."
            )
            print(f"FinBERT disabled: {self.load_error}")
            return False
        except Exception as e:
            self.load_error = str(e)
            print(f"Failed to load FinBERT model: {e}")
            return False

    def is_available(self) -> bool:
        return self._lazy_load()

    def _contains_numbers(self, text: str) -> bool:
        """
        Detects if text contains numerical values or comparisons.
        FinBERT is known to struggle with math (e.g., '103m vs 172m').
        """
        # Basic regex to find numbers, currency, or percentage
        return bool(re.search(r"\d", text))

    def analyze(self, text: str) -> FinBERTResult | None:
        """
        Analyzes a single piece of text.
        Returns None if model fails to load or inference fails.
        """
        if not self._lazy_load() or not text:
            return None

        try:
            import torch

            inputs = self.tokenizer(
                text, return_tensors="pt", padding=True, truncation=True, max_length=512
            ).to(self.device)

            with torch.no_grad():
                outputs = self.model(**inputs)
                logits = outputs.logits

            probs = torch.nn.functional.softmax(logits, dim=-1).cpu().numpy()[0]

            # Map labels for project-aps/finbert-finetune:
            # 0: neutral, 1: negative, 2: positive (verified via tests and research doc)
            labels = ["neutral", "negative", "positive"]
            all_scores = {labels[i]: float(probs[i]) for i in range(len(labels))}

            max_idx = probs.argmax()
            label = labels[max_idx]
            score = float(probs[max_idx])

            return FinBERTResult(
                label=label,
                score=score,
                all_scores=all_scores,
                has_numbers=self._contains_numbers(text),
            )
        except Exception as e:
            logger.warning(f"FinBERT inference error: {e}")
            return None

    def should_skip_llm(self, result: FinBERTResult, threshold: float = 0.85) -> bool:
        """
        Decision logic for cost optimization.
        Skip LLM if:
        1. Confidence is very high (> threshold)
        2. No numerical values are present (FinBERT's weakness)
        3. Simple sentiment (not neutral, which often implies nuance needed)
        """
        if result.label == "neutral":
            return False

        return result.score >= threshold and not result.has_numbers


# Singleton helper
def get_finbert_analyzer() -> FinBERTAnalyzer:
    return FinBERTAnalyzer()
