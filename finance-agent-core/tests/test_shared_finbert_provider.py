from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from src.infrastructure.sentiment import FinBERTResult, get_finbert_analyzer


def test_platform_provider_import_does_not_load_model_dependencies() -> None:
    project_root = Path(__file__).resolve().parents[1]
    script = """
import sys
from src.infrastructure.sentiment import get_finbert_analyzer

assert "torch" not in sys.modules
assert "transformers" not in sys.modules
analyzer = get_finbert_analyzer()
assert analyzer.model is None
assert analyzer.tokenizer is None
"""

    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=project_root,
        capture_output=True,
        check=False,
        text=True,
    )

    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    ("label", "score", "has_numbers", "expected"),
    [
        ("positive", 0.9, False, True),
        ("negative", 0.9, True, False),
        ("neutral", 0.99, False, False),
        ("positive", 0.84, False, False),
    ],
)
def test_skip_llm_decision_requires_confident_simple_sentiment(
    label: str, score: float, has_numbers: bool, expected: bool
) -> None:
    result = FinBERTResult(
        label=label,
        score=score,
        all_scores={label: score},
        has_numbers=has_numbers,
    )

    assert get_finbert_analyzer().should_skip_llm(result) is expected
