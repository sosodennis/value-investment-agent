from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a markdown checklist artifact from release gate snapshot.",
    )
    parser.add_argument(
        "--snapshot",
        type=Path,
        required=True,
        help="Path to fundamental release gate snapshot JSON.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Path to write markdown checklist artifact.",
    )
    parser.add_argument(
        "--owner",
        type=str,
        default="automation",
        help="Checklist owner label.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = _read_payload(args.snapshot)
    markdown = _build_markdown(
        payload=payload, snapshot_path=args.snapshot, owner=args.owner
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(markdown, encoding="utf-8")
    return 0


def _read_payload(path: Path) -> Mapping[str, object]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, Mapping):
        raise TypeError("snapshot root must be an object")
    return raw


def _build_markdown(
    *,
    payload: Mapping[str, object],
    snapshot_path: Path,
    owner: str,
) -> str:
    generated_at = _as_text(payload.get("generated_at"), fallback="unknown")
    gate_profile = _as_text(payload.get("gate_profile"), fallback="unknown")
    exit_code = _as_int(payload.get("release_gate_exit_code"))
    report_path = _as_text(payload.get("report_path"), fallback="unknown")
    replay_report_path = _as_optional_text(payload.get("replay_report_path"))
    live_replay_run_path = _as_optional_text(payload.get("live_replay_run_path"))

    summary = payload.get("summary")
    summary_map = summary if isinstance(summary, Mapping) else {}
    gap_distribution = summary_map.get("consensus_gap_distribution")
    gap_map = gap_distribution if isinstance(gap_distribution, Mapping) else {}
    replay_checks = summary_map.get("replay_checks")
    replay_map = replay_checks if isinstance(replay_checks, Mapping) else {}
    live_replay = summary_map.get("live_replay")
    live_replay_map = live_replay if isinstance(live_replay, Mapping) else {}

    issues = payload.get("issues")
    issue_list: list[str]
    if isinstance(issues, list):
        issue_list = [item for item in issues if isinstance(item, str) and item.strip()]
    else:
        issue_list = []

    decision = "Approve" if exit_code == 0 else "Reject"
    reason = (
        "all release gates passed"
        if exit_code == 0
        else "one or more release gates failed"
    )

    lines = [
        "# Fundamental Cohort Release Checklist (Auto)",
        "",
        "## Metadata",
        f"- Owner: {owner}",
        f"- Snapshot: `{snapshot_path}`",
        f"- Generated At: {generated_at}",
        f"- Gate Profile: `{gate_profile}`",
        f"- Release Gate Exit Code: {exit_code if exit_code is not None else 'unknown'}",
        "",
        "## Evidence Paths",
        f"- Backtest report: `{report_path}`",
        f"- Replay report: `{replay_report_path or 'n/a'}`",
        f"- Live replay run: `{live_replay_run_path or 'n/a'}`",
        "",
        "## Summary Snapshot",
        f"- total_cases: {_render_number(summary_map.get('total_cases'))}",
        f"- ok: {_render_number(summary_map.get('ok'))}",
        f"- errors: {_render_number(summary_map.get('errors'))}",
        f"- consensus_gap_available_count: {_render_number(gap_map.get('available_count'))}",
        f"- consensus_gap_median: {_render_number(gap_map.get('median'))}",
        f"- consensus_gap_p90_abs: {_render_number(gap_map.get('p90_abs'))}",
        f"- replay_trace_pass_rate: {_render_number(replay_map.get('trace_contract_pass_rate'))}",
        f"- replay_quality_block_rate: {_render_number(replay_map.get('quality_block_rate'))}",
        f"- replay_cache_hit_rate: {_render_number(replay_map.get('cache_hit_rate'))}",
        f"- replay_warm_latency_p90_ms: {_render_number(replay_map.get('warm_latency_p90_ms'))}",
        f"- replay_cold_latency_p90_ms: {_render_number(replay_map.get('cold_latency_p90_ms'))}",
        f"- live_replay_gate_passed: {_render_bool(live_replay_map.get('gate_passed'))}",
        "",
        "## Issues",
    ]
    if issue_list:
        for item in issue_list:
            lines.append(f"- {item}")
    else:
        lines.append("- none")

    lines.extend(
        [
            "",
            "## Decision",
            f"- Release decision: `{decision}`",
            f"- Reason: {reason}",
            "",
        ]
    )
    return "\n".join(lines)


def _as_text(raw: object, *, fallback: str) -> str:
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return fallback


def _as_optional_text(raw: object) -> str | None:
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return None


def _as_int(raw: object) -> int | None:
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return raw
    return None


def _render_number(raw: object) -> str:
    if isinstance(raw, bool):
        return "n/a"
    if isinstance(raw, int):
        return str(raw)
    if isinstance(raw, float):
        return f"{raw:.4f}"
    return "n/a"


def _render_bool(raw: object) -> str:
    if isinstance(raw, bool):
        return "true" if raw else "false"
    return "n/a"


if __name__ == "__main__":
    raise SystemExit(main())
