#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  sync_skills.sh [options] [skill_name ...]

Options:
  --reverse            Sync from project .agent back to ~/.codex/skills
  --source <path>      Override source root
  --dest <path>        Override destination root
  --delete             Delete files in destination skill dirs not present in source
  --dry-run            Show actions without writing changes
  -h, --help           Show help

Notes:
  - Only top-level directories that contain SKILL.md are synced.
  - Hidden directories (for example .system) are ignored.
  - Non-skill directories (for example .agent/references) are not touched.
EOF
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
DEFAULT_CODEX_SKILLS="$HOME/.codex/skills"
DEFAULT_PROJECT_AGENT="$REPO_ROOT/.agent"

reverse=false
dry_run=false
delete_mode=false
source_root=""
dest_root=""

declare -a skill_names=()

while (($# > 0)); do
  case "$1" in
    --reverse)
      reverse=true
      shift
      ;;
    --source)
      source_root="${2:-}"
      shift 2
      ;;
    --dest)
      dest_root="${2:-}"
      shift 2
      ;;
    --delete)
      delete_mode=true
      shift
      ;;
    --dry-run)
      dry_run=true
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    -*)
      echo "Unknown option: $1" >&2
      usage
      exit 1
      ;;
    *)
      skill_names+=("$1")
      shift
      ;;
  esac
done

if [[ -z "$source_root" || -z "$dest_root" ]]; then
  if [[ "$reverse" == true ]]; then
    source_root="${source_root:-$DEFAULT_PROJECT_AGENT}"
    dest_root="${dest_root:-$DEFAULT_CODEX_SKILLS}"
  else
    source_root="${source_root:-$DEFAULT_CODEX_SKILLS}"
    dest_root="${dest_root:-$DEFAULT_PROJECT_AGENT}"
  fi
fi

if ! command -v rsync >/dev/null 2>&1; then
  echo "Error: rsync is required but not found in PATH." >&2
  exit 1
fi

if [[ ! -d "$source_root" ]]; then
  echo "Error: source root does not exist: $source_root" >&2
  exit 1
fi

mkdir -p "$dest_root"

declare -a targets=()

if ((${#skill_names[@]} > 0)); then
  for name in "${skill_names[@]}"; do
    if [[ -d "$source_root/$name" && -f "$source_root/$name/SKILL.md" ]]; then
      targets+=("$name")
    else
      echo "Skip (not a skill dir with SKILL.md): $source_root/$name" >&2
    fi
  done
else
  for dir in "$source_root"/*; do
    [[ -d "$dir" ]] || continue
    name="$(basename "$dir")"
    [[ "$name" == .* ]] && continue
    [[ -f "$dir/SKILL.md" ]] || continue
    targets+=("$name")
  done
fi

if ((${#targets[@]} == 0)); then
  echo "No skill directories selected for sync."
  exit 0
fi

declare -a rsync_flags=(-a)
if [[ "$delete_mode" == true ]]; then
  rsync_flags+=(--delete)
fi
if [[ "$dry_run" == true ]]; then
  rsync_flags+=(--dry-run --itemize-changes)
fi

echo "Source:      $source_root"
echo "Destination: $dest_root"
echo "Delete mode: $delete_mode"
echo "Dry run:     $dry_run"
echo "Skills:      ${targets[*]}"
echo

for name in "${targets[@]}"; do
  src="$source_root/$name/"
  dst="$dest_root/$name/"
  mkdir -p "$dest_root/$name"
  echo "Syncing: $name"
  rsync "${rsync_flags[@]}" "$src" "$dst"
done

echo
echo "Sync complete."
