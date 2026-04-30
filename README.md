# nrao-archive-fetcher

Small Python tools for:

- querying the NRAO archive
- enriching rows with archive details
- building a JSON manifest
- importing `wget` commands from macOS Mail
- downloading data in project-code folders

## Install

```bash
uv sync --extra dev
```

## Python Usage

```python
import astropy.units as u

from nrao_archive_fetcher import NRAOQuery, enrich, apply_filter, build_manifest, write_manifest
from nrao_archive_fetcher import BANDS, DATAPRODS, INSTRUMENTS

q = (
    NRAOQuery()
    .where_in_circle((1.488230870833333, 38.33754126944444), 20 * u.arcsec)
    .where_instruments(INSTRUMENTS.VLA_VARIANTS())
    .where_dataproduct(DATAPRODS.VISIBILITY)
    .where_band(BANDS.C)
    .limit(10)
)

df = q.get()
df = enrich(df)
df = apply_filter(df, lambda row, details: bool(details), as_dataframe=True)
manifest = build_manifest(df, include_row=True, include_details=True, query_text=q.build())
write_manifest(manifest, "manifest.json")
```

## CLI

Show pending request links:

```bash
nrao-fetch show-pending manifest.json
```

Import `wget` commands from macOS Mail:

```bash
nrao-fetch import-email manifest.json
```

Run downloads:

```bash
nrao-fetch download manifest.json
```

## Example

Run the full example:

```bash
uv run python example.py
```
