#!/usr/bin/env bash
# Submit the manifest build as one single-CPU, long-running Slurm job.
# Extra arguments are passed to sbatch (e.g. --time=1-00:00:00).
set -euo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
cd "$ROOT"
source slurm/env.sh

for csv in collect/small_subset/small_selection.csv collect/vla_calibrators_one_hit_missed.csv \
           collect/vla_calibrators_one_hit.csv; do
    [[ -r "$RADIOASTRO_ROOT/$csv" ]] || { echo "Missing input: $RADIOASTRO_ROOT/$csv" >&2; exit 1; }
done
mkdir -p "$NRAO_RUNS_ROOT" "$NRAO_LOG_DIR"
[[ -w "$NRAO_RUNS_ROOT" && -w "$NRAO_LOG_DIR" ]] || { echo "Storage not writable: $NRAO_DATA_ROOT" >&2; exit 1; }

# Seed storage with the repo's manifests once, so the build resumes from them.
if [[ -z "$(ls -A "$NRAO_RUNS_ROOT")" ]]; then
    cp -r runs/. "$NRAO_RUNS_ROOT/"
fi

module load uv
uv sync --frozen

export NRAO_FETCHER_ROOT="$ROOT"
exec sbatch --clusters="$NRAO_SLURM_CLUSTER" --partition="$NRAO_SLURM_PARTITION" \
    --account="$NRAO_SLURM_ACCOUNT" \
    --output="$NRAO_LOG_DIR/%x-%j.out" --error="$NRAO_LOG_DIR/%x-%j.err" \
    "$@" "$ROOT/slurm/build_manifests.sbatch"
