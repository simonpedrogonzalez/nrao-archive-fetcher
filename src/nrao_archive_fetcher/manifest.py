from __future__ import annotations

import json
import math
from pathlib import Path

import pandas as pd

from .constants import TAP_URL
from .details import build_viewer_url, summarize_details
from .query import mjd_to_iso
from .utils import first_non_empty, now_iso, print_status, records_from_data


def _summary_from_row(row):
    summary = row.get("detail_summary")
    if isinstance(summary, dict):
        return summary
    details = row.get("details")
    if isinstance(details, dict):
        return summarize_details(details)
    return {}


def _date_from_row(row, summary):
    if row.get("t_min") not in (None, ""):
        try:
            return mjd_to_iso(float(row["t_min"])).split(" ", 1)[0]
        except Exception:
            pass
    return summary.get("date")


def _viewer_url_from_row(row, summary):
    access_url = row.get("access_url")
    if isinstance(access_url, str) and access_url.strip():
        return access_url
    return summary.get("viewer_url")


def _obs_id_from_row(row, summary):
    return first_non_empty(row.get("obs_publisher_did"), summary.get("sdm_id"))


def _project_code_from_row(row, summary):
    return first_non_empty(row.get("project_code"), summary.get("project_code"))


def _estimated_size_gb(row, summary):
    value = row.get("access_estsize")
    if value not in (None, ""):
        try:
            return float(value) / 1_000_000.0
        except Exception:
            pass
    return summary.get("estimated_size_gb")


def _array_configs(row, summary):
    if row.get("configuration"):
        return [str(row.get("configuration"))]
    return list(summary.get("array_configs") or [])


def _targets(row, summary):
    if row.get("target_name"):
        return [str(row.get("target_name"))]
    return list(summary.get("targets") or [])


def build_manifest(data, include_row=True, include_details=True, query_text=None, tap_url=TAP_URL):
    records = records_from_data(data)
    entries = []
    for row in records:
        row_only = dict(row)
        row_only.pop("details", None)
        row_only.pop("detail_summary", None)
        summary = _summary_from_row(row)
        entry = {
            "project_code": _project_code_from_row(row, summary),
            "obs_id": _obs_id_from_row(row, summary),
            "date": _date_from_row(row, summary),
            "viewer_url": _viewer_url_from_row(row, summary),
            "estimated_size_gb": _estimated_size_gb(row, summary),
            "band_codes": list(summary.get("band_codes") or []),
            "array_configs": _array_configs(row, summary),
            "targets": _targets(row, summary),
            "request_status": "",
            "request_submitted_at": None,
            "request_finished_at": None,
            "download_command": "",
            "download_attempts": 0,
            "download_root": None,
        }
        if summary:
            entry["detail_summary"] = summary
        if include_row:
            entry["row"] = row_only
        if include_details and isinstance(row.get("details"), dict):
            entry["details"] = row["details"]
        entries.append(entry)
    manifest = {
        "version": 1,
        "created_at": now_iso(),
        "source": {
            "tap_url": tap_url,
            "query_text": query_text,
        },
        "entries": entries,
    }
    print_status("[MANIFEST] built %d entries" % (len(entries),))
    return manifest


def read_manifest(path):
    return json.loads(Path(path).read_text())


def make_json_safe(value):
    if isinstance(value, dict):
        return {str(key): make_json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [make_json_safe(item) for item in value]
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        return value
    if hasattr(value, "item"):
        try:
            return make_json_safe(value.item())
        except Exception:
            pass
    try:
        missing = pd.isna(value)
    except Exception:
        missing = False
    if isinstance(missing, bool) and missing:
        return None
    return value


def dumps_json(data):
    return json.dumps(make_json_safe(data), indent=2, sort_keys=False, allow_nan=False)


def write_manifest(manifest, path):
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(dumps_json(manifest))
    print_status("[MANIFEST] wrote %s" % (destination,))


def print_pending(manifest_path):
    manifest = read_manifest(manifest_path)
    pending = 0
    for entry in manifest.get("entries", []):
        viewer_url = entry.get("viewer_url")
        download_command = entry.get("download_command")
        if viewer_url and not str(download_command or "").strip():
            pending += 1
            print("%s %s" % (entry.get("project_code") or "<missing-project-code>", viewer_url))
    print_status("[PENDING] %d pending entries" % (pending,))
