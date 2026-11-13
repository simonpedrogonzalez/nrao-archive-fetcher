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
                "entry_id": "0005+383_24B-465",
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
        entry["hook_result"] = "persisted"

    updated = download_manifest(manifest_path, before_download=before, after_download=after)
    entry = updated["entries"][0]
    assert entry["request_status"] == "downloaded"
    assert entry["download_attempts"] == 1
    assert seen["before"] == ["24B-465"]
    assert seen["after"][0][0] == "24B-465"
    assert Path(entry["download_root"]).name == "0005+383_24B-465"
    assert json.loads(manifest_path.read_text())["entries"][0]["hook_result"] == "persisted"
    entry_json = Path(entry["download_root"]) / "manifest_entry.json"
    assert entry_json.exists()
    loaded_entry = json.loads(entry_json.read_text())
    assert loaded_entry["project_code"] == "24B-465"


def test_download_command_resumes_with_continue_flag(tmp_path):
    from nrao_archive_fetcher.download import prepare_download_command

    tokens = prepare_download_command('wget -r -np https://dl-dsoc.nrao.edu/u/1/aaaaaaaaaaaaaaaa/', tmp_path)
    assert tokens.count("-c") == 1
    tokens = prepare_download_command("wget2 -c -r https://dl-dsoc.nrao.edu/u/1/aaaaaaaaaaaaaaaa/", tmp_path)
    assert tokens.count("-c") == 1


def test_download_skips_entries_already_downloaded_or_extracted(tmp_path, monkeypatch):
    statuses = ["", "error", "downloading", "downloaded", "extracting", "extracted", "extraction_error"]
    entries = [
        {"entry_id": status or "new", "project_code": "17A-001", "request_status": status,
         "download_command": "wget https://dl-dsoc.nrao.edu/u/1/aaaaaaaaaaaaaaaa/"}
        for status in statuses
    ]
    manifest_path = tmp_path / "manifest.json"
    write_manifest({"entries": entries}, manifest_path)
    downloaded = []
    monkeypatch.setattr(
        "nrao_archive_fetcher.download.run_download_command",
        lambda tokens: (downloaded.append(tokens[-1]), (0, "ok"))[1],
    )
    download_manifest(manifest_path)
    assert sorted(Path(path).name for path in downloaded) == ["downloading", "error", "new"]


def test_wget_rc8_is_treated_as_success(tmp_path, monkeypatch):
    manifest_path = tmp_path / "manifest.json"
    write_manifest({"entries": [{"entry_id": "a", "project_code": "18B-316", "download_command": "wget -r https://x/", "request_status": "error"}]}, manifest_path)
    monkeypatch.setattr("nrao_archive_fetcher.download.run_download_command", lambda tokens: (8, "404 robots.txt"))
    entry = download_manifest(manifest_path)["entries"][0]
    assert entry["request_status"] == "downloaded"
    assert entry["last_error"] is None


def test_other_wget_errors_still_fail(tmp_path, monkeypatch):
    manifest_path = tmp_path / "manifest.json"
    write_manifest({"entries": [{"entry_id": "a", "project_code": "18B-316", "download_command": "wget -r https://x/", "request_status": ""}]}, manifest_path)
    monkeypatch.setattr("nrao_archive_fetcher.download.run_download_command", lambda tokens: (4, "network failure"))
    assert download_manifest(manifest_path)["entries"][0]["request_status"] == "error"
