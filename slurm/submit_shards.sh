#!/usr/bin/env bash
# Submit N parallel download + extraction jobs on one manifest.
#
#   slurm/submit_shards.sh runs/<group>/manifest.json N [--force] [--no-sync] [extra sbatch options...]
#
# e.g. slurm/submit_shards.sh runs/small_remaining/manifest.json 4 --time=3-00:00:00
# Before submitting it: refuses if jobs for this manifest are still queued or running (--force skips the check),
# runs merge-shards, and runs sync-requests from the incoming copy (--no-sync skips it).
# Environment: CASA=/path/to/casa (default: casa on PATH), DELETE_ORIGINAL=1 to delete raw downloads after extraction,
# INCOMING=<local manifest copy>. Default: for .../local/runs/<group>/manifest.json, .../incoming/runs/<group>/manifest.json;
# otherwise runs/<group>/incoming/manifest.local.json. A missing incoming copy is an error unless --no-sync.
# Cluster, account and partition default to NRAO_SLURM_CLUSTER/ACCOUNT/PARTITION from slurm/env.sh when not given.
set -euo pipefail
[[ $# -ge 2 ]] || { sed -n '2,13p' "$0" >&2; exit 2; }
manifest=$1
shards=$2
shift 2
[[ -f "$manifest" ]] || { echo "manifest not found: $manifest" >&2; exit 2; }
[[ "$shards" =~ ^[1-9][0-9]*$ ]] || { echo "N must be a positive integer, got: $shards" >&2; exit 2; }
manifest=$(cd "$(dirname "$manifest")" && pwd)/$(basename "$manifest")
group_dir=$(dirname "$manifest")
group=$(basename "$group_dir")
job_name="nrao-$group"

repo=$(cd "$(dirname "$0")/.." && pwd)
# Cluster/account/partition defaults, storage paths, UV_CACHE_DIR (CHPC only; the file is not in git).
[[ -f "$repo/slurm/env.sh" ]] && source "$repo/slurm/env.sh"

# Split --force/--no-sync from the sbatch options, and remember the cluster (-M) so squeue looks in the same place.
force=0
sync=1
cluster=""
has_account=0
has_partition=0
sbatch_args=()
while [[ $# -gt 0 ]]; do
    case "$1" in
        --force) force=1 ;;
        --no-sync) sync=0 ;;
        -M|--clusters) cluster=$2; shift ;;
        -M*) cluster=${1#-M} ;;
        --clusters=*) cluster=${1#--clusters=} ;;
        -A|--account|-p|--partition)
            [[ "$1" == -A || "$1" == --account ]] && has_account=1 || has_partition=1
            sbatch_args+=("$1" "$2"); shift ;;
        -A*|--account=*) has_account=1; sbatch_args+=("$1") ;;
        -p*|--partition=*) has_partition=1; sbatch_args+=("$1") ;;
        *) sbatch_args+=("$1") ;;
    esac
    shift
done
cluster=${cluster:-${NRAO_SLURM_CLUSTER:-}}
[[ $has_account -eq 0 && -n "${NRAO_SLURM_ACCOUNT:-}" ]] && sbatch_args+=(--account="$NRAO_SLURM_ACCOUNT")
[[ $has_partition -eq 0 && -n "${NRAO_SLURM_PARTITION:-}" ]] && sbatch_args+=(--partition="$NRAO_SLURM_PARTITION")
cluster_args=()
[[ -n "$cluster" ]] && cluster_args=(-M "$cluster")

# 1. Never run two sets of jobs on the same shards: they would download the same entries twice.
if [[ $force -eq 0 ]]; then
    if ! queue=$(squeue -h -u "$USER" -n "$job_name" -o "%i %T" ${cluster_args[@]+"${cluster_args[@]}"}); then
        echo "squeue failed, cannot check for running $job_name jobs. --force submits anyway." >&2
        exit 1
    fi
    active=$(grep -v '^CLUSTER' <<<"$queue" || true)
    if [[ -n "$active" ]]; then
        echo "Jobs named $job_name are still queued or running${cluster:+ on $cluster}:" >&2
        echo "$active" >&2
        echo "Wait for them to finish (or scancel them). --force submits anyway." >&2
        exit 1
    fi
fi

# 2. Find the incoming (email import) copy before changing anything.
if [[ $sync -eq 1 ]]; then
    if [[ -n "${INCOMING:-}" ]]; then
        incoming=$INCOMING
    elif [[ "$group_dir" == */local/runs/"$group" ]]; then
        incoming="${group_dir%/local/runs/$group}/incoming/runs/$group/$(basename "$manifest")"
    else
        incoming="$group_dir/incoming/manifest.local.json"
    fi
    [[ -f "$incoming" ]] || { echo "incoming copy not found: $incoming (set INCOMING, or --no-sync to skip)" >&2; exit 2; }
    [[ "$(cd "$(dirname "$incoming")" && pwd)/$(basename "$incoming")" != "$manifest" ]] \
        || { echo "incoming copy is the manifest itself: $incoming" >&2; exit 2; }
fi

cd "$repo"
# 3. Bring the progress of the previous jobs into the main manifest.
uv run --frozen nrao-fetch merge-shards "$manifest"
# 4. Bring in new links and request failures from the incoming copy.
if [[ $sync -eq 1 ]]; then
    uv run --frozen nrao-fetch sync-requests "$incoming" "$manifest"
else
    echo "[SUBMIT] --no-sync: skipping sync-requests"
fi

logs="$group_dir/logs"
mkdir -p "$logs"
sbatch --array="0-$((shards - 1))" \
    --job-name="$job_name" \
    --output="$logs/shard-%a-of-${shards}_%A.out" \
    --export=ALL \
    ${cluster_args[@]+"${cluster_args[@]}"} \
    ${sbatch_args[@]+"${sbatch_args[@]}"} slurm/run_shard.sbatch "$manifest" "$shards"
