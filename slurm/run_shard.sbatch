#!/usr/bin/env bash
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --job-name=nrao-shard
# One array task = one shard. Submit through slurm/submit_shards.sh, which sets --array and the log paths.
set -euo pipefail
[[ $# -eq 2 ]] || { echo "usage: run_shard.sbatch MANIFEST N" >&2; exit 2; }
manifest=$1
shards=$2
# sbatch runs a spooled copy of this script, so work from the submit directory (the repo root).
cd "${SLURM_SUBMIT_DIR:?submit through slurm/submit_shards.sh}"
echo "Slurm job ${SLURM_ARRAY_JOB_ID}_${SLURM_ARRAY_TASK_ID} on $(hostname): shard ${SLURM_ARRAY_TASK_ID} of ${shards} for ${manifest}"
exec uv run python workflows/radioastro_calibrators/run_manifest.py "$manifest" \
    --shards "$shards" --casa "${CASA:-casa}" ${DELETE_ORIGINAL:+--delete-original}
