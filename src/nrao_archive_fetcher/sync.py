"""Keep a local manifest and a CHPC manifest in step, and split CHPC work across parallel jobs.

Each side owns different fields, so syncing never has to resolve conflicts:

- Local (``import-email``) owns the request fields: ``download_command``, ``request_error``,
  ``request_failed_at`` and the statuses ``request_ready`` / ``request_failed``.
- CHPC (download + extraction) owns ``PROCESSING_FIELDS`` and the ``PROCESSING_STATUSES``.

``sync_requests`` copies request fields from the local copy into the CHPC manifest.
``merge_shards`` copies processing fields from the shard manifests into the CHPC manifest.
"""

from __future__ import annotations

import re
from pathlib import Path

from .manifest import read_manifest, write_manifest
from .utils import now_iso, print_status


PROCESSING_STATUSES = ("downloading", "downloaded", "error", "extracting", "extracted", "extraction_error")
# Statuses where the data is complete on disk: a new request link must not touch them.
# ("downloading" and "extraction_error" may be stuck: a timed-out job or a broken download, so they take a new link.)
LOCKED_STATUSES = ("downloaded", "extracting", "extracted")
RETRY_STATUSES = ("error", "downloading", "extraction_error")
PROCESSING_FIELDS = (
    "request_status",
    "request_finished_at",
    "download_root",
    "download_attempts",
    "last_error",
    "extracted_ms",
    "selected_spw",
    "flux_estimate",
    "extraction_metadata",
    "extraction_finished_at",
    "original_download_deleted",
)
SHARD_RE = re.compile(r"\.shard-(\d+)-of-(\d+)\.json$")


def _command(entry):
    return str(entry.get("download_command") or "").strip()


def _set_ready(target, source):
    target["download_command"] = source.get("download_command")
    target["request_status"] = "request_ready"
    target["request_finished_at"] = source.get("request_finished_at") or now_iso()
    target.pop("request_error", None)
    target.pop("request_failed_at", None)


def sync_requests(local_path, target_path, dry_run=False):
    """Copy new download links and request failures from a local manifest copy into the CHPC manifest.

    Entries are matched by entry_id. Entries that are downloaded or extracted are never changed.
    An entry whose download failed or got stuck (``error``, ``downloading``, ``extraction_error``)
    gets the new link and is retried.
    """
    local = read_manifest(local_path)
    target = read_manifest(target_path)
    by_id = {entry.get("entry_id"): entry for entry in target.get("entries", []) if entry.get("entry_id")}
    counts = {"new": 0, "retry": 0, "updated": 0, "failed": 0, "locked": 0, "unknown": 0}
    for source in local.get("entries", []):
        entry_id = source.get("entry_id")
        entry = by_id.get(entry_id)
        if entry is None:
            counts["unknown"] += 1
            print_status("[SYNC] not in target manifest: %s" % (entry_id,))
            continue
        status = entry.get("request_status") or ""
        local_command = _command(source)
        if local_command:
            if local_command == _command(entry):
                continue
            if status in LOCKED_STATUSES:
                counts["locked"] += 1
                print_status("[SYNC] kept %s: already %s" % (entry_id, status))
                continue
            kind = "new" if not _command(entry) else "retry" if status in RETRY_STATUSES else "updated"
            _set_ready(entry, source)
            if kind == "retry":
                entry["last_error"] = None
            counts[kind] += 1
            print_status("[SYNC] %s %s" % (kind, entry_id))
        elif source.get("request_status") == "request_failed":
            if _command(entry) or status in PROCESSING_STATUSES:
                continue
            if status == "request_failed" and entry.get("request_error") == source.get("request_error"):
                continue
            entry["request_status"] = "request_failed"
            entry["request_error"] = source.get("request_error")
            entry["request_failed_at"] = source.get("request_failed_at")
            counts["failed"] += 1
            print_status("[SYNC] failed %s: %s" % (entry_id, source.get("request_error")))
    print_status(
        "[SYNC] %d new link(s), %d retried, %d updated, %d failure(s), %d kept (already downloaded), %d unknown"
        % (counts["new"], counts["retry"], counts["updated"], counts["failed"], counts["locked"], counts["unknown"])
    )
    if not dry_run:
        write_manifest(target, target_path)
    return counts


def shard_path(manifest_path, index, count):
    manifest_path = Path(manifest_path)
    return manifest_path.with_name("%s.shard-%d-of-%d.json" % (manifest_path.stem, index, count))


def _copy_processing(target, source):
    for field in PROCESSING_FIELDS:
        if field == "request_status":
            if source.get(field) in PROCESSING_STATUSES:
                target[field] = source[field]
        elif field in source:
            target[field] = source[field]


def write_shard(manifest_path, index, count):
    """Write the shard manifest for job ``index`` of ``count`` and return its path.

    The shard holds the entries at positions index, index + count, ... of the main manifest
    (the manifest is sorted by size, so every shard gets a similar mix). Request fields come
    from the main manifest. Progress already saved in an earlier version of this shard is kept.
    """
    if count < 1 or not 0 <= index < count:
        raise ValueError("shard index must be in 0..%d, got %d" % (count - 1, index))
    manifest = read_manifest(manifest_path)
    entries = [dict(entry) for position, entry in enumerate(manifest.get("entries", [])) if position % count == index]
    path = shard_path(manifest_path, index, count)
    if path.is_file():
        previous = {entry.get("entry_id"): entry for entry in read_manifest(path).get("entries", [])}
        for entry in entries:
            old = previous.get(entry.get("entry_id"))
            # A different link means the entry was re-requested after this progress was saved.
            if old is not None and _command(old) == _command(entry):
                _copy_processing(entry, old)
    shard = {key: value for key, value in manifest.items() if key != "entries"}
    shard["shard"] = {"of": str(Path(manifest_path).name), "index": index, "count": count}
    shard["entries"] = entries
    write_manifest(shard, path)
    return path


def merge_shards(manifest_path, dry_run=False):
    """Copy download/extraction progress from all shard manifests back into the main manifest."""
    manifest_path = Path(manifest_path)
    manifest = read_manifest(manifest_path)
    by_id = {entry.get("entry_id"): entry for entry in manifest.get("entries", []) if entry.get("entry_id")}
    paths = sorted(
        (path for path in manifest_path.parent.glob(manifest_path.stem + ".shard-*-of-*.json") if SHARD_RE.search(path.name)),
        key=lambda path: path.stat().st_mtime,
    )
    seen = {}
    merged = 0
    for path in paths:
        for source in read_manifest(path).get("entries", []):
            entry_id = source.get("entry_id")
            entry = by_id.get(entry_id)
            if entry is None:
                print_status("[MERGE] %s: entry not in main manifest: %s" % (path.name, entry_id))
                continue
            if entry_id in seen:
                print_status("[MERGE] %s is in %s and %s, using the newer file" % (entry_id, seen[entry_id], path.name))
            seen[entry_id] = path.name
            if _command(source) != _command(entry):
                # The entry got a new link (sync-requests) after this shard was written: its progress is stale.
                continue
            before = {field: entry.get(field) for field in PROCESSING_FIELDS}
            _copy_processing(entry, source)
            if before != {field: entry.get(field) for field in PROCESSING_FIELDS}:
                merged += 1
    print_status("[MERGE] %d shard file(s), %d entr%s updated" % (len(paths), merged, "y" if merged == 1 else "ies"))
    if not dry_run:
        write_manifest(manifest, manifest_path)
    return merged
