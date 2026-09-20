import csv
import runpy
from pathlib import Path

from workflows.radioastro_calibrators.generate_inventory import build_inventory, generate_inventory


def _write_csv(path, rows):
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["name", "access_url", "gain_calibrator_name", "extracted_ms"],
        )
        writer.writeheader()
        writer.writerows(rows)


def test_inventory_uses_existing_primary_ms_and_ignores_z(tmp_path):
    csv_path = tmp_path / "small_selection.csv"
    extracted = tmp_path / "extracted"
    ms = extracted / "0012-399" / "0012-399" / "0012-399.ms"
    ms.mkdir(parents=True)
    _write_csv(
        csv_path,
        [
            {
                "name": "0012-399",
                "access_url": "https://data.nrao.edu/portal/#/productViewer/17B-078.sb1.eb2.3",
                "gain_calibrator_name": "J0012-3954",
                "extracted_ms": "/stale/path.ms",
            },
            {"name": "z", "access_url": "", "gain_calibrator_name": "", "extracted_ms": ""},
            {
                "name": "not-downloaded",
                "access_url": "https://data.nrao.edu/portal/#/productViewer/other.sb1",
                "gain_calibrator_name": "J0000",
                "extracted_ms": "",
            },
        ],
    )
    inventory = build_inventory(csv_path, extracted)
    assert list(inventory) == ["17B-078.sb1.eb2.3"]
    assert inventory["17B-078.sb1.eb2.3"]["project_code"] == "17B-078"
    assert inventory["17B-078.sb1.eb2.3"]["historical_extracted_path"] == str(ms.resolve())


def test_generated_inventory_is_deterministic_importable_python(tmp_path):
    csv_path = tmp_path / "small_selection.csv"
    extracted = tmp_path / "extracted"
    ms = extracted / "b" / "b" / "b.ms"
    ms.mkdir(parents=True)
    _write_csv(
        csv_path,
        [{
            "name": "b",
            "access_url": "https://data.nrao.edu/portal/#/productViewer/P_sb2.eb1",
            "gain_calibrator_name": "gain-b",
            "extracted_ms": "",
        }],
    )
    first = tmp_path / "first.py"
    second = tmp_path / "second.py"
    generate_inventory(csv_path, extracted, first)
    generate_inventory(csv_path, extracted, second)
    assert first.read_text() == second.read_text()
    values = runpy.run_path(str(first))
    assert values["ALREADY_DOWNLOADED_CALIBRATOR_IDS"] == frozenset({"b"})
    assert values["ALREADY_DOWNLOADED_GAIN_FIELDS"] == frozenset({"gain-b"})


def test_one_observation_can_represent_multiple_calibrators(tmp_path):
    csv_path = tmp_path / "small_selection.csv"
    extracted = tmp_path / "extracted"
    rows = []
    for calibrator in ("b", "a"):
        (extracted / calibrator / calibrator / (calibrator + ".ms")).mkdir(parents=True)
        rows.append({
            "name": calibrator,
            "access_url": "https://data.nrao.edu/portal/#/productViewer/P.sb1.eb1",
            "gain_calibrator_name": "gain",
            "extracted_ms": "",
        })
    _write_csv(csv_path, rows)
    output = tmp_path / "inventory.py"
    inventory = generate_inventory(csv_path, extracted, output)
    assert list(inventory) == ["P.sb1.eb1"]
    assert inventory["P.sb1.eb1"]["calibrator_ids"] == ["a", "b"]
    assert runpy.run_path(str(output))["ALREADY_DOWNLOADED_CALIBRATOR_IDS"] == frozenset({"a", "b"})
