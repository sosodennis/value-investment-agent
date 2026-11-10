from __future__ import annotations

import os
from fnmatch import fnmatch


def select_artifacts(files: list[str]) -> list[str]:
    """Keep loader metadata and one supported set of PyTorch weights."""
    safe = "model.safetensors" in files or "model.safetensors.index.json" in files
    weights = "model*.safetensors" if safe else "pytorch_model*.bin"
    selected = sorted(
        name
        for name in files
        if "/" not in name
        and (name.endswith((".json", ".txt", ".model")) or fnmatch(name, weights))
    )
    if not any(fnmatch(name, weights) for name in selected):
        raise ValueError("model revision has no supported PyTorch weights")
    return selected


def main() -> None:
    from huggingface_hub import list_repo_files, snapshot_download

    configured = {
        "news.sentiment": (
            os.environ["NEWS_FINBERT_MODEL"],
            os.environ["NEWS_FINBERT_REVISION"],
        ),
        "sec.fls": (
            os.environ["SEC_FLS_MODEL"],
            os.environ["SEC_FLS_REVISION"],
        ),
    }
    requested = {
        operation.strip()
        for operation in os.getenv("INFERENCE_OPERATIONS", ",".join(configured)).split(
            ","
        )
        if operation.strip()
    }
    unknown = requested - configured.keys()
    if unknown:
        raise ValueError(
            f"unsupported inference operations: {', '.join(sorted(unknown))}"
        )
    if not requested:
        raise ValueError("INFERENCE_OPERATIONS must select at least one operation")

    for operation in sorted(requested):
        repo_id, revision = configured[operation]
        files = list_repo_files(repo_id=repo_id, revision=revision)
        snapshot_download(
            repo_id=repo_id,
            revision=revision,
            allow_patterns=select_artifacts(files),
        )


if __name__ == "__main__":
    main()
