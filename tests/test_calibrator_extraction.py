import json
import runpy
from pathlib import Path

import numpy as np

from workflows.radioastro_calibrators.extract_entry import extract_entry
from workflows.radioastro_calibrators.flux_weblog import parse_flux_text


def test_extract_script_loads_without_package_context():
    script = Path(__file__).parents[1] / "workflows/radioastro_calibrators/extract_entry.py"
    namespace = runpy.run_path(str(script), run_name="casa_script_import_test")
    assert "extract_entry" in namespace


def test_parse_retained_17b078_fluxboot_fixture():
    path = Path(__file__).parent / "fixtures" / "17B-078_fluxboot.log"
    result = parse_flux_text(path.read_text(), "J0012-3954", source_file=path)
    assert result["stokes_i_jy"] == 0.70096222557855437
    assert result["reference_frequency_ghz"] == 4.68
    assert result["spectral_index"] == -0.067825109916211879
    assert result["fit_snr"] == 3201.53460341


def test_parse_flux_with_spix_list_from_newer_pipelines():
    line = (
        "2023-02-03 00:24:07\tINFO\tfluxscale::pipeline.infrastructure.jobrequest::casa\t"
        "Executing setjy(vis='calibrators.ms', field='J0239-0234', spw='0,1', standard='manual', "
        "fluxdensity=[0.4332708876619984, 0, 0, 0], spix=[0.5910513751904884, -0.12], "
        "reffreq='5468221464.542124Hz', usescratch=True)"
    )
    result = parse_flux_text(line, "J0239-0234")
    assert result["stokes_i_jy"] == 0.4332708876619984
    assert result["spectral_index"] == 0.5910513751904884
    assert abs(result["reference_frequency_ghz"] - 5.468221464542124) < 1e-12


class FakeTable:
    # FIELD_ID of each main-table row (DATA_DESC_ID 0, 1, 1); FIELD 0 is the gain calibrator.
    row_fields = (0, 0, 0)

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
        if name == "FIELD_ID":
            return np.array(self.row_fields)
        raise AssertionError((self.path, name))


def _source_ms(tmp_path):
    download = tmp_path / "downloads"
    source_ms = download / "pipeline" / "source.ms"
    source_ms.mkdir(parents=True)
    (source_ms / "table.dat").touch()
    return download


def test_select_spw_ignores_flags_and_skips_spws_without_gain_calibrator_rows(tmp_path):
    from workflows.radioastro_calibrators.extract_entry import select_spw

    class GainCalOnlyInSpw0(FakeTable):
        row_fields = (0, 1, 1)  # the wider SPW 1 only has rows for another field

    ms = _source_ms(tmp_path) / "pipeline" / "source.ms"
    assert select_spw(ms, "C", GainCalOnlyInSpw0, [0])["spw"] == 0
    assert select_spw(ms, "C", FakeTable, [0])["spw"] == 1


def test_extract_entry_selects_field_spw_and_updates_metadata(tmp_path):
    download = tmp_path / "downloads"
    source_ms = download / "pipeline" / "source.ms"
    source_ms.mkdir(parents=True)
    (source_ms / "table.dat").touch()
    output = tmp_path / "extracted"
    calls = {}

    def fake_split(**kwargs):
        calls["split"] = kwargs
        Path(kwargs["outputvis"]).mkdir(parents=True)
        (Path(kwargs["outputvis"]) / "table.dat").touch()

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
