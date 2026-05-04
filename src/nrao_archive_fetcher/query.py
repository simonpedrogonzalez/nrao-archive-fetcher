from __future__ import annotations

import random
import time
from pathlib import Path
from typing import Iterable, Optional, Union

import astropy.units as u
import pandas as pd
import pyvo
from astropy.coordinates import SkyCoord
from astropy.time import Time

from .constants import BANDS, COLS, DATAPRODS, DEFAULT_QUERY_LIMIT, TAP_URL, TIMESPANS, Band, TimeSpan
from .utils import print_status


def date_to_mjd(date_str):
    return Time(date_str, format="iso", scale="utc").mjd


def mjd_to_iso(mjd):
    return Time(mjd, format="mjd", scale="utc").iso


def _as_mjd(value):
    if value is None:
        return None
    if isinstance(value, (float, int)):
        return float(value)
    return float(date_to_mjd(str(value)))


def find_obscore_table(service):
    result = service.run_sync("SELECT table_name FROM TAP_SCHEMA.tables")
    frame = result.to_table().to_pandas()
    names = set(frame["table_name"].astype(str))
    preferred = [
        "ivoa.obscore",
        "tap_schema.obscore",
        "ivoa.ObsCore",
        "obscore.obscore",
        "obscore.ObsCore",
    ]
    for name in preferred:
        if name in names:
            return name
    candidates = sorted([name for name in names if "obscore" in name.lower()])
    if candidates:
        return candidates[0]
    raise RuntimeError("No ObsCore table found.")


def get_obscore_columns(service, obscore_table):
    query = """
    SELECT column_name
    FROM TAP_SCHEMA.columns
    WHERE table_name = '%s'
    ORDER BY column_name
    """ % (obscore_table,)
    frame = service.run_sync(query).to_table().to_pandas()
    return [str(value) for value in frame["column_name"]]


def pretty_format_query(query_text):
    query_text = query_text.strip()
    query_text = query_text.replace(" WHERE ", "\nWHERE ")
    query_text = query_text.replace(" FROM ", "\nFROM ")
    query_text = query_text.replace(" ORDER BY ", "\nORDER BY ")
    if "WHERE " not in query_text:
        return query_text
    head, where_part = query_text.split("WHERE ", 1)
    if "ORDER BY" in where_part:
        where_body, order_part = where_part.split("ORDER BY", 1)
        order_part = "ORDER BY " + order_part
    else:
        where_body = where_part
        order_part = ""
    conditions = where_body.strip().split(" AND ")
    where_block = "WHERE\n    " + "\n    AND ".join(piece.strip() for piece in conditions)
    out = head.strip() + "\n" + where_block
    if order_part:
        out += "\n" + order_part.strip()
    return out


def _resolve_named_center(name):
    try:
        from astroquery.simbad import Simbad
    except ImportError as exc:
        raise ValueError("String target lookup requires astroquery to be installed.") from exc
    simbad = Simbad()
    simbad.add_votable_fields("coordinates")
    table = simbad.query_object(name)
    if table is None:
        raise ValueError("SIMBAD could not resolve %r" % (name,))
    return SkyCoord(str(table["RA"][0]), str(table["DEC"][0]), unit=(u.hourangle, u.deg), frame="icrs")


class NRAOQuery:
    def __init__(self, tap_url=TAP_URL, raw_query=None):
        self.tap_url = tap_url
        self._service = None
        self._table = None
        self.available_cols = set()
        self._raw_query = raw_query
        self._select = ["*"]
        self._where = []
        self._order_by = None
        self._limit = DEFAULT_QUERY_LIMIT
        self._unique_on = None

    @property
    def table(self):
        self._ensure_schema()
        return self._table

    def _ensure_service(self):
        if self._service is None:
            self._service = pyvo.dal.TAPService(self.tap_url)
        return self._service

    def _ensure_schema(self):
        if self._raw_query is not None:
            return
        if self._table is None:
            service = self._ensure_service()
            self._table = find_obscore_table(service)
            self.available_cols = set(get_obscore_columns(service, self._table))

    def select(self, *cols):
        self._raw_query = None
        self._select = list(cols) if cols else ["*"]
        return self

    def limit(self, count):
        self._raw_query = None
        self._limit = int(count)
        return self

    def top(self, count):
        return self.limit(count)

    def order_by(self, expr):
        self._raw_query = None
        self._order_by = expr
        return self

    def unique_on(self, column):
        self._unique_on = str(column)
        return self

    def where_timespan(self, span):
        self._ensure_schema()
        self._raw_query = None
        if span.start_mjd is not None and "t_min" in self.available_cols:
            self._where.append("(t_min >= %s)" % (float(span.start_mjd),))
        if span.end_mjd is not None and "t_min" in self.available_cols:
            self._where.append("(t_min < %s)" % (float(span.end_mjd),))
        return self

    def where_dates(self, start=None, end=None):
        self._ensure_schema()
        self._raw_query = None
        start_mjd = _as_mjd(start)
        end_mjd = _as_mjd(end)
        if start_mjd is not None and "t_min" in self.available_cols:
            self._where.append("(t_min >= %s)" % (start_mjd,))
        if end_mjd is not None and "t_min" in self.available_cols:
            self._where.append("(t_min < %s)" % (end_mjd,))
        return self

    def where_in_circle(self, center, radius):
        self._ensure_schema()
        self._raw_query = None
        if isinstance(radius, u.Quantity):
            radius_deg = radius.to_value(u.deg)
        else:
            radius_deg = float(radius)
        if isinstance(center, str):
            coord = _resolve_named_center(center)
        elif isinstance(center, tuple):
            coord = SkyCoord(float(center[0]) * u.deg, float(center[1]) * u.deg, frame="icrs")
        else:
            coord = center
        self._where.append(
            "CONTAINS(POINT('ICRS', s_ra, s_dec), CIRCLE('ICRS', %s, %s, %s)) = 1"
            % (coord.ra.deg, coord.dec.deg, radius_deg)
        )
        return self

    def where_instruments(self, instruments):
        self._ensure_schema()
        self._raw_query = None
        if "instrument_name" in self.available_cols:
            values = ",".join("'%s'" % (str(item),) for item in instruments)
            self._where.append("(instrument_name IN (%s))" % (values,))
        return self

    def where_dataproduct(self, dataproduct_type):
        self._ensure_schema()
        self._raw_query = None
        if "dataproduct_type" in self.available_cols:
            self._where.append("(dataproduct_type = '%s')" % (dataproduct_type,))
        return self

    def where_band(self, band):
        self._ensure_schema()
        self._raw_query = None
        band_obj = BANDS.get(band) if not isinstance(band, Band) else band
        if "freq_min" in self.available_cols and "freq_max" in self.available_cols:
            self._where.append("(freq_max >= %s AND freq_min <= %s)" % (band_obj.f_lo_hz, band_obj.f_hi_hz))
        return self

    def where_configs(self, configs):
        self._ensure_schema()
        self._raw_query = None
        if "configuration" in self.available_cols:
            values = ",".join("'%s'" % (str(item),) for item in configs)
            self._where.append("(configuration IN (%s))" % (values,))
        return self

    def where_proprietary_status(self, status):
        self._ensure_schema()
        self._raw_query = None
        if "proprietary_status" in self.available_cols:
            self._where.append("(proprietary_status = '%s')" % (status,))
        return self

    def build(self):
        if self._raw_query is not None:
            return self._raw_query.strip()
        self._ensure_schema()
        select_list = ", ".join(self._select) if self._select else "*"
        where_clause = ""
        if self._where:
            where_clause = " WHERE " + " AND ".join(self._where)
        order_clause = ""
        if self._order_by:
            order_clause = " ORDER BY " + self._order_by
        return "SELECT TOP %d %s FROM %s%s%s" % (int(self._limit), select_list, self._table, where_clause, order_clause)

    def save(self, path):
        Path(path).write_text(self.build())
        print_status("[QUERY] wrote query to %s" % (path,))

    @classmethod
    def load(cls, path, tap_url=TAP_URL):
        return cls(tap_url=tap_url, raw_query=Path(path).read_text())

    def get(self, as_dataframe=True, retries=6, backoff=1.5, jitter=0.25, verbose=True):
        query_text = self.build()
        service = self._ensure_service()
        if verbose:
            print_status("[QUERY] Executing ADQL query")
            print(pretty_format_query(query_text), flush=True)
        last_error = None
        for attempt in range(retries):
            try:
                table = service.run_sync(query_text).to_table()
                if as_dataframe:
                    frame = table.to_pandas()
                    if self._unique_on and self._unique_on in frame.columns:
                        before = len(frame)
                        frame = frame.drop_duplicates(subset=[self._unique_on]).reset_index(drop=True)
                        if verbose:
                            print_status(
                                "[QUERY] unique on %s: %d -> %d rows"
                                % (self._unique_on, before, len(frame))
                            )
                    print_status("[QUERY] received %d rows" % (len(frame),))
                    return frame
                print_status("[QUERY] received %d rows" % (len(table),))
                return table
            except Exception as exc:
                last_error = exc
                text = str(exc).lower()
                transient = any(
                    marker in text
                    for marker in [
                        "timeout",
                        "timed out",
                        "service unavailable",
                        "temporarily unavailable",
                        "bad gateway",
                        "gateway timeout",
                        "502",
                        "503",
                        "504",
                        "connection reset",
                        "could not connect",
                        "internal server error",
                    ]
                )
                if (not transient) or attempt == retries - 1:
                    raise
                sleep_seconds = max(0.5, backoff * (2 ** attempt) * (1.0 + random.uniform(-jitter, jitter)))
                print_status("[QUERY] transient error, retrying in %.1fs: %s" % (sleep_seconds, exc))
                time.sleep(sleep_seconds)
        raise RuntimeError("TAP query failed after retries") from last_error
