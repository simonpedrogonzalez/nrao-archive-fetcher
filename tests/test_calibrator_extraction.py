import json
from pathlib import Path

import numpy as np

from workflows.radioastro_calibrators.extract_entry import extract_entry
from workflows.radioastro_calibrators.flux_weblog import parse_flux_text


def test_parse_retained_17b078_fluxboot_fixture():
    path = Path(__file__).parent / "fixtures" / "17B-078_fluxboot.log"
    result = parse_flux_text(path.read_text(), "J0012-3954", source_file=path)
    assert result["stokes_i_jy"] == 0.70096222557855437
    assert result["reference_frequency_ghz"] == 4.68
    assert result["spectral_index"] == -0.067825109916211879
    assert result["fit_snr"] == 3201.53460341


class FakeTable:
    def open(self, path):
        self.path = Path(path)

    def close(self):
        pass

    def colnames(self):
        return ["DATA", "CORRECTED_DATA"]

    def nrows(self):
        return 2

    def getcell(self, name, row):
        assert name == "CHAN_FREQ"
        return np.array([4.0e9, 4.02e9]) if row == 0 else np.array([5.0e9, 5.08e9])

    def getcol(self, name):
        if self.path.name == "FIELD":
            return np.array(["J0012-3954"])
        if self.path.name == "DATA_DESCRIPTION":
            return np.array([0, 1])
        if name == "DATA_DESC_ID":
            return np.array([0, 1, 1])
        if name == "FLAG":
            return np.zeros((2, 1, 3), dtype=bool)
        raise AssertionError((self.path, name))


def test_extract_entry_selects_field_spw_and_updates_metadata(tmp_path):
    download = tmp_path / "downloads"
    source_ms = download / "pipeline" / "source.ms"
    source_ms.mkdir(parents=True)
    output = tmp_path / "extracted"
    calls = {}

    def fake_split(**kwargs):
        calls["split"] = kwargs
        Path(kwargs["outputvis"]).mkdir(parents=True)

    def fake_listobs(**kwargs):
        calls["listobs"] = kwargs
        Path(kwargs["listfile"]).write_text("listobs")

    entry = {
        "entry_id": "0012-399_obs",
        "gain_calibrator_name": "J0012-3954",
        "band_guess": "C",
    }
    result = extract_entry(entry, download, output, FakeTable, fake_split, fake_listobs)
    assert calls["split"]["field"] == "J0012-3954"
    assert calls["split"]["spw"] == "1"
    assert calls["split"]["datacolumn"] == "corrected"
    assert calls["split"]["keepflags"] is True
    assert Path(result["extracted_ms"]).is_dir()
    assert Path(result["listobs"]).is_file()
    metadata = json.loads((output / "0012-399_obs" / "extraction_metadata.json").read_text())
    assert metadata["selected_spw"] == "1"
