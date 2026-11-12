# NRAO calibrator manifests (snapshot 2026-11-10)

Copies of the live manifests from `$NRAO_RUNS_ROOT/<group>/manifest.json`
(`/uufs/chpc.utah.edu/common/home/astro/tanmoy/sgonzalez/radioastroml/nrao-archive-fetcher/runs/`),
built by `nrao-archive-fetcher` `workflows/radioastro_calibrators/build_manifests.py`,
Slurm job 9683064 on lonepeak (completed 2026-11-09). Entries are sorted by
`estimated_size_gb`, smallest first. One entry = one MS (NRAO estimated download size).

| Group | MSs | Total | Mean / MS |
|---|---|---|---|
| small_remaining | 81 | 0.63 TB | 7.7 GB |
| missing_no_date | 37 | 0.78 TB | 21.0 GB |
| large_original | 192 | 8.26 TB | 43.0 GB |
| repeated_up_to_3 | 843 | 25.65 TB | 30.4 GB |

- small_remaining / large_original: from the original selection CSVs (all >= 2016-09-01).
- missing_no_date / repeated_up_to_3: fresh archive search with no date filter, so they
  include pre-2016-09-01 observations (10 and 156 entries) and lack `date_utc`.
  May be rebuilt with a date cutoff (and possibly a size cap).
- Transient failures not yet retried: 1925+211 (missing_no_date), 0726+791 (repeated_up_to_3).
- Snapshot only: download/extraction status is tracked in the live manifests, not here.
