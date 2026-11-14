#!/usr/bin/env python3
"""Enforce issue-scoped acceptance metadata in the required contract-policy job."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from validate_acceptance_manifest import (
    acceptance_metadata_path,
    load_manifest,
    validate_manifest,
)

ISSUE_BRANCH_RE = re.compile(r"^codex/issue-(\d+)-")
GATED_ISSUES = {351, 352, 353, 354, 355, 361}
CLOSING_RE_TEMPLATE = r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#{}\b"


def _verified_commit_errors(
    manifest_commit: str, current_sha: str, issue: int
) -> list[str]:
    errors: list[str] = []
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", manifest_commit, current_sha],
        check=False,
        capture_output=True,
        text=True,
    )
    if ancestor.returncode != 0:
        return [
            f"verified manifest commit {manifest_commit} is not an ancestor of PR head {current_sha}"
        ]

    changed = subprocess.run(
        ["git", "diff", "--name-only", f"{manifest_commit}..{current_sha}"],
        check=False,
        capture_output=True,
        text=True,
    )
    if changed.returncode != 0:
        return ["cannot inspect files changed after the verified implementation commit"]

    invalid = []
    for path in changed.stdout.splitlines():
        if acceptance_metadata_path(path, issue):
            continue
        invalid.append(path)
    if invalid:
        errors.append(
            "files changed after the verified implementation commit must be acceptance "
            f"metadata only: {', '.join(invalid)}"
        )
    return errors


def _event_body() -> str:
    event_path = os.getenv("GITHUB_EVENT_PATH")
    if not event_path:
        return ""
    try:
        payload = json.loads(Path(event_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    pull_request = payload.get("pull_request")
    return pull_request.get("body") or "" if isinstance(pull_request, dict) else ""


def _pull_request_is_draft() -> bool | None:
    event_path = os.getenv("GITHUB_EVENT_PATH")
    if not event_path:
        return None
    try:
        payload = json.loads(Path(event_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    pull_request = payload.get("pull_request")
    if not isinstance(pull_request, dict):
        return None
    draft = pull_request.get("draft")
    return draft if isinstance(draft, bool) else None


def main() -> int:
    branch = os.getenv("GITHUB_HEAD_REF") or os.getenv("GITHUB_REF_NAME") or ""
    match = ISSUE_BRANCH_RE.match(branch)
    if not match:
        print(f"acceptance policy: PASS not applicable branch={branch or 'unknown'}")
        return 0

    issue = int(match.group(1))
    if issue not in GATED_ISSUES:
        print(f"acceptance policy: PASS issue={issue} outside fundamental sequence")
        return 0
    manifest_path = Path("docs/acceptance") / f"issue-{issue}-runtime.json"
    if not manifest_path.exists():
        print(
            f"acceptance policy: FAIL missing {manifest_path} for issue branch {branch}",
            file=sys.stderr,
        )
        return 1

    try:
        manifest = load_manifest(manifest_path)
    except (TypeError, ValueError) as exc:
        print(f"acceptance policy: FAIL: {exc}", file=sys.stderr)
        return 1

    current_sha = os.getenv("GITHUB_SHA")
    body = _event_body()
    closing_keyword = bool(
        re.search(CLOSING_RE_TEMPLATE.format(issue), body, re.IGNORECASE)
    )
    draft = _pull_request_is_draft()
    errors = validate_manifest(
        manifest,
        expected_issue=issue,
        require_sec_identity=issue in {355, 361},
    )
    expected_schema = 2 if issue == 361 else 1
    if manifest.get("schema_version") != expected_schema:
        errors.append(
            f"issue {issue} requires acceptance schema_version={expected_schema}"
        )
    if manifest.get("branch") != branch:
        errors.append("manifest branch must match the issue branch being checked")
    if manifest.get("status") == "VERIFIED":
        if not current_sha:
            errors.append("VERIFIED acceptance policy requires GITHUB_SHA")
        else:
            errors.extend(
                _verified_commit_errors(manifest["commit"], current_sha, issue)
            )
    if closing_keyword and manifest.get("status") != "VERIFIED":
        errors.append("PR closing keyword requires acceptance manifest status=VERIFIED")
    if draft is False and manifest.get("status") != "VERIFIED":
        errors.append(
            "a ready-for-review PR requires acceptance manifest status=VERIFIED"
        )
    if errors:
        for error in errors:
            print(f"acceptance policy: FAIL: {error}", file=sys.stderr)
        return 1

    print(
        f"acceptance policy: PASS issue={issue} status={manifest['status']} "
        f"manifest_commit={manifest['commit']} head={current_sha or 'local'}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
