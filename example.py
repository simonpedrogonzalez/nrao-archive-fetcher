from __future__ import annotations

from pathlib import Path

import astropy.units as u

from nrao_archive_fetcher import (
    BANDS,
    DATAPRODS,
    INSTRUMENTS,
    PROPRIETARY,
    NRAOQuery,
    apply_filter,
    build_manifest,
    enrich,
    write_manifest,
)


OUT_DIR = Path("example_output")
TARGET_ACCESS_URL = "https://data.nrao.edu/portal/#/productViewer/16B-069_sb32991151_1.57709.66087045139"


def main():
    OUT_DIR.mkdir(exist_ok=True)

    query = (
        NRAOQuery()
        .where_dates(start="2016-11-16", end="2016-11-18")
        .where_in_circle((162.769906408333, -31.6373076138889), 20 * u.arcsec)
        .where_instruments(INSTRUMENTS.VLA_EVLA)
        .where_dataproduct(DATAPRODS.VISIBILITY)
        .where_band(BANDS.X)
        .where_proprietary_status(PROPRIETARY.PUBLIC)
        .limit(5)
        .unique_on("obs_publisher_did")
    )

    print("\n[1] Querying archive for the smallest example from radioastro-ml small_selection.csv")
    df = query.get()
    print(df[["project_code", "target_name", "access_url"]].head().to_string(index=False))

    print("\n[2] Enriching rows")
    df = enrich(df)
    print(df[["project_code", "detail_summary"]].head().to_string(index=False))

    print("\n[3] Keeping only the exact smallest-row archive entry")
    df = apply_filter(
        df,
        lambda row, details: bool(details) and row.get("access_url") == TARGET_ACCESS_URL,
        as_dataframe=True,
    )
    print(df[["project_code", "target_name"]].head().to_string(index=False))

    print("\n[4] Building manifest")
    manifest = build_manifest(df, include_row=True, include_details=True, query_text=query.build())
    manifest_path = OUT_DIR / "manifest.json"
    write_manifest(manifest, manifest_path)
    print(f"wrote {manifest_path}")
    print(f"entries: {len(manifest['entries'])}")


if __name__ == "__main__":
    main()
