from __future__ import annotations

import argparse
import json
import math
import shutil
from pathlib import Path

import numpy as np

try:
    from .flux_weblog import find_flux_estimate, write_flux_estimate
except ImportError:  # Direct execution by CASA: ``casa -c extract_entry.py ...``
    from flux_weblog import find_flux_estimate, write_flux_estimate


BAND_RANGES_HZ = {
    "L": (1e9, 2e9),
    "S": (2e9, 4e9),
    "C": (4e9, 8e9),
    "X": (8e9, 12e9),
    "KU": (12e9, 18e9),
    "K": (18e9, 26.5e9),
    "KA": (26.5e9, 40e9),
    "Q": (40e9, 50e9),
}
MIN_UNFLAGGED = 0.5
MIN_BANDWIDTH_HZ = 10e6


def find_first_ms(root):
    candidates = [path for path in Path(root).rglob("*.ms") if path.is_dir()]
    return sorted(candidates)[0] if candidates else None


def _read_table(table_factory, path, callback):
    table = table_factory()
    table.open(str(path))
    try:
        return callback(table)
    finally:
        table.close()


def require_corrected_data(ms_path, table_factory):
    columns = _read_table(table_factory, ms_path, lambda table: set(table.colnames()))
    if "CORRECTED_DATA" not in columns:
        raise ValueError("MeasurementSet does not contain CORRECTED_DATA")


def require_field(ms_path, field_name, table_factory):
    names = _read_table(table_factory, Path(ms_path) / "FIELD", lambda table: table.getcol("NAME"))
    if field_name not in {str(name) for name in names}:
        raise ValueError("Field %r is not present in the MeasurementSet" % field_name)


def select_spw(ms_path, band_guess, table_factory):
    def read_spws(table):
        result = []
        for spw in range(table.nrows()):
            frequencies = np.asarray(table.getcell("CHAN_FREQ", spw), dtype=float)
            if frequencies.size:
                result.append(
                    {
                        "spw": spw,
                        "f_center_hz": float(np.median(frequencies)),
                        "bandwidth_hz": float(np.max(frequencies) - np.min(frequencies)),
                    }
                )
        return result

    spws = _read_table(table_factory, Path(ms_path) / "SPECTRAL_WINDOW", read_spws)
    if not spws:
        raise ValueError("MeasurementSet has no readable spectral windows")
    data_desc_ids, flags = _read_table(
        table_factory,
        ms_path,
        lambda table: (np.asarray(table.getcol("DATA_DESC_ID")), np.asarray(table.getcol("FLAG"))),
    )
    dd_to_spw = _read_table(
        table_factory,
        Path(ms_path) / "DATA_DESCRIPTION",
        lambda table: np.asarray(table.getcol("SPECTRAL_WINDOW_ID"), dtype=int),
    )
    band = str(band_guess or "").strip().upper()
    band_range = BAND_RANGES_HZ.get(band)
    for info in spws:
        ddids = np.where(dd_to_spw == info["spw"])[0]
        row_mask = np.isin(data_desc_ids, ddids)
        info["n_rows"] = int(np.count_nonzero(row_mask))
        selected_flags = flags[:, :, row_mask]
        info["unflagged_fraction"] = (
            1.0 - float(np.count_nonzero(selected_flags)) / selected_flags.size
            if selected_flags.size else float("nan")
        )
        info["matches_band"] = bool(
            band_range and band_range[0] <= info["f_center_hz"] <= band_range[1]
        )

    matching = [info for info in spws if info["matches_band"]]
    candidates = matching or spws
    best = max(
        candidates,
        key=lambda info: (
            info["bandwidth_hz"],
            info["unflagged_fraction"] if math.isfinite(info["unflagged_fraction"]) else -1.0,
        ),
    )
    if not math.isfinite(best["unflagged_fraction"]) or best["unflagged_fraction"] < MIN_UNFLAGGED:
        raise ValueError(
            "SPW %s has unflagged fraction %.3f below %.3f"
            % (best["spw"], best["unflagged_fraction"], MIN_UNFLAGGED)
        )
    if best["bandwidth_hz"] < MIN_BANDWIDTH_HZ:
        raise ValueError(
            "SPW %s bandwidth %.3f MHz is below %.3f MHz"
            % (best["spw"], best["bandwidth_hz"] / 1e6, MIN_BANDWIDTH_HZ / 1e6)
        )
    return best


def extract_entry(entry, download_root, output_root, table_factory, split_task, listobs_task):
    entry_id = str(entry.get("entry_id") or "").strip()
    field = str(entry.get("gain_calibrator_name") or "").strip()
    if not entry_id or not field:
        raise ValueError("entry_id and gain_calibrator_name are required")
    source_ms = find_first_ms(download_root)
    if source_ms is None:
        raise FileNotFoundError("No downloaded MeasurementSet found under %s" % download_root)
    require_corrected_data(source_ms, table_factory)
    require_field(source_ms, field, table_factory)
    spw = select_spw(source_ms, entry.get("band_guess"), table_factory)

    output_dir = Path(output_root) / entry_id
    output_dir.mkdir(parents=True, exist_ok=True)
    output_ms = output_dir / (entry_id + ".ms")
    if output_ms.exists():
        shutil.rmtree(output_ms)
    split_task(
        vis=str(source_ms),
        outputvis=str(output_ms),
        field=field,
        spw=str(spw["spw"]),
        datacolumn="corrected",
        keepflags=True,
    )
    if not output_ms.is_dir():
        raise RuntimeError("CASA split did not create %s" % output_ms)
    listobs_path = output_dir / "listobs.txt"
    listobs_task(vis=str(output_ms), listfile=str(listobs_path), overwrite=True)

    flux = find_flux_estimate(download_root, field, band=entry.get("band_guess"))
    flux_path = output_dir / "flux_estimate.json"
    write_flux_estimate(flux, flux_path)
    metadata = {
        "entry_id": entry_id,
        "source_ms": str(source_ms),
        "extracted_ms": str(output_ms),
        "gain_calibrator_name": field,
        "selected_spw": str(spw["spw"]),
        "spw_center_ghz": spw["f_center_hz"] / 1e9,
        "spw_bandwidth_mhz": spw["bandwidth_hz"] / 1e6,
        "spw_unflagged_fraction": spw["unflagged_fraction"],
        "spw_matches_band": spw["matches_band"],
        "listobs": str(listobs_path),
        "flux_estimate": str(flux_path),
    }
    metadata_path = output_dir / "extraction_metadata.json"
    metadata_path.write_text(json.dumps(metadata, indent=2) + "\n")
    return metadata


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--entry-json", required=True)
    parser.add_argument("--download-root", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--result-json", required=True)
    args = parser.parse_args(argv)
    from casatasks import listobs, split
    from casatools import table

    entry = json.loads(Path(args.entry_json).read_text())
    result = extract_entry(entry, args.download_root, args.output_root, table, split, listobs)
    Path(args.result_json).write_text(json.dumps(result, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
