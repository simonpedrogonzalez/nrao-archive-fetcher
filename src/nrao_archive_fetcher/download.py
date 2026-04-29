from __future__ import annotations

import json
import shlex
import subprocess
from pathlib import Path

from .manifest import read_manifest, write_manifest
from .utils import now_iso, print_status


def _normalize_command(command):
    return " ".join(str(command or "").replace("\\\n", " ").replace("\\\r", " ").split())


def prepare_download_command(command, download_dir):
    normalized = _normalize_command(command)
    if not normalized:
        raise ValueError("download_command is empty")
    tokens = shlex.split(normalized)
    if not tokens:
        raise ValueError("download_command is empty")
    executable = tokens[0]
    if executable not in ("wget", "wget2"):
        raise ValueError("download_command must start with wget or wget2")

    cleaned = [executable]
    skip_next = False
    for idx, token in enumerate(tokens[1:], start=1):
        if skip_next:
            skip_next = False
            continue
        if token in ("-P", "--directory-prefix"):
            skip_next = True
            continue
        if token.startswith("--directory-prefix="):
            continue
        cleaned.append(token)
    if executable == "wget" and not any(token.startswith("--progress") for token in cleaned):
        cleaned.append("--progress=dot:giga")
    cleaned.extend(["-P", str(download_dir)])
    return cleaned


def run_download_command(tokens):
    print_status("[DOWNLOAD] command: %s" % (" ".join(shlex.quote(token) for token in tokens),))
    proc = subprocess.Popen(tokens, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
    lines = []
    assert proc.stdout is not None
    for line in proc.stdout:
        print(line.rstrip(), flush=True)
        lines.append(line)
    proc.wait()
    return proc.returncode, "".join(lines)


def _write_entry_json(entry, folder):
    entry_path = Path(folder) / "manifest_entry.json"
    entry_path.write_text(json.dumps(entry, indent=2, sort_keys=False))
    print_status("[DOWNLOAD] wrote %s" % (entry_path,))


def download_manifest(manifest_path, base_download_root=None, before_download=None, after_download=None):
    manifest_path = Path(manifest_path)
    manifest = read_manifest(manifest_path)
    download_root = Path(base_download_root) if base_download_root else manifest_path.parent / "downloads"
    download_root.mkdir(parents=True, exist_ok=True)
    entries = manifest.get("entries", [])
    todo = [
        entry for entry in entries
        if str(entry.get("download_command") or "").strip() and entry.get("request_status") != "downloaded"
    ]
    print_status("[DOWNLOAD] total todo=%d" % (len(todo),))
    for index, entry in enumerate(todo, start=1):
        project_code = str(entry.get("project_code") or "").strip()
        if not project_code:
            raise ValueError("Manifest entry is missing project_code.")
        project_folder = download_root / project_code
        project_folder.mkdir(parents=True, exist_ok=True)
        entry["download_root"] = str(project_folder)
        entry["request_status"] = "downloading"
        entry["download_attempts"] = int(entry.get("download_attempts") or 0) + 1
        entry["request_finished_at"] = None
        print_status("[DOWNLOAD] %d/%d project=%s" % (index, len(todo), project_code))
        _write_entry_json(entry, project_folder)
        write_manifest(manifest, manifest_path)
        if before_download is not None:
            before_download(entry)
        try:
            tokens = prepare_download_command(entry.get("download_command"), project_folder)
            return_code, output = run_download_command(tokens)
            if return_code != 0:
                entry["request_status"] = "error"
                entry["request_finished_at"] = now_iso()
                entry["last_error"] = output[-4000:]
                _write_entry_json(entry, project_folder)
                write_manifest(manifest, manifest_path)
                print_status("[DOWNLOAD] error project=%s rc=%s" % (project_code, return_code))
                continue
            entry["request_status"] = "downloaded"
            entry["request_finished_at"] = now_iso()
            entry["last_error"] = None
            _write_entry_json(entry, project_folder)
            write_manifest(manifest, manifest_path)
            if after_download is not None:
                after_download(entry, str(project_folder))
            print_status("[DOWNLOAD] done project=%s" % (project_code,))
        except Exception as exc:
            entry["request_status"] = "error"
            entry["request_finished_at"] = now_iso()
            entry["last_error"] = str(exc)
            _write_entry_json(entry, project_folder)
            write_manifest(manifest, manifest_path)
            raise
    return manifest
