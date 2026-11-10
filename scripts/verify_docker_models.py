#!/usr/bin/env python3
"""Probe baked models offline in a disposable container; emit comparable JSON."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

TEXTS = [
    "Management expects higher revenue and operating margins next year.",
    "Revenue declined and the company reported a substantial loss.",
    "The annual meeting took place on Tuesday.",
]


def embeddings() -> dict[str, object]:
    import numpy as np
    import torch
    from fastembed import TextEmbedding
    from sentence_transformers import SentenceTransformer

    torch.set_num_threads(1)
    model = SentenceTransformer(
        "sentence-transformers/all-MiniLM-L6-v2", local_files_only=True
    )
    dense = model.encode(TEXTS, normalize_embeddings=True)
    fast = np.array(
        list(
            TextEmbedding(
                model_name="sentence-transformers/all-MiniLM-L6-v2",
                cache_dir=os.environ["FASTEMBED_CACHE_PATH"],
                local_files_only=True,
                threads=1,
            ).embed(TEXTS)
        )
    )
    result: dict[str, object] = {}
    for name, vectors in (("sentence_transformer", dense), ("fastembed", fast)):
        assert vectors.shape == (len(TEXTS), 384)
        assert np.isfinite(vectors).all()
        scores = vectors @ vectors[0]
        result[name] = {
            "vectors": vectors.tolist(),
            "ranking": sorted(range(len(TEXTS)), key=lambda i: -float(scores[i])),
        }
    return result


def classifier(kind: str) -> dict[str, object]:
    from model_inference_service.models import make_default_runners

    operation = "news.sentiment" if kind == "news" else "sec.fls"
    runner = make_default_runners()[operation]
    status = runner.load()
    assert status.loaded, status.error
    runner.warmup()
    outputs = (
        [runner.infer({"text": text}) for text in TEXTS]
        if kind == "news"
        else runner.infer({"sentences": TEXTS})
    )
    return {"model_revision": status.model_revision, "outputs": outputs}


def inventory() -> list[dict[str, object]]:
    root = Path(os.environ["HF_HUB_CACHE"])
    artifacts = []
    for snapshot in sorted(root.glob("models--*/snapshots/*")):
        for path in sorted(snapshot.rglob("*")):
            if not path.is_file():
                continue
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                while chunk := stream.read(1024 * 1024):
                    digest.update(chunk)
            artifacts.append(
                {
                    "path": str(path.relative_to(root)),
                    "bytes": path.stat().st_size,
                    "sha256": digest.hexdigest(),
                }
            )
    assert artifacts, "no baked model artifacts found"
    return artifacts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kind", choices=("embeddings", "news", "fls"))
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    for name in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE", "HF_LOCAL_FILES_ONLY"):
        assert os.environ.get(name) == "1", f"{name}=1 is required"
    packages = {}
    for name in ("torch", "transformers", "sentence-transformers", "fastembed"):
        try:
            packages[name] = version(name)
        except PackageNotFoundError:
            continue
    result = {
        "kind": args.kind,
        "inputs": TEXTS,
        "packages": packages,
        "artifacts": inventory(),
        "result": embeddings() if args.kind == "embeddings" else classifier(args.kind),
    }
    args.output.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n")


if __name__ == "__main__":
    main()
