# CHPC storage layout for nrao-archive-fetcher. Source this file.
# Large outputs (manifests, downloads, extracted MSs, Slurm logs) live on the
# astro group storage inside radioastro-ml's data folder, not in $HOME.
RADIOASTRO_STORAGE=${RADIOASTRO_STORAGE:-/uufs/chpc.utah.edu/common/home/astro/tanmoy/sgonzalez/radioastroml}
export NRAO_DATA_ROOT=${NRAO_DATA_ROOT:-$RADIOASTRO_STORAGE/data/nrao-archive-fetcher}
export NRAO_RUNS_ROOT=${NRAO_RUNS_ROOT:-$NRAO_DATA_ROOT/runs}
export NRAO_LOG_DIR=${NRAO_LOG_DIR:-$NRAO_DATA_ROOT/logs}
# Incoming (email import) request copies: <root>/<group>/manifest.json, kept apart from the live manifests.
export NRAO_INCOMING_ROOT=${NRAO_INCOMING_ROOT:-$RADIOASTRO_STORAGE/reports/manifests/incoming/runs}
export RADIOASTRO_ROOT=${RADIOASTRO_ROOT:-$HOME/radioastro-ml}
export UV_CACHE_DIR=${UV_CACHE_DIR:-$RADIOASTRO_STORAGE/.uv-cache}

# Slurm: lonepeak is a non-preemptable general cluster (3-day limit).
export NRAO_SLURM_CLUSTER=${NRAO_SLURM_CLUSTER:-lonepeak}
export NRAO_SLURM_PARTITION=${NRAO_SLURM_PARTITION:-lonepeak}
export NRAO_SLURM_ACCOUNT=${NRAO_SLURM_ACCOUNT:-laskar}
