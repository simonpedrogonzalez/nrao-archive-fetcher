import csv

from workflows.radioastro_calibrators.build_manifests import (
    TransientArchiveError,
    archive_candidates,
    build_all,
    entry_from_values,
    validate_collections,
)


FIELDS = [
    "name", "ra", "dec", "band_guess", "configs", "usable_configs", "gain_array_config",
    "size_gb", "gain_calibrator_name", "access_url", "status", "wget_error",
]


def write_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def row(name, obs_id, size, configs="A,B"):
    return {
        "name": name,
        "ra": "00:00:00",
        "dec": "+00:00:00",
        "band_guess": "C",
        "configs": configs,
        "usable_configs": configs,
        "gain_array_config": "A",
        "size_gb": size,
        "gain_calibrator_name": "J" + name,
        "access_url": "https://data.nrao.edu/portal/#/productViewer/" + obs_id,
        "status": "old",
        "wget_error": "old error",
    }


def candidate(spec, obs_id, size):
    return entry_from_values(
        spec["calibrator_id"], obs_id, obs_id.split(".")[0], "GAIN-" + spec["calibrator_id"],
        "https://data.nrao.edu/portal/#/productViewer/" + obs_id, size,
        spec["band_guess"], spec["usable_configs"], ra=spec["ra"], dec=spec["dec"],
    )


def test_four_manifests_are_disjoint_sorted_and_repeated_quota_is_obeyed(tmp_path):
    source = tmp_path / "radioastro"
    small_rows = [row("downloaded", "P.sb0", "1"), row("small", "P.sb1", "2"), row("z", "", "")]
    missing_rows = [row("missing", "", "")]
    one_hit_rows = [row("large", "P.sb3", "20"), row("small", "P.sb1", "2")]
    write_csv(source / "collect/small_subset/small_selection.csv", small_rows)
    write_csv(source / "collect/vla_calibrators_one_hit_missed.csv", missing_rows)
    write_csv(source / "collect/vla_calibrators_one_hit.csv", one_hit_rows)

    candidates = {
        "downloaded": [candidate({"calibrator_id": "downloaded", "band_guess": "C", "usable_configs": ["A"], "ra": "", "dec": ""}, "P.sb0", 1),
                       candidate({"calibrator_id": "downloaded", "band_guess": "C", "usable_configs": ["A"], "ra": "", "dec": ""}, "P.sb4", 4),
                       candidate({"calibrator_id": "downloaded", "band_guess": "C", "usable_configs": ["A"], "ra": "", "dec": ""}, "P.sb5", 5),
                       candidate({"calibrator_id": "downloaded", "band_guess": "C", "usable_configs": ["A"], "ra": "", "dec": ""}, "P.sb6", 6),
                       candidate({"calibrator_id": "downloaded", "band_guess": "C", "usable_configs": ["A"], "ra": "", "dec": ""}, "P.sb7", 7)],
        "small": [candidate({"calibrator_id": "small", "band_guess": "C", "usable_configs": ["A"], "ra": "", "dec": ""}, "P.sb1", 2),
                  candidate({"calibrator_id": "small", "band_guess": "C", "usable_configs": ["A"], "ra": "", "dec": ""}, "P.sb8", 8)],
        "missing": [candidate({"calibrator_id": "missing", "band_guess": "C", "usable_configs": ["A"], "ra": "", "dec": ""}, "P.sb2", 3),
                    candidate({"calibrator_id": "missing", "band_guess": "C", "usable_configs": ["A"], "ra": "", "dec": ""}, "P.sb9", 9)],
        "large": [candidate({"calibrator_id": "large", "band_guess": "C", "usable_configs": ["A"], "ra": "", "dec": ""}, "P.sb3", 20)],
    }

    manifests = build_all(
        source,
        tmp_path / "runs",
        candidate_finder=lambda spec: candidates.get(spec["calibrator_id"], []),
        downloaded_obs_ids={"P.sb0"},
        downloaded_by_obs_id={"P.sb0": {"calibrator_id": "downloaded", "calibrator_ids": ["downloaded"]}},
    )
    small, missing, large, repeated = manifests
    assert [entry["obs_id"] for entry in small["entries"]] == ["P.sb1"]
    assert [entry["obs_id"] for entry in missing["entries"]] == ["P.sb2"]
    assert [entry["obs_id"] for entry in large["entries"]] == ["P.sb3"]
    repeated_downloaded = [entry for entry in repeated["entries"] if entry["calibrator_id"] == "downloaded"]
    assert len(repeated_downloaded) == 3
    assert len([entry for entry in repeated["entries"] if entry["calibrator_id"] == "small"]) == 1
    assert len([entry for entry in repeated["entries"] if entry["calibrator_id"] == "missing"]) == 1
    validate_collections({"P.sb0"}, manifests)
    for manifest in manifests:
        sizes = [entry["estimated_size_gb"] for entry in manifest["entries"]]
        assert sizes == sorted(sizes)
        for entry in manifest["entries"]:
            assert set((
                "entry_id", "obs_id", "project_code", "calibrator_id", "gain_calibrator_name",
                "viewer_url", "estimated_size_gb", "band_guess", "usable_configs", "request_status",
                "download_command", "download_root", "extracted_ms", "selected_spw", "flux_estimate",
            )).issubset(entry)


def test_schema_discovery_failure_is_transient(monkeypatch):
    monkeypatch.setattr(
        "workflows.radioastro_calibrators.build_manifests.NRAOQuery.where_in_circle",
        lambda self, center, radius: (_ for _ in ()).throw(RuntimeError("TAP unavailable")),
    )
    spec = {
        "calibrator_id": "cal",
        "ra": "00:00:00",
        "dec": "+00:00:00",
        "band_guess": "C",
        "usable_configs": ["A"],
    }
    try:
        archive_candidates(spec)
    except TransientArchiveError as exc:
        assert "TAP query failed" in str(exc)
    else:
        raise AssertionError("schema failure was not classified as transient")
