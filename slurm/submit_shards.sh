#!/usr/bin/env bash
# Submit N parallel download + extraction jobs on one manifest.
#
#   slurm/submit_shards.sh runs/small_remaining/manifest.json 4 [extra sbatch options...]
#
# e.g. slurm/submit_shards.sh runs/small_remaining/manifest.json 4 --account=astro --partition=lonepeak --time=3-00:00:00
# Environment: CASA=/path/to/casa (default: casa on PATH), DELETE_ORIGINAL=1 to delete raw downloads after extraction.
# When all jobs finish, run: uv run nrao-fetch merge-shards <manifest>
set -euo pipefail
[[ $# -ge 2 ]] || { sed -n '2,9p' "$0" >&2; exit 2; }
manifest=$1
shards=$2
shift 2
[[ -f "$manifest" ]] || { echo "manifest not found: $manifest" >&2; exit 2; }
[[ "$shards" =~ ^[1-9][0-9]*$ ]] || { echo "N must be a positive integer, got: $shards" >&2; exit 2; }
manifest=$(cd "$(dirname "$manifest")" && pwd)/$(basename "$manifest")
cd "$(dirname "$0")/.."
logs="$(dirname "$manifest")/logs"
mkdir -p "$logs"
sbatch --array="0-$((shards - 1))" \
    --output="$logs/shard-%a-of-${shards}_%A.out" \
    --export=ALL \
    "$@" slurm/run_shard.sbatch "$manifest" "$shards"
