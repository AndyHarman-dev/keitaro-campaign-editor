#!/usr/bin/env bash
# Runs every quality gate. Usage: scripts/check.sh [--fast]
#   --fast  skip mutation testing (slow); use before small commits.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
FAST="${1:-}"

echo "== backend: ruff"
cd "$ROOT/backend"
uv run ruff check app tests
echo "== backend: tests + CRAP (threshold 10)"
crapper --threshold 10 app
echo "== backend: duplication (>= 0.8)"
dryer --threshold 0.8 app
if [[ "$FAST" != "--fast" ]]; then
  echo "== backend: mutation"
  mutator --test-command "uv run pytest -q -x -p no:cacheprovider" app
fi

if [[ -d "$ROOT/frontend" ]]; then
  cd "$ROOT/frontend"
  echo "== frontend: types + lint"
  npm run --silent typecheck
  npm run --silent lint
  echo "== frontend: tests + CRAP (threshold 10)"
  crapper --threshold 10 src
  echo "== frontend: duplication (>= 0.8)"
  dryer --threshold 0.8 src
  if [[ "$FAST" != "--fast" ]]; then
    echo "== frontend: mutation"
    mutator src
  fi
fi
echo "All checks passed."
