#!/usr/bin/env bash
# Phase 1 CLI: render a Markdown file to PDF and print it via the dockerized CUPS.
#
# Usage:  bin/print-md.sh [--printer Q] [OPTIONS...] FILE
# Example: bin/print-md.sh sample.md
#          bin/print-md.sh --printer brother-hl2350dw --page-size a4 --copies 2 sample.md
set -euo pipefail

cd "$(dirname "$0")/.."

COMPOSE_NET="print-mcp_print-backend"
IMAGE="print-mcp-mcp"

if ! docker network inspect "$COMPOSE_NET" >/dev/null 2>&1; then
  echo "error: CUPS network $COMPOSE_NET not found; run: docker compose up -d cups" >&2
  exit 1
fi

if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
  echo "building $IMAGE ..." >&2
  docker compose build mcp
fi

if ! docker compose ps cups --status running --format '{{.Name}}' | grep -q .; then
  echo "error: CUPS container is not running; run: docker compose up -d cups" >&2
  exit 1
fi

# Locate the input markdown file: the last argument that names an existing file.
file_arg=""
_args=("$@")
for ((i = ${#_args[@]} - 1; i >= 0; i--)); do
  cand="${_args[$i]}"
  if [[ "$cand" != -* && -f "$cand" ]]; then
    file_arg="$cand"
    break
  fi
done
if [[ -z "$file_arg" ]]; then
  echo "error: no input Markdown file given" >&2
  exit 2
fi
file_abs="$(realpath "$file_arg")"
if [[ ! -f "$file_abs" ]]; then
  echo "error: no such file: $file_abs" >&2
  exit 2
fi
mount_dir="$(dirname "$file_abs")"

# Rewrite the positional file to its name relative to the mounted directory.
args=()
for arg in "$@"; do
  if [[ "$arg" == "$file_arg" ]]; then
    args+=("$(basename "$file_abs")")
  else
    args+=("$arg")
  fi
done

docker run --rm \
  --network "$COMPOSE_NET" \
  -v "$mount_dir":/work -w /work \
  -v "$PWD":/app-repo:ro \
  --user 0 \
  --env-file .env \
  -e CUPS_SERVER=cups -e CUPS_PORT=631 -e DEFAULT_PRINTER=brother-hl2350dw \
  --entrypoint python \
  "$IMAGE" \
  /app-repo/cli/print_file.py "${args[@]}"