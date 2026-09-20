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
    (download / "pipeline" / "source.ms").mkdir(parents=True)

    def fake_download(path, base_download_root=None):
        manifest = read_manifest(path)
        manifest["entries"][0]["download_root"] = str(download)
        return manifest

    def fake_casa(casa, script, entry_json, download_root, output_root, result_json):
        output = Path(output_root) / entry_id
        (output / (entry_id + ".ms")).mkdir(parents=True)
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
