#!/usr/bin/env bash
# Submit N parallel download + extraction jobs on one manifest.
#
#   slurm/submit_shards.sh runs/<group>/manifest.json N [--force] [extra sbatch options...]
#
# e.g. slurm/submit_shards.sh runs/small_remaining/manifest.json 4 --account=astro --partition=lonepeak --time=3-00:00:00
# Before submitting it: refuses if jobs for this manifest are still queued or running (--force skips the check),
# runs merge-shards, and runs sync-requests if the incoming copy exists.
# Environment: CASA=/path/to/casa (default: casa on PATH), DELETE_ORIGINAL=1 to delete raw downloads after extraction,
# INCOMING=<local manifest copy> (default: runs/<group>/incoming/manifest.local.json).
set -euo pipefail
[[ $# -ge 2 ]] || { sed -n '2,11p' "$0" >&2; exit 2; }
manifest=$1
shards=$2
shift 2
[[ -f "$manifest" ]] || { echo "manifest not found: $manifest" >&2; exit 2; }
[[ "$shards" =~ ^[1-9][0-9]*$ ]] || { echo "N must be a positive integer, got: $shards" >&2; exit 2; }
manifest=$(cd "$(dirname "$manifest")" && pwd)/$(basename "$manifest")
group_dir=$(dirname "$manifest")
group=$(basename "$group_dir")
job_name="nrao-$group"

# Split --force from the sbatch options, and remember the cluster (-M) so squeue looks in the same place.
force=0
sbatch_args=()
squeue_args=()
while [[ $# -gt 0 ]]; do
    case "$1" in
        --force) force=1 ;;
        -M|--clusters) sbatch_args+=("$1" "$2"); squeue_args+=(-M "$2"); shift ;;
        -M*) sbatch_args+=("$1"); squeue_args+=(-M "${1#-M}") ;;
        --clusters=*) sbatch_args+=("$1"); squeue_args+=(-M "${1#--clusters=}") ;;
        *) sbatch_args+=("$1") ;;
    esac
    shift
done

# 1. Never run two sets of jobs on the same shards: they would download the same entries twice.
if [[ $force -eq 0 ]]; then
    active=$(squeue -h -u "$USER" -n "$job_name" -o "%i %T" ${squeue_args[@]+"${squeue_args[@]}"} | grep -v '^CLUSTER' || true)
    if [[ -n "$active" ]]; then
        echo "Jobs named $job_name are still queued or running:" >&2
        echo "$active" >&2
        echo "Wait for them to finish (or scancel them). --force submits anyway." >&2
        exit 1
    fi
fi

cd "$(dirname "$0")/.."
# 2. Bring the progress of the previous jobs into the main manifest.
uv run --frozen nrao-fetch merge-shards "$manifest"
# 3. Bring in new links and request failures from the local (email import) copy.
incoming=${INCOMING:-$group_dir/incoming/manifest.local.json}
if [[ -f "$incoming" ]]; then
    uv run --frozen nrao-fetch sync-requests "$incoming" "$manifest"
else
    echo "[SUBMIT] no incoming copy at $incoming, skipping sync-requests"
fi

logs="$group_dir/logs"
mkdir -p "$logs"
sbatch --array="0-$((shards - 1))" \
    --job-name="$job_name" \
    --output="$logs/shard-%a-of-${shards}_%A.out" \
    --export=ALL \
    ${sbatch_args[@]+"${sbatch_args[@]}"} slurm/run_shard.sbatch "$manifest" "$shards"
