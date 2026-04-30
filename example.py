from __future__ import annotations

import functools
import http.server
import json
import shutil
import socket
import socketserver
import threading
from pathlib import Path

import astropy.units as u

from nrao_archive_fetcher import (
    BANDS,
    CONFIGS,
    DATAPRODS,
    INSTRUMENTS,
    PROPRIETARY,
    NRAOQuery,
    apply_filter,
    build_manifest,
    download_manifest,
    enrich,
    read_manifest,
    write_manifest,
)


ROOT = Path(__file__).resolve().parent
OUT_DIR = ROOT / "example_output"
MANIFEST_PATH = OUT_DIR / "manifest.json"
DOWNLOAD_ROOT = OUT_DIR / "downloads"
LOCAL_SOURCE_DIR = OUT_DIR / "local_source"


class QuietTCPServer(socketserver.TCPServer):
    allow_reuse_address = True


def _find_free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _start_local_file_server(directory: Path):
    port = _find_free_port()
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(directory))
    server = QuietTCPServer(("127.0.0.1", port), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, port


def _print_frame(title, frame, columns):
    print("\n" + "=" * 80)
    print(title)
    print("=" * 80)
    if frame.empty:
        print("<empty>")
        return
    existing = [column for column in columns if column in frame.columns]
    print(frame[existing].to_string(index=False))


def _print_manifest_entry_summary(entry, title):
    print("\n" + "=" * 80)
    print(title)
    print("=" * 80)
    summary = {
        "project_code": entry.get("project_code"),
        "obs_id": entry.get("obs_id"),
        "date": entry.get("date"),
        "viewer_url": entry.get("viewer_url"),
        "estimated_size_gb": entry.get("estimated_size_gb"),
        "band_codes": entry.get("band_codes"),
        "array_configs": entry.get("array_configs"),
        "targets": entry.get("targets"),
        "request_status": entry.get("request_status"),
        "download_attempts": entry.get("download_attempts"),
        "download_root": entry.get("download_root"),
    }
    print(json.dumps(summary, indent=2))


def _prepare_local_download_file():
    LOCAL_SOURCE_DIR.mkdir(parents=True, exist_ok=True)
    sample_path = LOCAL_SOURCE_DIR / "sample.txt"
    sample_path.write_text("local download verification for nrao-archive-fetcher\n")
    return sample_path


def _add_demo_download_command(manifest_path: Path):
    sample_path = _prepare_local_download_file()
    server, port = _start_local_file_server(LOCAL_SOURCE_DIR)
    manifest = read_manifest(manifest_path)
    first_entry = manifest["entries"][0]
    first_entry["download_command"] = f"wget http://127.0.0.1:{port}/{sample_path.name}"
    first_entry["request_status"] = "request_ready"
    write_manifest(manifest, manifest_path)
    return server


def main():
    if OUT_DIR.exists():
        shutil.rmtree(OUT_DIR)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    DOWNLOAD_ROOT.mkdir(parents=True, exist_ok=True)

    print("\n[STEP] Querying NRAO archive")
    query = (
        NRAOQuery()
        .select(
            "obs_publisher_did",
            "project_code",
            "target_name",
            "t_min",
            "instrument_name",
            "configuration",
            "freq_min",
            "freq_max",
            "access_estsize",
            "access_url",
            "proprietary_status",
        )
        .where_dates(start="2016-09-01")
        .where_in_circle((1.488230870833333, 38.33754126944444), 20 * u.arcsec)
        .where_instruments(INSTRUMENTS.VLA_VARIANTS())
        .where_dataproduct(DATAPRODS.VISIBILITY)
        .where_configs([CONFIGS.A, CONFIGS.B, CONFIGS.C, CONFIGS.D])
        .where_band(BANDS.C)
        .where_proprietary_status(PROPRIETARY.PUBLIC)
        .limit(1)
    )
    query.save(OUT_DIR / "query.txt")
    queried = query.get(as_dataframe=True)
    _print_frame(
        "Query Results",
        queried,
        [
            "project_code",
            "obs_publisher_did",
            "target_name",
            "instrument_name",
            "configuration",
            "t_min",
            "access_estsize",
            "access_url",
        ],
    )

    print("\n[STEP] Enriching query results")
    enriched = enrich(queried, as_dataframe=True)
    detail_rows = []
    for _, row in enriched.iterrows():
        summary = row.get("detail_summary") or {}
        detail_rows.append(
            {
                "project_code": summary.get("project_code"),
                "date": summary.get("date"),
                "band_codes": summary.get("band_codes"),
                "array_configs": summary.get("array_configs"),
                "targets": summary.get("targets"),
                "estimated_size_gb": summary.get("estimated_size_gb"),
            }
        )
    import pandas as pd

    _print_frame(
        "Detail Summary",
        pd.DataFrame(detail_rows),
        ["project_code", "date", "band_codes", "array_configs", "targets", "estimated_size_gb"],
    )

    print("\n[STEP] Applying a simple filter")
    filtered = apply_filter(
        enriched,
        lambda row, details: bool(details) and bool((row.get("detail_summary") or {}).get("project_code")),
        as_dataframe=True,
    )
    _print_frame(
        "Filtered Results",
        filtered,
        ["project_code", "target_name", "access_url"],
    )
    if filtered.empty:
        raise RuntimeError("Example filter removed every row; cannot continue.")

    print("\n[STEP] Building and writing manifest")
    manifest = build_manifest(filtered, include_row=True, include_details=True, query_text=query.build())
    write_manifest(manifest, MANIFEST_PATH)
    _print_manifest_entry_summary(manifest["entries"][0], "Manifest Entry Summary")

    print("\n[STEP] Preparing a local download command for pipeline verification")
    server = _add_demo_download_command(MANIFEST_PATH)
    try:
        print("\n[STEP] Running downloader")
        download_manifest(MANIFEST_PATH, base_download_root=DOWNLOAD_ROOT)
    finally:
        server.shutdown()
        server.server_close()

    final_manifest = read_manifest(MANIFEST_PATH)
    first_entry = final_manifest["entries"][0]
    _print_manifest_entry_summary(first_entry, "Final Manifest Entry Summary")

    download_dir = Path(first_entry["download_root"])
    print("\n[STEP] Download directory contents")
    for path in sorted(download_dir.rglob("*")):
        rel = path.relative_to(download_dir)
        kind = "dir" if path.is_dir() else "file"
        print(f"{kind}: {rel}")


if __name__ == "__main__":
    main()
