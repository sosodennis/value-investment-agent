from __future__ import annotations

import os

from huggingface_hub import snapshot_download


def main() -> None:
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
        snapshot_download(repo_id=repo_id, revision=revision)


if __name__ == "__main__":
    main()
