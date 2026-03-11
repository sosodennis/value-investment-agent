#!/usr/bin/env python3
from __future__ import annotations

import argparse
import fnmatch
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPO_REPORTS_PREFIX = "finance-agent-core/reports/"
PROJECT_REPORTS_PREFIX = "reports/"

ALWAYS_ALLOWED_FILENAMES = {
    ".gitignore",
    "README.md",
}

ALLOWED_REPORT_PATTERNS = (
    "fundamental_backtest_report_*.json",
    "fundamental_release_gate_snapshot_*.json",
    "forward_signal_calibration_pipeline_report_*.json",
    "fundamental_cohort_stability_report_*.json",
    "fundamental_replay_manifest_live_*.json",
    "fundamental_replay_checks_report_live_*.json",
    "fundamental_replay_cohort_gate_*.json",
    "fundamental_live_replay_cohort_run_*.json",
    "fundamental_cohort_release_checklist_*.md",
    "fundamental_reinvestment_clamp_profile_validation_report_*.json",
)

DISALLOWED_NAME_PATTERNS = (
    "*probe*.json",
    "*_update_*.json",
    "*debug*.json",
    "*trial*.json",
)


def _run_git(cmd: Sequence[str], cwd: Path) -> list[str]:
    process = subprocess.run(
        cmd,
        cwd=str(cwd),
        check=False,
        capture_output=True,
        text=True,
    )
    if process.returncode != 0:
        raise RuntimeError(process.stderr.strip() or "git command failed")
    return [line.strip() for line in process.stdout.splitlines() if line.strip()]


def _git_repo_root() -> Path:
    out = _run_git(("git", "rev-parse", "--show-toplevel"), PROJECT_ROOT)
    return Path(out[0])


def _normalize_report_relpath(raw_path: str) -> Path | None:
    normalized = raw_path.replace("\\", "/")
    if normalized.startswith(REPO_REPORTS_PREFIX):
        return Path(normalized[len(REPO_REPORTS_PREFIX) :])
    if normalized.startswith(PROJECT_REPORTS_PREFIX):
        return Path(normalized[len(PROJECT_REPORTS_PREFIX) :])
    return None


def _collect_staged_paths(repo_root: Path) -> list[Path]:
    raw_paths = _run_git(
        (
            "git",
            "diff",
            "--cached",
            "--name-only",
            "--diff-filter=ACMR",
            "--",
            "finance-agent-core/reports",
        ),
        repo_root,
    )
    paths: list[Path] = []
    for raw_path in raw_paths:
        rel_path = _normalize_report_relpath(raw_path)
        if rel_path is not None:
            paths.append(rel_path)
    return paths


def _is_allowed_report(rel_path: Path) -> tuple[bool, str]:
    filename = rel_path.name
    if filename in ALWAYS_ALLOWED_FILENAMES and len(rel_path.parts) == 1:
        return True, "policy_file"

    if len(rel_path.parts) > 1:
        return False, "nested_path_not_allowed"

    for pattern in DISALLOWED_NAME_PATTERNS:
        if fnmatch.fnmatch(filename, pattern):
            return False, f"disallowed_name_pattern:{pattern}"

    for pattern in ALLOWED_REPORT_PATTERNS:
        if fnmatch.fnmatch(filename, pattern):
            return True, f"allowed_pattern:{pattern}"

    return False, "not_in_allowlist"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Validate staged finance-agent-core/reports files against "
            "the reports version-control policy."
        )
    )
    parser.add_argument(
        "--paths",
        nargs="*",
        default=None,
        help=(
            "Optional explicit paths to validate instead of staged files. "
            "Paths may use either reports/... or finance-agent-core/reports/..."
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    repo_root = _git_repo_root()

    if args.paths is None:
        candidate_paths = _collect_staged_paths(repo_root)
    else:
        candidate_paths = []
        for raw_path in args.paths:
            rel_path = _normalize_report_relpath(raw_path)
            if rel_path is not None:
                candidate_paths.append(rel_path)

    violations: list[tuple[Path, str]] = []
    for rel_path in candidate_paths:
        allowed, reason = _is_allowed_report(rel_path)
        if not allowed:
            violations.append((rel_path, reason))

    if violations:
        print("reports VCS policy violation(s) found:")
        for rel_path, reason in violations:
            print(f"- reports/{rel_path.as_posix()} ({reason})")
        print(
            "\nAllowed files are defined by finance-agent-core/reports/.gitignore "
            "and finance-agent-core/reports/README.md."
        )
        return 1

    print("reports VCS policy check passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
