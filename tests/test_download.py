import json
from pathlib import Path

from nrao_archive_fetcher.download import download_manifest
from nrao_archive_fetcher.manifest import write_manifest


def test_download_manifest(tmp_path, monkeypatch):
    manifest_path = tmp_path / "manifest.json"
    manifest = {
        "version": 1,
        "created_at": "2026-04-29T00:00:00Z",
        "source": {},
        "entries": [
            {
                "project_code": "24B-465",
                "viewer_url": "https://data.nrao.edu/portal/#/productViewer/24B-465.sb47226343.eb47329790.60643.9672167824",
                "download_command": "wget https://dl-dsoc.nrao.edu/user/123/abcdef1234567890/",
                "download_attempts": 0,
                "request_status": "",
            }
        ],
    }
    write_manifest(manifest, manifest_path)

    seen = {"before": [], "after": []}

    monkeypatch.setattr("nrao_archive_fetcher.download.run_download_command", lambda tokens: (0, "ok"))

    def before(entry):
        seen["before"].append(entry["project_code"])

    def after(entry, downloaded_path):
        seen["after"].append((entry["project_code"], downloaded_path))

    updated = download_manifest(manifest_path, before_download=before, after_download=after)
    entry = updated["entries"][0]
    assert entry["request_status"] == "downloaded"
    assert entry["download_attempts"] == 1
    assert seen["before"] == ["24B-465"]
    assert seen["after"][0][0] == "24B-465"
    entry_json = Path(entry["download_root"]) / "manifest_entry.json"
    assert entry_json.exists()
    loaded_entry = json.loads(entry_json.read_text())
    assert loaded_entry["project_code"] == "24B-465"
