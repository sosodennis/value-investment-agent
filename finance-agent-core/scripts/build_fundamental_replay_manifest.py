from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from collections.abc import Iterable
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from src.agents.fundamental.core_valuation.interface.replay_contracts import (  # noqa: E402
    ValuationReplayInputModel,
    parse_valuation_replay_input_model,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build valuation_replay_manifest_v1 from replay input files."
    )
    parser.add_argument(
        "--inputs",
        type=Path,
        nargs="*",
        default=None,
        help="Replay input JSON files (valuation_replay_input_v2).",
    )
    parser.add_argument(
        "--discover-root",
        type=Path,
        default=None,
        help="Directory to discover replay inputs automatically.",
    )
    parser.add_argument(
        "--discover-glob",
        type=str,
        default="*.replay-input*.json",
        help="Glob pattern used with --discover-root.",
    )
    parser.add_argument(
        "--discover-recursive",
        action="store_true",
        help="Use recursive glob discovery under --discover-root.",
    )
    parser.add_argument(
        "--ticker-allowlist",
        type=str,
        default="",
        help="Comma-separated ticker allowlist (e.g. AAPL,MSFT,GOOG,NVDA).",
    )
    parser.add_argument(
        "--latest-per-ticker",
        action="store_true",
        help=(
            "Keep only the newest replay input file per ticker by file modified time."
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Output path for valuation_replay_manifest_v1 JSON.",
    )
    parser.add_argument(
        "--stage-dir",
        type=Path,
        default=None,
        help=(
            "Optional directory to stage/copy replay input files before generating "
            "manifest. Manifest paths will point to staged files."
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_paths = _resolve_input_paths(
        inputs=args.inputs,
        discover_root=args.discover_root,
        discover_glob=args.discover_glob,
        discover_recursive=bool(args.discover_recursive),
    )
    if not input_paths:
        raise ValueError(
            "no replay inputs resolved; provide --inputs or --discover-root"
        )

    output_dir = args.output.parent.resolve()
    stage_dir = args.stage_dir.resolve() if args.stage_dir is not None else None
    if stage_dir is not None:
        stage_dir.mkdir(parents=True, exist_ok=True)
    ticker_allowlist = _parse_ticker_allowlist(args.ticker_allowlist)

    selected_entries = _select_entries(
        input_paths=input_paths,
        ticker_allowlist=ticker_allowlist,
        latest_per_ticker=bool(args.latest_per_ticker),
    )
    if not selected_entries:
        raise ValueError("no replay inputs matched ticker/policy filters")

    cases: list[dict[str, str]] = []
    for index, (resolved, replay_input, ticker) in enumerate(selected_entries, start=1):
        model_type = replay_input.model_type.strip().lower()
        case_id = _sanitize_case_id(f"{ticker}_{model_type}_{index:02d}")
        if stage_dir is not None:
            staged_path = _stage_input_file(
                source=resolved,
                destination_dir=stage_dir,
                case_id=case_id,
            )
            relative_input_path = _to_relative_path(staged_path, output_dir)
        else:
            relative_input_path = _to_relative_path(resolved, output_dir)
        cases.append({"case_id": case_id, "input_path": relative_input_path})

    payload = {
        "schema_version": "valuation_replay_manifest_v1",
        "cases": cases,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 0


def _resolve_input_paths(
    *,
    inputs: list[Path] | None,
    discover_root: Path | None,
    discover_glob: str,
    discover_recursive: bool,
) -> list[Path]:
    resolved: list[Path] = []
    for path in inputs or []:
        resolved.append(path.resolve())

    if discover_root is not None:
        root = discover_root.resolve()
        iterator: Iterable[Path]
        if discover_recursive:
            iterator = root.rglob(discover_glob)
        else:
            iterator = root.glob(discover_glob)
        resolved.extend(item.resolve() for item in iterator if item.is_file())

    unique: dict[str, Path] = {}
    for path in resolved:
        unique[str(path)] = path
    return sorted(unique.values(), key=lambda item: str(item))


def _parse_ticker_allowlist(raw: str) -> set[str]:
    tokens = {token.strip().upper() for token in raw.split(",") if token.strip()}
    return tokens


def _select_entries(
    *,
    input_paths: list[Path],
    ticker_allowlist: set[str],
    latest_per_ticker: bool,
) -> list[tuple[Path, ValuationReplayInputModel, str]]:
    entries: list[tuple[Path, ValuationReplayInputModel, str]] = []
    latest: dict[str, tuple[float, Path, ValuationReplayInputModel]] = {}

    for path in input_paths:
        schema_version = _peek_schema_version(path)
        if schema_version != "valuation_replay_input_v2":
            print(
                (
                    "[build_manifest] skip non-v2 replay input: "
                    f"{path} (schema_version={schema_version!r})"
                ),
                file=sys.stderr,
            )
            continue
        replay_input = _load_replay_input(path)
        ticker = (replay_input.ticker or "unknown").strip().upper()
        if ticker_allowlist and ticker not in ticker_allowlist:
            continue
        if latest_per_ticker:
            modified_at = path.stat().st_mtime
            current = latest.get(ticker)
            if current is None or (modified_at, str(path)) > (
                current[0],
                str(current[1]),
            ):
                latest[ticker] = (modified_at, path, replay_input)
            continue
        entries.append((path, replay_input, ticker))

    if latest_per_ticker:
        for ticker in sorted(latest):
            _, path, replay_input = latest[ticker]
            entries.append((path, replay_input, ticker))
        return entries
    return sorted(entries, key=lambda item: str(item[0]))


def _load_replay_input(path: Path) -> ValuationReplayInputModel:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return parse_valuation_replay_input_model(raw, context=f"manifest.input:{path}")


def _peek_schema_version(path: Path) -> str | None:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict):
        return None
    token = raw.get("schema_version")
    if isinstance(token, str):
        return token.strip()
    return None


def _to_relative_path(path: Path, output_dir: Path) -> str:
    return Path(os.path.relpath(path, start=output_dir)).as_posix()


def _stage_input_file(*, source: Path, destination_dir: Path, case_id: str) -> Path:
    target = destination_dir / f"{case_id}.json"
    shutil.copy2(source, target)
    return target


def _sanitize_case_id(raw: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_]+", "_", raw).strip("_")
    return normalized or "replay_case"


if __name__ == "__main__":
    raise SystemExit(main())
