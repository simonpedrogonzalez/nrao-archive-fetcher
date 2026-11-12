from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from pathlib import Path

from nrao_archive_fetcher.download import download_manifest
from nrao_archive_fetcher.manifest import read_manifest, write_manifest
from nrao_archive_fetcher.sync import write_shard
from nrao_archive_fetcher.utils import now_iso, print_status
from workflows.radioastro_calibrators.extract_entry import find_first_ms


def _complete_outputs(output_root, entry_id):
    folder = Path(output_root) / entry_id
    expected = {
        "extracted_ms": folder / (entry_id + ".ms"),
        "listobs": folder / "listobs.txt",
        "flux_estimate": folder / "flux_estimate.json",
        "extraction_metadata": folder / "extraction_metadata.json",
    }
    return expected if expected["extracted_ms"].is_dir() and all(
        path.is_file() for key, path in expected.items() if key != "extracted_ms"
    ) else None


def _run_casa(casa_executable, script_path, entry_json, download_root, output_root, result_json):
    command = [
        str(casa_executable), "--nogui", "--nologger", "-c", str(script_path),
        "--entry-json", str(entry_json),
        "--download-root", str(download_root),
        "--output-root", str(output_root),
        "--result-json", str(result_json),
    ]
    return subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)


def _record_success(entry, outputs, result):
    entry["request_status"] = "extracted"
    entry["extracted_ms"] = str(outputs["extracted_ms"])
    entry["selected_spw"] = result.get("selected_spw")
    entry["flux_estimate"] = str(outputs["flux_estimate"])
    entry["extraction_metadata"] = str(outputs["extraction_metadata"])
    entry["extraction_finished_at"] = now_iso()
    entry["last_error"] = None


def run_manifest(
    manifest_path,
    casa_executable="casa",
    delete_original=False,
    download_fn=download_manifest,
    casa_runner=_run_casa,
):
    """Download and extract every entry of a manifest, extracting each entry right after its download.

    Only successful downloads are extracted. Entries downloaded in an earlier run but not extracted
    (job stopped, or CASA failed) are extracted first. Finished entries are never downloaded again.
    """
    manifest_path = Path(manifest_path).resolve()
    run_root = manifest_path.parent
    download_root = run_root / "downloads"
    output_root = run_root / "extracted"
    output_root.mkdir(parents=True, exist_ok=True)
    script_path = Path(__file__).with_name("extract_entry.py").resolve()

    def extract(entry):
        """Extract one downloaded entry, updating it in place."""
        entry_id = str(entry.get("entry_id") or "").strip()
        if not entry_id:
            entry["request_status"] = "extraction_error"
            entry["last_error"] = "Manifest entry is missing entry_id"
            return
        outputs = _complete_outputs(output_root, entry_id)
        if outputs is not None:
            _record_success(entry, outputs, json.loads(outputs["extraction_metadata"].read_text()))
            return
        entry_download_root = Path(entry.get("download_root") or (download_root / entry_id))
        if find_first_ms(entry_download_root) is None:
            entry["request_status"] = "extraction_error"
            entry["last_error"] = "No MeasurementSet found in %s" % entry_download_root
            return
        entry["request_status"] = "extracting"
        entry["last_error"] = None
        entry_json = entry_download_root / "manifest_entry.json"
        entry_json.parent.mkdir(parents=True, exist_ok=True)
        entry_json.write_text(json.dumps(entry, indent=2) + "\n")
        result_json = output_root / entry_id / "extraction_result.json"
        result_json.parent.mkdir(parents=True, exist_ok=True)
        process = casa_runner(casa_executable, script_path, entry_json, entry_download_root, output_root, result_json)
        outputs = _complete_outputs(output_root, entry_id)
        if outputs is None or process.returncode != 0 or not result_json.is_file():
            entry["request_status"] = "extraction_error"
            entry["last_error"] = (process.stdout or "CASA extraction did not produce the expected files")[-4000:]
            return
        _record_success(entry, outputs, json.loads(result_json.read_text()))
        print_status("[EXTRACT] done entry=%s" % entry_id)
        if delete_original:
            resolved = entry_download_root.resolve()
            if download_root.resolve() not in resolved.parents:
                raise ValueError("Refusing to delete download outside %s" % download_root)
            shutil.rmtree(resolved)
            entry["download_root"] = None
            entry["original_download_deleted"] = True

    # 1. Entries whose download already finished but which are not extracted yet.
    manifest = read_manifest(manifest_path)
    for entry in manifest.get("entries", []):
        if entry.get("request_status") == "extracted":
            continue
        entry_id = str(entry.get("entry_id") or "").strip()
        finished = entry_id and _complete_outputs(output_root, entry_id) is not None
        if finished or entry.get("request_status") in ("downloaded", "extracting", "extraction_error"):
            extract(entry)
            write_manifest(manifest, manifest_path)

    # 2. Everything else: download, then extract right away (download_fn saves the entry after the hook).
    return download_fn(manifest_path, base_download_root=download_root, after_download=lambda entry, folder: extract(entry))


def run_shard(manifest_path, shards, shard_index, **kwargs):
    """Run job shard_index of shards on its own shard manifest, next to the main manifest.

    All shards share the downloads/ and extracted/ folders. Each one writes only its shard manifest,
    so the jobs never overwrite each other. Merge the progress back with ``nrao-fetch merge-shards``.
    """
    path = write_shard(manifest_path, shard_index, shards)
    print_status("[SHARD] job %d of %d -> %s" % (shard_index, shards, path))
    return run_manifest(path, **kwargs)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest")
    parser.add_argument("--casa", default="casa")
    parser.add_argument("--delete-original", action="store_true")
    parser.add_argument("--shards", type=int, help="Total number of parallel jobs N. Each job takes every Nth entry.")
    parser.add_argument(
        "--shard-index",
        type=int,
        help="This job's index, 0..N-1. Defaults to SLURM_ARRAY_TASK_ID (submit with sbatch --array=0-<N-1>).",
    )
    args = parser.parse_args(argv)
    kwargs = dict(casa_executable=args.casa, delete_original=args.delete_original)
    if args.shards is None:
        run_manifest(args.manifest, **kwargs)
        return 0
    index = args.shard_index
    if index is None:
        task_id = os.environ.get("SLURM_ARRAY_TASK_ID")
        if task_id is None:
            parser.error("--shards needs --shard-index or a Slurm array job (SLURM_ARRAY_TASK_ID)")
        index = int(task_id)
    run_shard(args.manifest, args.shards, index, **kwargs)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
