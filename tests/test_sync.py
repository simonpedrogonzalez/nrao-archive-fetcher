import json
from pathlib import Path
from types import SimpleNamespace

from nrao_archive_fetcher.manifest import read_manifest, write_manifest
from nrao_archive_fetcher.sync import merge_shards, shard_path, sync_requests, write_shard
from workflows.radioastro_calibrators.run_manifest import main as run_main
from workflows.radioastro_calibrators.run_manifest import run_shard

WGET_OLD = "wget https://dl-dsoc.nrao.edu/u/1/aaaaaaaaaaaaaaaa/"
WGET_NEW = "wget https://dl-dsoc.nrao.edu/u/2/bbbbbbbbbbbbbbbb/"


def _entry(entry_id, **fields):
    return {"entry_id": entry_id, "project_code": "17A-001", "download_command": "", "request_status": "", **fields}


def _write(path, entries):
    write_manifest({"version": 1, "entries": entries}, path)
    return path


def test_sync_requests_copies_links_and_failures(tmp_path):
    local = _write(tmp_path / "local.json", [
        _entry("a", download_command=WGET_OLD, request_status="request_ready", request_finished_at="t1"),
        _entry("b", request_status="request_failed", request_error="No further information found."),
        _entry("c"),
        _entry("not-on-chpc", download_command=WGET_OLD, request_status="request_ready"),
    ])
    target = _write(tmp_path / "manifest.json", [_entry("a"), _entry("b"), _entry("c")])
    counts = sync_requests(local, target)
    assert counts["new"] == 1 and counts["failed"] == 1 and counts["unknown"] == 1
    a, b, c = read_manifest(target)["entries"]
    assert a["download_command"] == WGET_OLD and a["request_status"] == "request_ready"
    assert b["request_status"] == "request_failed" and b["request_error"] == "No further information found."
    assert c["request_status"] == ""
    assert sync_requests(local, target)["new"] == 0


def test_sync_requests_retries_failed_or_stuck_but_keeps_downloaded(tmp_path):
    stuck = ("error", "downloading", "extraction_error")
    done = ("downloaded", "extracting", "extracted")
    local = _write(tmp_path / "local.json", [
        _entry(status, download_command=WGET_NEW, request_status="request_ready") for status in stuck + done
    ])
    target = _write(tmp_path / "manifest.json", [
        _entry(status, download_command=WGET_OLD, request_status=status, last_error="x") for status in stuck + done
    ])
    counts = sync_requests(local, target)
    assert counts["retry"] == 3 and counts["locked"] == 3
    for entry in read_manifest(target)["entries"]:
        if entry["entry_id"] in stuck:
            assert entry["download_command"] == WGET_NEW and entry["request_status"] == "request_ready"
            assert entry["last_error"] is None
        else:
            assert entry["download_command"] == WGET_OLD and entry["request_status"] == entry["entry_id"]


def test_sync_requests_failure_does_not_overwrite_a_link(tmp_path):
    local = _write(tmp_path / "local.json", [_entry("a", request_status="request_failed", request_error="x")])
    target = _write(tmp_path / "manifest.json", [_entry("a", download_command=WGET_OLD, request_status="request_ready")])
    assert sync_requests(local, target)["failed"] == 0
    assert read_manifest(target)["entries"][0]["request_status"] == "request_ready"


def test_shards_partition_every_entry_once(tmp_path):
    main = _write(tmp_path / "manifest.json", [_entry(str(i)) for i in range(7)])
    ids = []
    for index in range(3):
        path = write_shard(main, index, 3)
        assert path == shard_path(main, index, 3)
        ids += [entry["entry_id"] for entry in read_manifest(path)["entries"]]
    assert sorted(ids, key=int) == [str(i) for i in range(7)]


def test_shard_keeps_progress_and_merge_brings_it_back(tmp_path):
    main = _write(tmp_path / "manifest.json", [
        _entry("a", download_command=WGET_OLD, request_status="request_ready"),
        _entry("b", download_command=WGET_OLD, request_status="request_ready"),
    ])
    path = write_shard(main, 0, 2)
    shard = read_manifest(path)
    shard["entries"][0].update(request_status="extracted", extracted_ms="/x/a.ms", download_root="/d/a")
    write_manifest(shard, path)
    # Rewriting the shard (job restarted before a merge) keeps the saved progress.
    assert read_manifest(write_shard(main, 0, 2))["entries"][0]["request_status"] == "extracted"
    assert merge_shards(main) == 1
    a, b = read_manifest(main)["entries"]
    assert a["request_status"] == "extracted" and a["extracted_ms"] == "/x/a.ms"
    assert a["download_command"] == WGET_OLD
    assert b["request_status"] == "request_ready"


def test_merge_ignores_shard_progress_from_before_a_new_link(tmp_path):
    main = _write(tmp_path / "manifest.json", [_entry("a", download_command=WGET_OLD, request_status="request_ready")])
    path = write_shard(main, 0, 1)
    shard = read_manifest(path)
    shard["entries"][0].update(request_status="error", last_error="404")
    write_manifest(shard, path)
    local = _write(tmp_path / "local.json", [_entry("a", download_command=WGET_NEW, request_status="request_ready")])
    sync_requests(local, main)
    assert merge_shards(main) == 0
    assert read_manifest(main)["entries"][0]["request_status"] == "request_ready"
    rewritten = read_manifest(write_shard(main, 0, 1))["entries"][0]
    assert rewritten["download_command"] == WGET_NEW and rewritten["request_status"] == "request_ready"


def test_run_shard_only_processes_its_entries(tmp_path):
    main = _write(tmp_path / "manifest.json", [
        _entry("e%d" % i, download_command=WGET_OLD, request_status="request_ready") for i in range(4)
    ])
    seen = []

    def fake_download(path, base_download_root=None, after_download=None):
        manifest = read_manifest(path)
        for entry in manifest["entries"]:
            seen.append(entry["entry_id"])
            entry["request_status"] = "downloaded"
            entry["download_root"] = str(Path(base_download_root) / entry["entry_id"])
        write_manifest(manifest, path)
        return manifest

    run_shard(main, 2, 1, download_fn=fake_download, casa_runner=None)
    assert seen == ["e1", "e3"]
    assert Path(read_manifest(shard_path(main, 1, 2))["entries"][0]["download_root"]).parent == tmp_path / "downloads"
    assert all(entry["request_status"] == "request_ready" for entry in read_manifest(main)["entries"])
    merge_shards(main)
    statuses = [entry["request_status"] for entry in read_manifest(main)["entries"]]
    assert statuses == ["request_ready", "downloaded", "request_ready", "downloaded"]


def test_shard_index_comes_from_slurm_array(tmp_path, monkeypatch):
    import workflows.radioastro_calibrators.run_manifest as runner

    calls = []
    monkeypatch.setattr(runner, "run_shard", lambda path, shards, index, **kw: calls.append((shards, index)))
    monkeypatch.setenv("SLURM_ARRAY_TASK_ID", "2")
    assert run_main([str(tmp_path / "manifest.json"), "--shards", "4"]) == 0
    assert calls == [(4, 2)]
