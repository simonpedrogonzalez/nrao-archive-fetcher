from pathlib import Path

import pandas as pd

from nrao_archive_fetcher.query import NRAOQuery, date_to_mjd


class FakeTableResult:
    def __init__(self, frame):
        self._frame = frame

    def to_table(self):
        return self

    def to_pandas(self):
        return self._frame.copy()

    def __len__(self):
        return len(self._frame)


class FakeService:
    def run_sync(self, query_text):
        normalized = " ".join(query_text.split())
        if "FROM TAP_SCHEMA.tables" in normalized:
            return FakeTableResult(pd.DataFrame({"table_name": ["ivoa.obscore"]}))
        if "FROM TAP_SCHEMA.columns" in normalized:
            return FakeTableResult(
                pd.DataFrame(
                    {
                        "column_name": [
                            "s_ra",
                            "s_dec",
                            "t_min",
                            "instrument_name",
                            "dataproduct_type",
                            "freq_min",
                            "freq_max",
                            "configuration",
                            "proprietary_status",
                        ]
                    }
                )
            )
        return FakeTableResult(pd.DataFrame({"project_code": ["24B-465"]}))


def test_query_build_and_get(monkeypatch):
    monkeypatch.setattr("nrao_archive_fetcher.query.pyvo.dal.TAPService", lambda url: FakeService())
    query = (
        NRAOQuery()
        .where_dates(start="2016-09-01")
        .where_in_circle((1.0, 2.0), 0.1)
        .where_instruments(["VLA", "EVLA"])
        .where_dataproduct("visibility")
        .where_configs(["A"])
        .where_proprietary_status("PUBLIC")
        .limit(5)
    )
    text = query.build()
    assert "SELECT TOP 5" in text
    assert "instrument_name IN ('VLA','EVLA')" in text
    frame = query.get()
    assert list(frame["project_code"]) == ["24B-465"]


def test_query_save_and_load(tmp_path):
    query = NRAOQuery(raw_query="SELECT TOP 1 * FROM ivoa.obscore")
    path = tmp_path / "query.txt"
    query.save(path)
    loaded = NRAOQuery.load(path)
    assert loaded.build() == "SELECT TOP 1 * FROM ivoa.obscore"


def test_date_to_mjd_known_value():
    assert round(date_to_mjd("2012-01-01"), 1) == 55927.0
