#!/bin/sh
set -eu

cd "$(dirname "$0")"

uv run python -m workflows.radioastro_calibrators.build_manifests \
  --radioastro-root "${RADIOASTRO_ROOT:-/Users/u1528314/Documents/radioastro-ml}" \
  --runs-root "${NRAO_RUNS_ROOT:-runs}"
