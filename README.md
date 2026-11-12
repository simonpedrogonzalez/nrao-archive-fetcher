# nrao-archive-fetcher

Small Python tools for:

- querying the NRAO archive
- enriching rows with project/viewer details
- building a JSON manifest
- importing `wget`/`wget2` commands from macOS Mail, IMAP, or exported JSON
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

Add `--limit 10` to show only the next 10 entries. Entries whose request failed are left out. List them, with the error from the failure email, using:

```bash
uv run nrao-fetch show-pending manifest.json --failed
```

5. The previous command output shows the calibrator ID and the link to the archive. Follow the links, and request the data, setting the calibrator ID as the request name.

6. After the NRAO emails arrive, import the `wget/wget2` commands into the manifest:

```bash
uv run nrao-fetch import-email manifest.json
```

On Linux, import directly through IMAP (credentials may instead use the
`NRAO_IMAP_HOST`, `NRAO_IMAP_USERNAME`, and `NRAO_IMAP_PASSWORD` environment
variables):

```bash
uv run nrao-fetch import-email manifest.json --backend imap \
  --host imap.gmail.com --username you@example.com --password APP_PASSWORD
```

Or import a provider-independent JSON export containing a list of messages
with `message_id`, `subject`, `received_at`, and `content` fields:

```bash
uv run nrao-fetch import-email manifest.json --messages-json messages.json
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

See [example.py](example.py).

## Radioastro calibrator extraction

The project-specific workflow under `workflows/radioastro_calibrators` extracts
one requested gain-calibrator field and one qualifying spectral window from a
pipeline-calibrated MeasurementSet. It retains the original download and writes
the compact MS, `listobs.txt`, extraction metadata, and a provenance-backed
`flux_estimate.json`. Imaging is intentionally outside this workflow.

Build the four manifests from the immutable historical inputs, then resume one
manifest's downloads and CASA extraction with:

```bash
uv run python -m workflows.radioastro_calibrators.build_manifests \
  --radioastro-root /path/to/radioastro-ml --runs-root runs
uv run python -m workflows.radioastro_calibrators.run_manifest \
  runs/small_remaining/manifest.json --casa /path/to/casa
```

### Parallel downloads on CHPC (email import done locally)

```bash
# local
uv run nrao-fetch import-email runs/<group>/manifest.json
# copy it to CHPC as runs/<group>/incoming/manifest.local.json (not over the CHPC manifest), then on CHPC:
uv run nrao-fetch sync-requests runs/<group>/incoming/manifest.local.json runs/<group>/manifest.json
CASA=/path/to/casa slurm/submit_shards.sh runs/<group>/manifest.json <N> --account=... --partition=... --time=...
uv run nrao-fetch merge-shards runs/<group>/manifest.json   # after the jobs finish
```

- `sync-requests` adds new links and failures. It never touches downloaded or extracted entries, and retries failed or stuck downloads that got a new link. Interrupted downloads resume (`wget -c`).
- `submit_shards.sh` runs N jobs. Each takes every Nth entry and saves progress to `manifest.shard-<i>-of-<N>.json`. Logs go to `runs/<group>/logs/`.
- `merge-shards` copies that progress into the main manifest. Run it before resubmitting with a different N.
