# CHPC storage layout for nrao-archive-fetcher. Source this file.
# Large outputs (manifests, downloads, extracted MSs, Slurm logs) live on the
# astro group storage next to radioastro-ml's data, not in $HOME.
RADIOASTRO_STORAGE=${RADIOASTRO_STORAGE:-/uufs/chpc.utah.edu/common/home/astro/tanmoy/sgonzalez/radioastroml}
export NRAO_DATA_ROOT=${NRAO_DATA_ROOT:-$RADIOASTRO_STORAGE/nrao-archive-fetcher}
export NRAO_RUNS_ROOT=${NRAO_RUNS_ROOT:-$NRAO_DATA_ROOT/runs}
export NRAO_LOG_DIR=${NRAO_LOG_DIR:-$NRAO_DATA_ROOT/logs}
export RADIOASTRO_ROOT=${RADIOASTRO_ROOT:-$HOME/radioastro-ml}
export UV_CACHE_DIR=${UV_CACHE_DIR:-$RADIOASTRO_STORAGE/.uv-cache}

# Slurm: lonepeak is a non-preemptable general cluster (3-day limit).
export NRAO_SLURM_CLUSTER=${NRAO_SLURM_CLUSTER:-lonepeak}
export NRAO_SLURM_PARTITION=${NRAO_SLURM_PARTITION:-lonepeak}
export NRAO_SLURM_ACCOUNT=${NRAO_SLURM_ACCOUNT:-laskar}
