# nrao-archive-fetcher

Small Python tools for:

- querying the NRAO archive
- enriching rows with project/viewer details
- building a JSON manifest
- importing `wget`/`wget2` commands from macOS Mail
- downloading data

## Install

```bash
uv sync --extra dev
```

## Workflow

1. Query the archive with `NRAOQuery()`.
   Query columns are the NRAO TAP / ObsCore columns documented here:
   [Scripted Access to the NRAO Archive](https://science.nrao.edu/facilities/vla/archive/scripted-access-to-the-nrao-archive)

2. Enrich the query rows with `enrich(df)`.
   This uses the NRAO viewer products behind pages like:
   [NRAO Archive Viewer](https://data.nrao.edu)
   and product URLs like `https://data.nrao.edu/portal/#/productViewer/<ID>`.

3. Filter the rows you want and write a manifest.

4. Print the pending request links:

```bash
uv run nrao-fetch show-pending manifest.json
```

5. The previous command output shows the links to the archive and the project id. Follow the links, and request the data, setting the project id as the request name.

6. After the NRAO emails arrive, import the `wget/wget2` commands into the manifest:

```bash
uv run nrao-fetch import-email manifest.json
```

7. Download the data:

```bash
uv run nrao-fetch download manifest.json
```

## Python Example

```python
import astropy.units as u

from nrao_archive_fetcher import NRAOQuery, enrich, apply_filter, build_manifest, write_manifest
from nrao_archive_fetcher import BANDS, DATAPRODS, INSTRUMENTS

q = (
    NRAOQuery()
    .where_in_circle((1.488230870833333, 38.33754126944444), 20 * u.arcsec)
    .where_instruments(INSTRUMENTS.VLA_EVLA)
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

## Same Flow Without CLI

A full python workflow allows additional options.

```python
from nrao_archive_fetcher import read_manifest, print_pending, import_email_commands, download_manifest
```

Show pending links:

```python
from nrao_archive_fetcher import print_pending
print_pending('manifest.json')
```

Import email commands:

```python
from nrao_archive_fetcher import import_email_commands
import_email_commands('manifest.json')
```

Download with optional hooks:

```python
def before_download(entry):
    print("starting", entry["project_code"])

def after_download(entry, downloaded_path):
    print("done", entry["project_code"], downloaded_path)

download_manifest(
    "manifest.json",
    before_download=before_download,
    after_download=after_download,
)
```

## Example

See [example.py](/Users/u1528314/repos/nrao-archive-fetcher/example.py).
