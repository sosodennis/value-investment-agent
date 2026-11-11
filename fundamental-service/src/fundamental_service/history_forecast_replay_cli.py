"""Compose the production Fundamental runtime for a pinned SEC replay plan."""

from __future__ import annotations

import argparse
import asyncio
import sys
from importlib.metadata import version
from pathlib import Path

from .history_forecast_replay import (
    HistoryReplayPlanV1,
    run_history_replay,
    validate_fixed_cohort,
    write_history_replay,
)
from .history_replay import (
    ROOT,
    _ensure_tracked_tree_clean,
    _resolve_commit,
    _runtime_pins,
)
from .history_review_signing import read_document
from .serialization import canonical_bytes


def replay_runtime_pins() -> dict[str, str]:
    return {
        **_runtime_pins(_resolve_commit()),
        "arelle_version": version("arelle-release"),
        "decimal_precision": "50",
    }


async def _execute(
    plan: HistoryReplayPlanV1, output_directory: Path, cohort_root: Path
) -> dict[str, object]:
    # This CLI is a composition root. Production repositories and trust settings
    # come from the existing runtime factory; fixture composition is unreachable.
    from .app import create_runtime_app

    app = create_runtime_app()
    async with app.router.lifespan_context(app):
        application = app.state.application
        if not application.require_metadata or not application.ready:
            raise ValueError(
                "the configured production Fundamental runtime is not ready"
            )
        artifacts = await asyncio.to_thread(
            run_history_replay, application, plan, cohort_root=cohort_root
        )
        writes = write_history_replay(artifacts, output_directory)
        return {
            "runtime": plan.runtime,
            "input_digest": writes["input"]["sha256"],
            "output_digest": writes["report"]["sha256"],
            "artifacts": writes,
            "report": artifacts["report"],
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument(
        "--cohort-root",
        type=Path,
        default=ROOT,
        help="Root containing the unchanged, digest-pinned SEC cohort evidence",
    )
    parser.add_argument(
        "--output-directory",
        type=Path,
        default=ROOT / "docs/acceptance/issue-361-service-replay-v1",
    )
    arguments = parser.parse_args(argv)
    try:
        _ensure_tracked_tree_clean(str(Path(__file__).relative_to(ROOT)))
        plan = HistoryReplayPlanV1.model_validate_json(
            canonical_bytes(read_document(arguments.plan))
        )
        if plan.evidence_class != "calibration":
            raise ValueError(
                "the production replay command requires the fixed calibration cohort"
            )
        if plan.runtime != replay_runtime_pins():
            raise ValueError(
                "replay plan runtime differs from this exact commit and runtime pins"
            )
        validate_fixed_cohort(plan, cohort_root=arguments.cohort_root)
        result = asyncio.run(
            _execute(plan, arguments.output_directory, arguments.cohort_root)
        )
        print(canonical_bytes(result).decode("utf-8"))
        return 0
    except (ValueError, OSError, EOFError) as error:
        print(f"history forecast replay failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
