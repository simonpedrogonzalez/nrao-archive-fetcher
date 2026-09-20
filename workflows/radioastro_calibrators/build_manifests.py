from __future__ import annotations

import argparse
import csv
import math
import re
from collections import Counter
from pathlib import Path

import astropy.units as u
from astropy.coordinates import SkyCoord

from nrao_archive_fetcher import BANDS, DATAPRODS, INSTRUMENTS, NRAOQuery, PROPRIETARY
from nrao_archive_fetcher.details import extract_sdm_id_from_access_url, fetch_product_details
from nrao_archive_fetcher.manifest import read_manifest, write_manifest
from nrao_archive_fetcher.utils import now_iso
from workflows.radioastro_calibrators.downloaded_inventory import (
    ALREADY_DOWNLOADED_OBS_IDS,
    DOWNLOADED_BY_OBS_ID,
)


class TransientArchiveError(RuntimeError):
    pass


def read_csv(path):
    with Path(path).open(newline="") as handle:
        return list(csv.DictReader(handle))


def _text(value):
    return str(value or "").strip()


def _float(value):
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def _obs_id(row):
    url = _text(row.get("access_url") or row.get("viewer_url"))
    if url:
        try:
            return extract_sdm_id_from_access_url(url)
        except ValueError:
            pass
    return _text(row.get("obs_id")) or None


def _project_code(obs_id, row):
    value = _text(row.get("project_code"))
    return value or re.split(r"(?:\.sb|_sb)", obs_id, maxsplit=1, flags=re.IGNORECASE)[0]


def safe_entry_id(calibrator_id, obs_id):
    return re.sub(r"[^A-Za-z0-9+_.-]+", "_", "%s_%s" % (calibrator_id, obs_id)).strip("_.")


def parse_configs(value):
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [item.strip() for item in _text(value).split(",") if item.strip()]


def entry_from_values(
    calibrator_id,
    obs_id,
    project_code,
    gain_calibrator_name,
    viewer_url,
    estimated_size_gb,
    band_guess,
    usable_configs,
    **extra
):
    entry_id = safe_entry_id(calibrator_id, obs_id)
    entry = {
        "entry_id": entry_id,
        "obs_id": obs_id,
        "project_code": project_code,
        "calibrator_id": calibrator_id,
        "gain_calibrator_name": gain_calibrator_name,
        "viewer_url": viewer_url,
        "estimated_size_gb": estimated_size_gb,
        "band_guess": band_guess,
        "usable_configs": list(usable_configs),
        "request_status": "",
        "download_command": "",
        "download_root": None,
        "extracted_ms": None,
        "selected_spw": None,
        "flux_estimate": None,
    }
    entry.update(extra)
    return entry


def entry_from_historical(row, provenance=None, usable_configs=None):
    calibrator_id = _text(row.get("name") or row.get("calibrator_id"))
    obs_id = _obs_id(row)
    if not calibrator_id or calibrator_id == "z" or not obs_id:
        return None
    return entry_from_values(
        calibrator_id=calibrator_id,
        obs_id=obs_id,
        project_code=_project_code(obs_id, row),
        gain_calibrator_name=_text(row.get("gain_calibrator_name")),
        viewer_url=_text(row.get("access_url") or row.get("viewer_url")),
        estimated_size_gb=_float(row.get("size_gb") or row.get("estimated_size_gb")),
        band_guess=_text(row.get("band_guess") or row.get("band_code")),
        usable_configs=(
            usable_configs
            if usable_configs is not None
            else parse_configs(row.get("usable_configs") or row.get("gain_array_config") or row.get("configs"))
        ),
        ra=_text(row.get("ra")),
        dec=_text(row.get("dec")),
        date_utc=_text(row.get("date_utc")) or None,
        provenance=provenance,
    )


def sort_entries(entries):
    return sorted(
        entries,
        key=lambda entry: (
            entry.get("estimated_size_gb") is None,
            entry.get("estimated_size_gb") if entry.get("estimated_size_gb") is not None else math.inf,
            entry["obs_id"],
        ),
    )


def new_manifest(stage, source_path, entries=None):
    return {
        "version": 1,
        "created_at": now_iso(),
        "source": {
            "stage": stage,
            "source_path": str(Path(source_path).resolve()) if source_path else None,
            "completed_calibrator_ids": [],
            "transient_failures": {},
        },
        "entries": sort_entries(entries or []),
    }


def build_small_remaining(rows, reserved, config_lookup=None):
    entries = []
    for row in rows:
        entry = entry_from_historical(
            row,
            provenance={
                "historical_status": _text(row.get("status")) or None,
                "historical_error": _text(row.get("wget_error")) or None,
            },
            usable_configs=(config_lookup or {}).get((_text(row.get("name")), _text(row.get("band_guess")) or _text(row.get("band_code")))),
        )
        if entry is not None and entry["obs_id"] not in reserved:
            entries.append(entry)
    return sort_entries(entries)


def build_large_original(rows, reserved, config_lookup=None):
    entries = []
    for row in rows:
        if (_float(row.get("size_gb")) or 0.0) < 15.0:
            continue
        entry = entry_from_historical(
            row,
            provenance={"historical_selection": "original_size_ge_15_gb"},
            usable_configs=(config_lookup or {}).get((_text(row.get("name")), _text(row.get("band_guess")) or _text(row.get("band_code")))),
        )
        if entry is not None and entry["obs_id"] not in reserved:
            entries.append(entry)
    return sort_entries(entries)


def _intent_tokens(intent):
    return set(_text(intent).upper().split())


def probable_gain_calibrator(details):
    execution_blocks = (details.get("details") or {}).get("execution_blocks") or []
    if not execution_blocks:
        return None
    scores = {}
    for scan in execution_blocks[0].get("scan_rows") or []:
        tokens = _intent_tokens(scan.get("intent"))
        if "CALIBRATE_PHASE" not in tokens:
            continue
        if tokens & {"CALIBRATE_FLUX", "CALIBRATE_BANDPASS", "CALIBRATE_DELAY"}:
            continue
        target = _text(scan.get("target_name"))
        if not target:
            continue
        try:
            duration = float(scan.get("duration")) * 86400.0
        except (TypeError, ValueError):
            duration = 0.0
        score = scores.setdefault(target, [0.0, 0])
        score[0] += duration
        score[1] += 1
    if not scores:
        return None
    return max(sorted(scores), key=lambda target: tuple(scores[target]))


def archive_candidates(spec, max_candidates=100):
    position = SkyCoord(spec["ra"], spec["dec"], unit=(u.hourangle, u.deg), frame="icrs")
    query = (
        NRAOQuery()
        .select("obs_publisher_did", "project_code", "t_min", "access_estsize", "access_url", "configuration")
        .where_in_circle(position, 5 * u.arcsec)
        .where_instruments(INSTRUMENTS.VLA_EVLA)
        .where_dataproduct(DATAPRODS.VISIBILITY)
        .where_configs(spec["usable_configs"])
        .where_proprietary_status(PROPRIETARY.PUBLIC)
        .where_band(BANDS.get(spec["band_guess"]))
        .order_by("access_estsize ASC")
        .limit(max_candidates)
        .unique_on("obs_publisher_did")
    )
    try:
        rows = query.get().to_dict(orient="records")
    except Exception as exc:
        raise TransientArchiveError("TAP query failed: %s" % exc) from exc

    candidates = []
    detail_errors = []
    for row in rows:
        url = _text(row.get("access_url"))
        if not url:
            continue
        try:
            details = fetch_product_details(url)
        except Exception as exc:
            detail_errors.append("%s: %s" % (url, exc))
            continue
        execution_blocks = (details.get("details") or {}).get("execution_blocks") or []
        if not execution_blocks or not execution_blocks[0].get("cals"):
            continue
        gain_field = probable_gain_calibrator(details)
        if not gain_field:
            continue
        obs_id = extract_sdm_id_from_access_url(url)
        candidates.append(
            entry_from_values(
                calibrator_id=spec["calibrator_id"],
                obs_id=obs_id,
                project_code=_project_code(obs_id, row),
                gain_calibrator_name=gain_field,
                viewer_url=url,
                estimated_size_gb=(
                    _float(row.get("access_estsize")) / 1_000_000.0
                    if _float(row.get("access_estsize")) is not None else None
                ),
                band_guess=spec["band_guess"],
                usable_configs=spec["usable_configs"],
                ra=spec["ra"],
                dec=spec["dec"],
            )
        )
    if detail_errors and not candidates:
        raise TransientArchiveError("Product details failed: %s" % "; ".join(detail_errors[:3]))
    return sort_entries(candidates)


def calibrator_spec(row):
    return {
        "calibrator_id": _text(row.get("name") or row.get("calibrator_id")),
        "ra": _text(row.get("ra")),
        "dec": _text(row.get("dec")),
        "band_guess": _text(row.get("band_guess") or row.get("band_code")),
        "usable_configs": parse_configs(
            row.get("configs") or row.get("usable_configs") or row.get("gain_array_config")
        ),
    }


def _load_or_create(path, stage, source_path):
    return read_manifest(path) if Path(path).exists() else new_manifest(stage, source_path)


def build_queried_manifest(path, stage, source_path, specs, reserved, slots_by_calibrator, candidate_finder):
    manifest = _load_or_create(path, stage, source_path)
    completed = set(manifest["source"].get("completed_calibrator_ids") or [])
    failures = dict(manifest["source"].get("transient_failures") or {})
    entries = list(manifest.get("entries") or [])
    reserved.update(entry["obs_id"] for entry in entries)
    for spec in specs:
        calibrator_id = spec["calibrator_id"]
        if calibrator_id in completed:
            continue
        slots = int(slots_by_calibrator.get(calibrator_id, 0))
        try:
            candidates = candidate_finder(spec)
        except TransientArchiveError as exc:
            failures[calibrator_id] = str(exc)
            manifest["source"]["transient_failures"] = failures
            write_manifest(manifest, path)
            continue
        selected = []
        for candidate in sort_entries(candidates):
            if candidate["obs_id"] in reserved:
                continue
            selected.append(candidate)
            reserved.add(candidate["obs_id"])
            if len(selected) >= slots:
                break
        entries.extend(selected)
        completed.add(calibrator_id)
        failures.pop(calibrator_id, None)
        manifest["entries"] = sort_entries(entries)
        manifest["source"]["completed_calibrator_ids"] = sorted(completed)
        manifest["source"]["transient_failures"] = failures
        write_manifest(manifest, path)
    return manifest


def _spec_index(config_lookup, *row_groups):
    result = {}
    for rows in row_groups:
        for row in rows:
            spec = calibrator_spec(row)
            spec["usable_configs"] = config_lookup.get(
                (spec["calibrator_id"], spec["band_guess"]), spec["usable_configs"]
            )
            if spec["calibrator_id"] and spec["ra"] and spec["dec"]:
                result[spec["calibrator_id"]] = spec
    return result


def selected_config_lookup(rows):
    result = {}
    for row in rows:
        calibrator_id = _text(row.get("name"))
        try:
            band = BANDS.get(row.get("receiver") or row.get("wavelength")).key
        except (TypeError, ValueError):
            continue
        configs = parse_configs(row.get("usable_configs"))
        if calibrator_id and configs:
            result[(calibrator_id, band)] = configs
    return result


def inventory_counts(downloaded_by_obs_id):
    counts = Counter()
    for metadata in downloaded_by_obs_id.values():
        for calibrator_id in metadata.get("calibrator_ids") or [metadata["calibrator_id"]]:
            counts[calibrator_id] += 1
    return counts


def validate_collections(downloaded_obs_ids, manifests):
    seen = set(downloaded_obs_ids)
    for manifest in manifests:
        entries = manifest.get("entries") or []
        if entries != sort_entries(entries):
            raise ValueError("Manifest %s is not sorted by size" % manifest["source"]["stage"])
        for entry in entries:
            if entry["obs_id"] in seen:
                raise ValueError("obs_id appears in multiple collections: %s" % entry["obs_id"])
            seen.add(entry["obs_id"])


def build_all(source_root, runs_root, candidate_finder=archive_candidates, downloaded_obs_ids=None, downloaded_by_obs_id=None):
    source_root = Path(source_root)
    runs_root = Path(runs_root)
    downloaded_obs_ids = set(ALREADY_DOWNLOADED_OBS_IDS if downloaded_obs_ids is None else downloaded_obs_ids)
    downloaded_by_obs_id = DOWNLOADED_BY_OBS_ID if downloaded_by_obs_id is None else downloaded_by_obs_id
    small_path = source_root / "collect/small_subset/small_selection.csv"
    missing_path = source_root / "collect/vla_calibrators_one_hit_missed.csv"
    one_hit_path = source_root / "collect/vla_calibrators_one_hit.csv"
    selected_path = source_root / "collect/vla_calibrators_selected.csv"
    small_rows = read_csv(small_path)
    missing_rows = read_csv(missing_path)
    one_hit_rows = read_csv(one_hit_path)
    selected_rows = read_csv(selected_path) if selected_path.exists() else []
    config_lookup = selected_config_lookup(selected_rows)

    reserved = set(downloaded_obs_ids)
    small_manifest = new_manifest(
        "small_remaining", small_path, build_small_remaining(small_rows, reserved, config_lookup)
    )
    small_output = runs_root / "small_remaining/manifest.json"
    write_manifest(small_manifest, small_output)
    reserved.update(entry["obs_id"] for entry in small_manifest["entries"])

    missing_specs = [calibrator_spec(row) for row in missing_rows]
    missing_output = runs_root / "missing_no_date/manifest.json"
    missing_manifest = build_queried_manifest(
        missing_output,
        "missing_no_date",
        missing_path,
        missing_specs,
        reserved,
        {spec["calibrator_id"]: 1 for spec in missing_specs},
        candidate_finder,
    )

    large_manifest = new_manifest(
        "large_original", one_hit_path, build_large_original(one_hit_rows, reserved, config_lookup)
    )
    large_output = runs_root / "large_original/manifest.json"
    write_manifest(large_manifest, large_output)
    reserved.update(entry["obs_id"] for entry in large_manifest["entries"])

    prior_counts = inventory_counts(downloaded_by_obs_id)
    for manifest in (small_manifest, missing_manifest, large_manifest):
        prior_counts.update(entry["calibrator_id"] for entry in manifest["entries"])
    specs = _spec_index(config_lookup, small_rows, missing_rows, one_hit_rows)
    repeated_specs = [specs[name] for name in sorted(prior_counts) if name in specs and prior_counts[name] > 0]
    slots = {name: min(3, max(0, 4 - count)) for name, count in prior_counts.items()}
    repeated_output = runs_root / "repeated_up_to_3/manifest.json"
    repeated_manifest = build_queried_manifest(
        repeated_output,
        "repeated_up_to_3",
        None,
        repeated_specs,
        reserved,
        slots,
        candidate_finder,
    )
    manifests = [small_manifest, missing_manifest, large_manifest, repeated_manifest]
    validate_collections(downloaded_obs_ids, manifests)
    return manifests


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--radioastro-root", required=True)
    parser.add_argument("--runs-root", default="runs")
    parser.add_argument("--max-candidates", type=int, default=100)
    args = parser.parse_args(argv)

    def find(spec):
        return archive_candidates(spec, max_candidates=args.max_candidates)

    manifests = build_all(args.radioastro_root, args.runs_root, candidate_finder=find)
    for manifest in manifests:
        print("%s: %d entries" % (manifest["source"]["stage"], len(manifest["entries"])))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
