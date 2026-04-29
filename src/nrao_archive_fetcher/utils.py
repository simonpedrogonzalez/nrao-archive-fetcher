from __future__ import annotations

import datetime as _dt
from typing import Any, Callable, Dict, Iterable, List, Optional

import pandas as pd


def now_iso():
    return _dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def print_status(message):
    print(message, flush=True)


def records_from_data(data):
    if isinstance(data, pd.DataFrame):
        return data.to_dict(orient="records")
    return [dict(item) for item in data]


def dataframe_from_records(records):
    return pd.DataFrame(records)


def apply_filter(data, filter_fn, as_dataframe=True):
    records = records_from_data(data)
    kept = []
    total = len(records)
    for idx, row in enumerate(records, start=1):
        details = row.get("details")
        if filter_fn(row, details):
            kept.append(row)
        print_status("[FILTER] kept %d/%d" % (idx, total))
    if as_dataframe:
        return dataframe_from_records(kept)
    return kept


def first_non_empty(*values):
    for value in values:
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        return value
    return None


def unique_preserving_order(values):
    seen = set()
    out = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out
