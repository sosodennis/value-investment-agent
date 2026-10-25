#!/bin/sh
set -eu

usage() {
  echo "Usage: $0 <retired-value-investment-agent-compose-project>" >&2
  exit 2
}

[ "$#" -eq 1 ] || usage
project="$1"
case "$project" in
  value-investment-agent-*) ;;
  *) echo "Refusing project outside value-investment-agent-* namespace: $project" >&2; exit 2 ;;
esac

containers="$(docker ps -aq --filter "label=com.docker.compose.project=${project}")"
if [ -n "$containers" ]; then
  echo "Refusing to remove caches while project containers exist: $project" >&2
  echo "Stop/remove that project's containers with: docker compose -p '$project' down" >&2
  exit 1
fi

removed=0
for cache in hf_cache inference_news_hf_cache inference_fls_hf_cache; do
  volumes="$(docker volume ls -q \
    --filter "label=com.docker.compose.project=${project}" \
    --filter "label=com.docker.compose.volume=${cache}")"
  for volume in $volumes; do
    volume_project="$(docker volume inspect -f '{{ index .Labels "com.docker.compose.project" }}' "$volume")"
    volume_kind="$(docker volume inspect -f '{{ index .Labels "com.docker.compose.volume" }}' "$volume")"
    if [ "$volume_project" = "$project" ] && [ "$volume_kind" = "$cache" ]; then
      docker volume rm "$volume"
      removed=$((removed + 1))
    fi
  done
done

echo "Removed $removed disposable model cache volume(s) for $project."
