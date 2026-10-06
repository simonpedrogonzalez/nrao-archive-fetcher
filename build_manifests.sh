#!/bin/sh
set -eu

cd "$(dirname "$0")"

uv run python workflows/radioastro_calibrators/build_manifests.py \
  --radioastro-root /Users/u1528314/Documents/radioastro-ml \
  --runs-root runs
