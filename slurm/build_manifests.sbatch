#!/usr/bin/env bash
#SBATCH --job-name=nrao-build-manifests
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=4G
#SBATCH --time=3-00:00:00
# Submit with slurm/submit_build_manifests.sh (sets cluster, account, log paths).
set -euo pipefail

# sbatch runs a spooled copy of this script, so the clone path comes from the submitter.
ROOT=${NRAO_FETCHER_ROOT:?submit through slurm/submit_build_manifests.sh}
cd "$ROOT"
source slurm/env.sh

if ! type module >/dev/null 2>&1; then
    for init in /etc/profile.d/modules.sh /usr/share/Modules/init/bash; do
        [[ -r "$init" ]] && source "$init" && break
    done
fi
module load uv

export PYTHONUNBUFFERED=1
export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"
export TMPDIR="$NRAO_DATA_ROOT/tmp/$SLURM_JOB_ID"
mkdir -p "$TMPDIR"

echo "Slurm job $SLURM_JOB_ID on $(hostname -f 2>/dev/null || hostname) start=$(date -Is)"
echo "radioastro_root=$RADIOASTRO_ROOT runs_root=$NRAO_RUNS_ROOT"
status=0
uv run --no-sync python -m workflows.radioastro_calibrators.build_manifests \
  --radioastro-root "$RADIOASTRO_ROOT" \
  --runs-root "$NRAO_RUNS_ROOT" || status=$?
rm -rf "$TMPDIR"
echo "end=$(date -Is)"
exit $status
