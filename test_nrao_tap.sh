#!/bin/sh
set -eu

cd "$(dirname "$0")"

uv run python -c "from workflows.radioastro_calibrators.build_manifests import ensure_archive_available; ensure_archive_available(); print('NRAO TAP is working')"
