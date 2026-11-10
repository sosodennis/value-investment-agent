"""Bake the immutable artifacts used by the existing offline embedding loaders."""

from __future__ import annotations

import os
from pathlib import Path

from huggingface_hub import snapshot_download

MODELS = (
    (
        "sentence-transformers/all-MiniLM-L6-v2",
        "1110a243fdf4706b3f48f1d95db1a4f5529b4d41",
        (
            "config.json",
            "config_sentence_transformers.json",
            "modules.json",
            "sentence_bert_config.json",
            "special_tokens_map.json",
            "tokenizer.json",
            "tokenizer_config.json",
            "vocab.txt",
            "1_Pooling/config.json",
            "model.safetensors",
        ),
    ),
    (
        "qdrant/all-MiniLM-L6-v2-onnx",
        "d13954661f83248295ba75c1ed411eef3b7b936e",
        (
            "config.json",
            "special_tokens_map.json",
            "tokenizer.json",
            "tokenizer_config.json",
            "vocab.txt",
            "model.onnx",
        ),
    ),
)


def main() -> None:
    cache = Path(os.environ["HF_HOME"])
    cache.mkdir(parents=True, exist_ok=True)
    if os.getenv("BAKE_HF_MODELS", "1") != "1":
        return
    for repo_id, revision, files in MODELS:
        snapshot = Path(
            snapshot_download(
                repo_id=repo_id,
                revision=revision,
                allow_patterns=list(files),
            )
        )
        # Existing offline loaders request the default ref; bind it to this pin.
        refs = snapshot.parent.parent / "refs"
        refs.mkdir(exist_ok=True)
        (refs / "main").write_text(revision)


if __name__ == "__main__":
    main()
