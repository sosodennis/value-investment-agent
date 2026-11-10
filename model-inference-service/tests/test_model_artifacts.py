from __future__ import annotations

import runpy
from pathlib import Path

import pytest

select_artifacts = runpy.run_path(
    str(Path(__file__).resolve().parents[1] / "scripts" / "bake_models.py")
)["select_artifacts"]


def test_prefers_safetensors_without_dropping_tokenizer_metadata() -> None:
    files = [
        "config.json",
        "tokenizer.json",
        "vocab.txt",
        "model.safetensors",
        "pytorch_model.bin",
        "training_args.bin",
        "tf_model.h5",
        "onnx/model.onnx",
        "openvino/openvino_model.bin",
    ]
    assert select_artifacts(files) == [
        "config.json",
        "model.safetensors",
        "tokenizer.json",
        "vocab.txt",
    ]


def test_supports_pytorch_only_fls_revision() -> None:
    assert select_artifacts(
        [
            "config.json",
            "pytorch_model.bin",
            "training_args.bin",
            "vocab.txt",
        ]
    ) == ["config.json", "pytorch_model.bin", "vocab.txt"]


def test_keeps_sharded_weights_and_their_index() -> None:
    assert select_artifacts(
        [
            "model.safetensors.index.json",
            "model-00001-of-00002.safetensors",
            "model-00002-of-00002.safetensors",
            "pytorch_model.bin",
            "config.json",
        ]
    ) == [
        "config.json",
        "model-00001-of-00002.safetensors",
        "model-00002-of-00002.safetensors",
        "model.safetensors.index.json",
    ]


def test_rejects_revision_without_supported_weights() -> None:
    with pytest.raises(ValueError, match="no supported PyTorch weights"):
        select_artifacts(["config.json", "tf_model.h5"])
