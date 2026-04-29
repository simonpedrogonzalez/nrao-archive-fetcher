import ast
import json
from pathlib import Path

import pandas as pd

from nrao_archive_fetcher.details import enrich, summarize_details
from nrao_archive_fetcher.manifest import build_manifest, read_manifest, write_manifest
from nrao_archive_fetcher.utils import apply_filter


def load_example():
    path = Path("reference/radioastro_ml_collect/collect/example_details.json")
    return ast.literal_eval(path.read_text())


def test_summarize_details():
    summary = summarize_details(load_example())
    assert summary["project_code"] == "24B-465"
    assert summary["band_codes"] == ["C"]
    assert "J0005+3820" in summary["targets"]


def test_enrich_and_filter(monkeypatch):
    payload = load_example()
    monkeypatch.setattr("nrao_archive_fetcher.details.fetch_product_details", lambda access_url, session=None: payload)
    frame = pd.DataFrame(
        [
            {
                "project_code": "24B-465",
                "access_url": "https://data.nrao.edu/portal/#/productViewer/24B-465.sb47226343.eb47329790.60643.9672167824",
                "target_name": "J0005+3820",
                "t_min": 60643.98902488426,
                "obs_publisher_did": "24B-465.sb47226343.eb47329790.60643.9672167824",
            }
        ]
    )
    enriched = enrich(frame)
    assert enriched.iloc[0]["detail_summary"]["project_code"] == "24B-465"
    filtered = apply_filter(enriched, lambda row, details: row["detail_summary"]["project_code"] == "24B-465")
    assert len(filtered) == 1


def test_build_manifest_round_trip(tmp_path):
    payload = load_example()
    frame = pd.DataFrame(
        [
            {
                "project_code": "24B-465",
                "access_url": "https://data.nrao.edu/portal/#/productViewer/24B-465.sb47226343.eb47329790.60643.9672167824",
                "target_name": "J0005+3820",
                "t_min": 60643.98902488426,
                "obs_publisher_did": "24B-465.sb47226343.eb47329790.60643.9672167824",
                "details": payload,
                "detail_summary": summarize_details(payload),
            }
        ]
    )
    manifest = build_manifest(frame, query_text="SELECT TOP 1 * FROM ivoa.obscore")
    path = tmp_path / "manifest.json"
    write_manifest(manifest, path)
    loaded = read_manifest(path)
    assert loaded["source"]["query_text"] == "SELECT TOP 1 * FROM ivoa.obscore"
    entry = loaded["entries"][0]
    assert entry["project_code"] == "24B-465"
    assert entry["viewer_url"].endswith("24B-465.sb47226343.eb47329790.60643.9672167824")
