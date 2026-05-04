# Generic NRAO Archive Fetcher Plan

This document is the concrete implementation plan for turning the copied `radioastro-ml` archive-fetching workflow into a reusable Python package in this repo.

Official archive-column reference reviewed:

- NRAO scripted archive access docs:
  - [Scripted Access to the NRAO Archive](https://science.nrao.edu/facilities/vla/archive/scripted-access-to-the-nrao-archive)
  - [NRAO Data Archive](https://science.nrao.edu/facilities/vla/archive/index)

## Reference Material

Copied, unchanged reference code lives in:

- `/Users/u1528314/repos/nrao-archive-fetcher/reference/radioastro_ml_collect/collect`
- `/Users/u1528314/repos/nrao-archive-fetcher/reference/radioastro_ml_scripts/scripts/extraction_pipeline.py`

How to treat these references:

- `collect/fetcher.py` should be reused mostly as-is because it already works and is the cleanest query core.
- `collect/product_details.py` is the main reference for fetching and summarizing archive details.
- `collect/build_archive_list.py` is the main reference for the query -> enrich -> filter -> manifest workflow.
- `collect/import_outlook_wget.py` is only a reference for how to extract `wget` commands and match them to rows.
- `scripts/extraction_pipeline.py` is only a reference for how downloading/extracting/filtering currently happens downstream.
  It should not be ported literally into the package.
  It is useful mainly to show:
  - how the downloaded files are handled
  - what sort of filtering a user may want to apply after download
  - what kind of before/after callback hooks the generic package should support

## Main Goal

Build a generic archive fetcher package for NRAO archive workflows that supports:

1. programmatic archive querying
2. optional detail enrichment per archive row
3. simple user filtering over query rows and enriched details
4. JSON manifest creation
5. printing pending manual request URLs
6. gathering `wget`/`wget2` commands from email and updating the manifest
7. orderly downloading with progress/messages
8. user hooks before and after each download

This package should not be tied to the calibrator-specific workflow.

## Core Decisions

### Manifest Format

Use JSON, not CSV, not parquet, not JSONL for the main manifest.

Reason:

- it must be human-readable
- some fields are naturally nested and lengthy
- query rows and details payloads are not very tabular
- users may want to preserve the full original row and full details JSON

Recommended manifest shape:

- a top-level JSON object
- with metadata and a list of entries

Example:

```json
{
  "version": 1,
  "created_at": "2026-04-29T12:00:00Z",
  "source": {
    "tap_url": "https://data-query.nrao.edu/tap",
    "query_text": "SELECT TOP 10 * FROM ..."
  },
  "entries": [
    {
      "project_code": "24B-465",
      "obs_id": "24B-465.sb47226343.eb47329790.60643.9672167824",
      "date": "2024-11-29",
      "viewer_url": "https://data.nrao.edu/portal/#/productViewer/24B-465.sb47226343.eb47329790.60643.9672167824",
      "estimated_size_gb": 9.223,
      "band_codes": ["C"],
      "array_configs": ["A"],
      "targets": ["J0005+3820"],
      "request_status": "",
      "request_submitted_at": null,
      "request_finished_at": null,
      "download_command": "",
      "download_attempts": 0,
      "download_root": null,
      "row": { "...": "full query row if included" },
      "details": { "...": "full details payload if included" }
    }
  ]
}
```

### Data Presentation Default

`as_dataframe` should default to `True`.

The package should still preserve raw nested data, but default user-facing results should be tables when possible.

Recommended behavior:

- query methods return `pandas.DataFrame` by default
- enrichment methods return a `DataFrame` by default
- nested JSON-like data can live inside object columns such as:
  - `row`
  - `details`
  - `detail_summary`

### Filtering API

Keep filtering simple.

Use one main filter callback shape:

- `filter_fn(row, details) -> bool`

Rules:

- `row` is the archive query row as a dict-like object
- `details` is the detail payload as a dict-like object, or `None` if not enriched
- if `filter_fn` returns `True`, keep the entry
- if `False`, discard it

This one function should be usable:

- right after querying
- after detail enrichment
- during manifest construction if needed

No more callback taxonomy than necessary.

### Download Hooks

Support two user hooks in the download pipeline:

- `before_download(entry) -> None`
- `after_download(entry, downloaded_path) -> None`

Where:

- `entry` is the manifest entry dict
- `downloaded_path` is the path to the downloaded data folder for that entry

These hooks are where users can do custom filtering/extraction/cleanup/imaging.

## What To Reuse From `fetcher.py`

Use `reference/radioastro_ml_collect/collect/fetcher.py` as the main foundation.

Keep or expose:

- `TAP_URL`
- `date_to_mjd`
- `mjd_to_iso`
- `TimeSpan`
- `TIMESPANS`
- `PROPRIETARY`
- `INSTRUMENTS`
- `DATAPRODS`
- `CONFIGS`
- `Band`
- `BANDS`
- `COLS`
- ObsCore table discovery
- column discovery
- the fluent `NRAOQuery` builder

Adjustments allowed:

- reorganize into better module structure
- add save/load query text helpers
- add logging/progress messages
- remove example code from the module body

But the builder style should stay:

```python
q = (
    NRAOQuery()
    .where_timespan(TIMESPANS.FROM_2016_SEP)
    .where_in_circle((ra_deg, dec_deg), 20 * u.arcsec)
    .where_instruments(INSTRUMENTS.VLA_EVLA)
    .where_dataproduct(DATAPRODS.VISIBILITY)
    .where_band(BANDS.C)
    .limit(25)
)
```

Important:

- replace the current constructor `limit` parameter with a `.limit()` method
- default limit should be `10`

## Query Interface

The main query interface should be the fluent builder.

### Fluent Builder

Keep the current `NRAOQuery()` style from `fetcher.py`.

Required methods:

- `.select(*cols)`
- `.where_timespan(span)`
- `.where_dates(start=None, end=None)`
- `.where_in_circle(center, radius)`
- `.where_instruments(instruments)`
- `.where_dataproduct(dataproduct_type)`
- `.where_band(band)`
- `.where_configs(configs)`
- `.where_proprietary_status(status)`
- `.order_by(expr)`
- `.limit(n)`
- `.build()`
- `.get(as_dataframe=True)`

Also add:

- `.save(path)` to write the ADQL query text to a `.txt` file
- `NRAOQuery.load(path)` to create a query object from saved raw ADQL text

If loading raw text into the full builder object is awkward, a separate raw-query wrapper is fine, as long as the query text can be easily saved and loaded.

## Query Result And Enrichment Presentation

Be careful with how results are represented after enrichment.

Recommended approach:

- query result: DataFrame of flat archive rows
- enrich result: DataFrame with the same flat columns plus nested object columns

Recommended enriched columns:

- `details`
  - full details JSON payload or `None`
- `detail_summary`
  - small dict of selected useful fields

Do not introduce `*_best` or any similar “resolved/best” convenience fields.

Rule:

- if a value exists in the query row and that already solves the need, use the query row
- otherwise use the details payload

That keeps the behavior obvious and avoids unnecessary extra naming.

This keeps the output readable in a table while still preserving the full payload.

## Manifest Policy

### Manifest Writing

Provide a simple method like:

- `write_manifest(entries, path, include_row=True, include_details=True)`

### What The Manifest Should Keep

For each entry, always keep mandatory basics:

- `project_code`
- `date`
- `viewer_url`
- `obs_id`
- `estimated_size_gb` or equivalent size estimate
- `band_codes`
- `array_configs`
- `targets`

Also keep the download workflow fields:

- `request_status`
- `request_submitted_at`
- `request_finished_at`
- `download_command`
- `download_attempts`
- `download_root`

Also keep:

- `row` if `include_row=True`
- `details` if `include_details=True`

No need for fine-grained field-selection configuration beyond that in the first implementation.

## Manifest Entry Schema

Provide schemas in code and documentation so users know roughly what may be present.

These schemas should:

- make all listed fields optional
- allow extra keys
- serve as guidance rather than strict restriction

Recommended schema-like typed structures:

- `ArchiveQueryRow`
- `ArchiveDetailsPayload`
- `ManifestEntry`
- `ManifestDocument`

### `ArchiveQueryRow`

Do not invent a disconnected row schema.

Base `ArchiveQueryRow` directly on the official NRAO TAP/ObsCore fields already reflected in `fetcher.py` `COLS` and in the NRAO scripted-access docs.

At minimum, document these as the expected known fields:

- `obs_publisher_did`
- `project_code`
- `target_name`
- `t_min`
- `t_max`
- `t_exptime`
- `instrument_name`
- `configuration`
- `dataproduct_type`
- `freq_min`
- `freq_max`
- `em_min`
- `em_max`
- `s_ra`
- `s_dec`
- `access_estsize`
- `access_url`
- `access_format`
- `proprietary_status`
- `pol_states`
- `calib_level`
- `num_antennas`
- `max_uv_dist`
- `spw_names`
- `center_frequencies`
- `bandwidths`
- `nums_channels`
- `spectral_resolutions`
- `aggregate_bandwidth`

The package should expose these from a dedicated constants file so users can inspect them directly.

Schema example:

```python
class ArchiveQueryRow(TypedDict, total=False):
    obs_publisher_did: str
    project_code: str
    target_name: str
    t_min: float
    t_max: float
    t_exptime: float
    instrument_name: str
    dataproduct_type: str
    access_format: str
    access_estsize: float
    access_url: str
    proprietary_status: str
    configuration: str
    freq_min: float
    freq_max: float
    em_min: float
    em_max: float
    s_ra: float
    s_dec: float
    access_format: str
    pol_states: str
    calib_level: int
    num_antennas: int
    max_uv_dist: float
    spw_names: str
    center_frequencies: str
    bandwidths: str
    nums_channels: str
    spectral_resolutions: str
    aggregate_bandwidth: float
```

### `ArchiveDetailsPayload`

Define this from the actual shape in `reference/radioastro_ml_collect/collect/example_details.json`.

It should explicitly document the main top-level/container pieces we know about from the example and `product_details.py`, especially:

- `details`
- inside that, `execution_blocks`
- inside execution blocks, things like:
  - `sdm_id`
  - `project_code`
  - `instrument_name`
  - `configuration`
  - `band_code`
  - `cal_status`
  - `cals`
  - `configurations`
  - `scan_rows`

Schema example:

```python
class ArchiveDetailsPayload(TypedDict, total=False):
    details: dict[str, Any]
```

```python
class ArchiveDetailsContainer(TypedDict, total=False):
    execution_blocks: list["ArchiveExecutionBlock"]
```

```python
class ArchiveExecutionBlock(TypedDict, total=False):
    sdm_id: str
    project_code: str
    instrument_name: str
    configuration: str
    band_code: str
    cal_status: str
    cals: list[dict[str, Any]]
    configurations: list[dict[str, Any]]
    scan_rows: list[dict[str, Any]]
```

```python
class ManifestEntry(TypedDict, total=False):
    project_code: str
    obs_id: str
    date: str
    viewer_url: str
    estimated_size_gb: float
    band_codes: list[str]
    array_configs: list[str]
    targets: list[str]
    request_status: str
    request_submitted_at: str | None
    request_finished_at: str | None
    download_command: str
    download_attempts: int
    download_root: str | None
    row: dict[str, Any]
    details: dict[str, Any]
```

## Manual Request Stage

Keep this very simple.

Provide one plain function:

- `print_pending(manifest_path)`

What it should print per pending entry:

- project code
- request/viewer URL

That is all.

No browser automation is needed in the core plan.

## Email Command Import

Do not build Outlook-specific logic into the public interface.

Expose one main function:

- `import_email_commands(manifest_path, gather_mode="mac_mail_app")`

Behavior:

- gather `wget`/`wget2` commands
- match them to manifest entries
- update `download_command`
- update request status metadata if appropriate
- save the manifest back

Gathering modes:

- `mac_mail_app`
  - implemented
- any other value
  - raise `NotImplementedError`

Internally, `import_outlook_wget.py` can still be used as a reference for parsing and matching logic, but the public package should present a simpler single entry point.

## Download Workflow

### Folder Naming

The download folder name should be the short `project_code`, not the long obs/block id.

Example:

- `24B-465`
- not `24B-465.sb47226343.eb47329790.60643.9672167824`

If there are collisions later, that can be solved with a suffix, but the first implementation should use project code as requested.

### Pre-Download Metadata Write

Before starting each download:

- create the project folder
- write the manifest entry JSON into that folder

Recommended filename:

- `manifest_entry.json`

### Download State Fields

These manifest fields are sufficient for the first implementation:

- `request_status`
- `request_submitted_at`
- `request_finished_at`
- `download_command`
- `download_attempts`
- `download_root`

Use `request_status` as the general status field for the request/download lifecycle.

Possible values can be simple strings like:

- `pending_request`
- `request_submitted`
- `request_ready`
- `downloading`
- `downloaded`
- `error`

### Download Implementation

This part should be built fresh, but informed by:

- `collect/import_outlook_wget.py`
- `scripts/extraction_pipeline.py`

Key requirements:

- run downloads in an orderly way
- print clear progress/messages
- increment `download_attempts`
- set `download_root`
- update `request_status`
- update `request_finished_at` on both success and error
- support `wget` and `wget2`
- support `before_download(entry)` and `after_download(entry, downloaded_path)`

The `after_download` hook is where users can implement custom processing such as:

- extracting specific files
- splitting/filtering MS data
- deleting unwanted data
- imaging or QA

That is exactly the kind of workflow currently shown in `scripts/extraction_pipeline.py`, but it should stay user-owned rather than baked into the fetcher core.

## Progress And User Feedback

This is important and required.

Whenever possible, show progress bars or clear status messages.

At minimum:

- querying:
  - show table detection / query execution / row counts
- enriching:
  - show which entry is being enriched and how many are done
- manifest writing:
  - show output path and number of entries
- email import:
  - show number of messages scanned, commands found, entries updated
- downloading:
  - show which project is being downloaded
  - show attempt count
  - show destination folder
  - stream command output if reasonable
  - show completion or error

If a true progress bar is not practical, print progress messages.

## Proposed Package Layout

Recommended layout:

```text
src/nrao_archive_fetcher/
  __init__.py
  query.py
  details.py
  manifest.py
  email.py
  download.py
  schemas.py
  constants.py
  progress.py
  utils.py
  cli/
    __init__.py
    main.py
tests/
```

Module responsibilities:

- `query.py`
  - mostly adapted `fetcher.py`
  - fluent query builder
  - query save/load helpers
  - raw ADQL execution

- `details.py`
  - detail fetching and summary extraction

- `manifest.py`
  - JSON manifest read/write/update
  - manifest entry normalization
  - request printing

- `email.py`
  - email gathering and command import

- `download.py`
  - orderly downloader with hooks and state updates

- `schemas.py`
  - schema-like typed definitions for rows/details/manifest

- `constants.py`
  - all exposed columns and option constants from `fetcher.py`
  - this is where the user can inspect available columns/options

- `progress.py`
  - progress bars or fallback progress logging

## Public API Sketch

Keep the package API mostly functional.

Preferred public API shape:

- `NRAOQuery`
- `enrich(...)`
- `apply_filter(...)`
- `build_manifest(...)`
- `write_manifest(...)`
- `read_manifest(...)`
- `print_pending(...)`
- `import_email_commands(...)`
- `download_manifest(...)`

Example:

```python
from nrao_archive_fetcher import NRAOQuery, enrich, apply_filter, build_manifest, write_manifest
from nrao_archive_fetcher import BANDS, DATAPRODS, INSTRUMENTS

q = (
    NRAOQuery()
    .where_in_circle((ra_deg, dec_deg), 20 * u.arcsec)
    .where_instruments(INSTRUMENTS.VLA_EVLA)
    .where_dataproduct(DATAPRODS.VISIBILITY)
    .where_band(BANDS.C)
    .limit(25)
)

df = q.get()
df2 = enrich(df)
df3 = apply_filter(df2, filter_fn=my_filter)

manifest = build_manifest(
    df3,
    include_row=True,
    include_details=True,
)

write_manifest(manifest, "manifest.json")
```

Low-level query-builder usage should still work:

```python
q = (
    NRAOQuery()
    .where_instruments(["VLA", "EVLA"])
    .where_dataproduct("visibility")
    .limit(10)
)

q.save("query.txt")
df = q.get()
```

## CLI Scope

Do not provide CLI commands for query, enrich, or build-manifest.

The user should do those from Python scripts.

CLI commands to implement:

- `nrao-fetch show-pending <manifest.json>`
- `nrao-fetch import-email <manifest.json>`
- `nrao-fetch download <manifest.json>`

Each CLI command should print clear progress/messages.

## Implementation Order

1. Create package scaffold under `src/nrao_archive_fetcher`.
2. Port `fetcher.py` into `query.py`, keeping its structure mostly intact.
3. Move columns/constants/options into `constants.py` and expose them publicly.
4. Port `product_details.py` into `details.py`.
5. Define schema-like types in `schemas.py` based on `COLS` and `example_details.json`.
6. Implement JSON manifest logic in `manifest.py`.
7. Implement `enrich(...)`, `apply_filter(...)`, `build_manifest(...)`, and `write_manifest(...)` as plain functions.
8. Implement email command import with `gather_mode="mac_mail_app"`.
9. Implement downloader with pre-write of entry JSON, hooks, and state updates.
10. Implement the three CLI commands.
11. Add progress/logging support everywhere.

## Testing Priorities

Add tests for:

- query builder ADQL generation
- query save/load to text
- details URL parsing and JSON fetching helpers
- enriched DataFrame shape and nested data handling
- manifest JSON read/write/update
- `filter_fn(row, details)` behavior
- email command extraction and manifest update
- download state transitions
- pre-download `manifest_entry.json` creation
- before/after callback invocation

Prefer fixtures over live network calls wherever possible.

## Non-Goals

Not part of the first implementation:

- imaging pipeline integration
- hard-coded MS filtering logic
- Outlook-specific public interface
- browser automation for manual request submission
- multiple manifest storage formats

The package should enable those workflows through hooks and user code, not absorb them into the core.
