from __future__ import annotations

import re
import time
from typing import Any, Dict, Optional
from urllib.parse import urlparse

import pandas as pd
import requests

from .constants import NRAO_DETAILS_API
from .utils import dataframe_from_records, print_status, records_from_data, unique_preserving_order


def extract_sdm_id_from_access_url(access_url):
    if not access_url:
        raise ValueError("access_url is empty")
    match = re.search(r"/#/(?:productViewer|productviewer)/([^/?#]+)", access_url)
    if match:
        return match.group(1)
    parsed = urlparse(access_url)
    tail = parsed.path.rstrip("/").split("/")[-1]
    if tail and "." in tail:
        return tail
    raise ValueError("Could not parse sdm_id from access_url: %r" % (access_url,))


def build_product_details_url(sdm_id):
    return "%s?sdm_id=%s" % (NRAO_DETAILS_API, sdm_id)


def build_viewer_url(sdm_id):
    return "https://data.nrao.edu/portal/#/productViewer/%s" % (sdm_id,)


def fetch_product_details(access_url, session=None, timeout=30, retries=5, backoff=1.0):
    sdm_id = extract_sdm_id_from_access_url(access_url)
    api_url = build_product_details_url(sdm_id)
    sess = session or requests.Session()
    last_error = None
    for attempt in range(retries):
        try:
            response = sess.get(api_url, timeout=timeout)
            if response.status_code == 429:
                time.sleep(backoff * (2 ** attempt))
                continue
            response.raise_for_status()
            return response.json()
        except Exception as exc:
            last_error = exc
            time.sleep(backoff * (2 ** attempt))
    raise RuntimeError("Failed to fetch product details for sdm_id=%s" % (sdm_id,)) from last_error


def _first_execution_block(details_payload):
    details = details_payload.get("details") or {}
    execution_blocks = details.get("execution_blocks") or []
    if execution_blocks:
        return execution_blocks[0]
    return {}


def summarize_details(details_payload):
    execution_block = _first_execution_block(details_payload)
    configurations = execution_block.get("configurations") or []
    targets = []
    bands = []
    array_configs = []
    for config in configurations:
        band = config.get("band")
        if band:
            bands.append(str(band))
        for target in config.get("target_durs") or []:
            target_name = target.get("target_name")
            if target_name:
                targets.append(str(target_name))
    if execution_block.get("band_code"):
        bands.append(str(execution_block.get("band_code")))
    if execution_block.get("configuration"):
        array_configs.append(str(execution_block.get("configuration")))

    obs_start = execution_block.get("obs_start")
    date_text = None
    if isinstance(obs_start, str) and obs_start.strip():
        date_text = obs_start.strip().split(" ", 1)[0]

    summary = {
        "sdm_id": execution_block.get("sdm_id"),
        "project_code": execution_block.get("project_code"),
        "date": date_text,
        "viewer_url": build_viewer_url(execution_block.get("sdm_id")) if execution_block.get("sdm_id") else None,
        "estimated_size_gb": (
            float(execution_block.get("access_estsize")) / 1_000_000_000.0
            if execution_block.get("access_estsize") not in (None, "")
            else None
        ),
        "band_codes": unique_preserving_order(bands),
        "array_configs": unique_preserving_order(array_configs),
        "targets": unique_preserving_order(targets),
        "cal_status": execution_block.get("cal_status"),
        "instrument_name": execution_block.get("instrument_name"),
        "num_antennas": execution_block.get("num_antennas"),
        "has_caltables": bool(execution_block.get("cals")),
    }
    return summary


def enrich(data, filter_fn=None, session=None, as_dataframe=True, progress=True):
    records = records_from_data(data)
    total = len(records)
    out = []
    sess = session or requests.Session()
    for idx, row in enumerate(records, start=1):
        row_copy = dict(row)
        details = None
        detail_summary = None
        access_url = row_copy.get("access_url")
        if isinstance(access_url, str) and access_url.strip():
            print_status("[ENRICH] fetching %d/%d" % (idx, total))
            details = fetch_product_details(access_url, session=sess)
            detail_summary = summarize_details(details)
        row_copy["details"] = details
        row_copy["detail_summary"] = detail_summary
        if filter_fn is not None and not filter_fn(row_copy, details):
            continue
        out.append(row_copy)
    if as_dataframe:
        return dataframe_from_records(out)
    return out
