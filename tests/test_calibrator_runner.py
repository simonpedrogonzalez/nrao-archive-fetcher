import json
from pathlib import Path
from types import SimpleNamespace

from nrao_archive_fetcher.manifest import read_manifest, write_manifest
from workflows.radioastro_calibrators.run_manifest import run_manifest


def test_runner_accepts_present_ms_and_persists_extraction(tmp_path):
    run_root = tmp_path / "small_remaining"
    manifest_path = run_root / "manifest.json"
    entry_id = "0012-399_obs"
    entry = {
        "entry_id": entry_id,
        "obs_id": "obs",
        "project_code": "17B-078",
        "gain_calibrator_name": "J0012-3954",
        "band_guess": "C",
        "download_command": "wget example",
        "request_status": "error",
    }
    write_manifest({"entries": [entry]}, manifest_path)
    download = run_root / "downloads" / entry_id
    source_ms = download / "pipeline" / "source.ms"
    source_ms.mkdir(parents=True)
    (source_ms / "table.dat").touch()

    def fake_download(path, base_download_root=None, after_download=None):
        manifest = read_manifest(path)
        entry = manifest["entries"][0]
        entry["download_root"] = str(download)
        entry["request_status"] = "downloaded"
        after_download(entry, str(download))
        write_manifest(manifest, path)
        return manifest

    def fake_casa(casa, script, entry_json, download_root, output_root, result_json):
        output = Path(output_root) / entry_id
        (output / (entry_id + ".ms")).mkdir(parents=True)
        (output / (entry_id + ".ms") / "table.dat").touch()
        (output / "listobs.txt").write_text("listobs")
        (output / "flux_estimate.json").write_text('{"status": "unavailable"}')
        metadata = {"selected_spw": "7"}
        (output / "extraction_metadata.json").write_text(json.dumps(metadata))
        Path(result_json).write_text(json.dumps(metadata))
        return SimpleNamespace(returncode=0, stdout="ok")

    updated = run_manifest(manifest_path, download_fn=fake_download, casa_runner=fake_casa)
    assert updated["entries"][0]["request_status"] == "extracted"
    persisted = read_manifest(manifest_path)["entries"][0]
    assert persisted["selected_spw"] == "7"
    assert Path(persisted["extracted_ms"]).is_dir()


def _fake_casa(entry_id):
    def run(casa, script, entry_json, download_root, output_root, result_json):
        output = Path(output_root) / entry_id
        (output / (entry_id + ".ms")).mkdir(parents=True)
        (output / (entry_id + ".ms") / "table.dat").touch()
        (output / "listobs.txt").write_text("listobs")
        (output / "flux_estimate.json").write_text("{}")
        (output / "extraction_metadata.json").write_text("{}")
        Path(result_json).write_text("{}")
        return SimpleNamespace(returncode=0, stdout="ok")
    return run


def _partial_ms(run_root, entry_id):
    ms = run_root / "downloads" / entry_id / "x.ms"
    ms.mkdir(parents=True)
    (ms / "table.dat").touch()


def test_failed_download_is_not_extracted(tmp_path):
    manifest_path = tmp_path / "manifest.json"
    write_manifest({"entries": [{"entry_id": "a", "download_command": "wget x", "request_status": ""}]}, manifest_path)
    _partial_ms(tmp_path, "a")
    casa_calls = []

    def failing_download(path, base_download_root=None, after_download=None):
        manifest = read_manifest(path)
        manifest["entries"][0]["request_status"] = "error"
        write_manifest(manifest, path)
        return manifest

    run_manifest(manifest_path, download_fn=failing_download, casa_runner=lambda *a: casa_calls.append(a))
    assert casa_calls == []
    assert read_manifest(manifest_path)["entries"][0]["request_status"] == "error"


def test_downloaded_entry_from_earlier_run_is_extracted_without_downloading(tmp_path):
    manifest_path = tmp_path / "manifest.json"
    write_manifest({"entries": [{"entry_id": "a", "download_command": "wget x", "request_status": "downloaded"}]}, manifest_path)
    _partial_ms(tmp_path, "a")

    def no_new_downloads(path, base_download_root=None, after_download=None):
        return read_manifest(path)

    run_manifest(manifest_path, download_fn=no_new_downloads, casa_runner=_fake_casa("a"))
    assert read_manifest(manifest_path)["entries"][0]["request_status"] == "extracted"


def test_each_entry_is_extracted_right_after_its_download(tmp_path):
    manifest_path = tmp_path / "manifest.json"
    write_manifest({"entries": [{"entry_id": "a", "download_command": "wget x", "request_status": ""}]}, manifest_path)
    events = []

    def download(path, base_download_root=None, after_download=None):
        manifest = read_manifest(path)
        entry = manifest["entries"][0]
        _partial_ms(tmp_path, "a")
        entry["request_status"] = "downloaded"
        events.append("downloaded")
        after_download(entry, str(tmp_path / "downloads" / "a"))
        events.append(entry["request_status"])
        write_manifest(manifest, path)
        return manifest

    run_manifest(manifest_path, download_fn=download, casa_runner=_fake_casa("a"))
    assert events == ["downloaded", "extracted"]
