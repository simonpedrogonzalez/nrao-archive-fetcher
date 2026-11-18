import json
import math
import runpy
from pathlib import Path

import numpy as np
import pytest

from workflows.radioastro_calibrators.extract_entry import extract_entry
from workflows.radioastro_calibrators.flux_weblog import build_estimate, evaluate, parse_flux_text, recheck, select_model


def test_extract_script_loads_without_package_context():
    script = Path(__file__).parents[1] / "workflows/radioastro_calibrators/extract_entry.py"
    namespace = runpy.run_path(str(script), run_name="casa_script_import_test")
    assert "extract_entry" in namespace


def test_parse_retained_17b078_fluxboot_fixture():
    path = Path(__file__).parent / "fixtures" / "17B-078_fluxboot.log"
    models, fits = parse_flux_text(path.read_text(), "J0012-3954", source_file=path)
    result = build_estimate(models, fits, "J0012-3954", spw_center_ghz=4.9)   # no spw argument: whole observation
    assert result["status"] == "available"
    assert result["stokes_i_jy"] == 0.70096222557855437
    assert result["reference_frequency_ghz"] == 4.68
    assert result["spectral_index"] == -0.067825109916211879
    assert result["spectral_index_coefficients"] == [-0.067825109916211879]
    assert result["fit_snr"] == 3201.53460341
    # The reference frequency is a normalization point, not a band limit.
    far = build_estimate(models, fits, "J0012-3954", spw_center_ghz=9.0)
    assert far["status"] == "available" and far["flux_at_spw_center_jy"] == evaluate(far, 9.0)


SETJY = (
    "2023-02-03 00:24:07\tINFO\tfluxscale::pipeline.infrastructure.jobrequest::casa\t"
    "Executing setjy(vis='calibrators.ms', field='J0239-0234', spw='{spw}', standard='manual', "
    "fluxdensity=[{flux}, 0, 0, 0], spix=[0.5910513751904884, -0.12], "
    "reffreq='5468221464.542124Hz', usescratch=True)"
)


def test_parse_flux_keeps_every_spix_coefficient():
    models, _ = parse_flux_text(SETJY.format(spw="0,1", flux=0.4332708876619984), "J0239-0234")
    result = build_estimate(models, [], "J0239-0234", selected_spw="1", spw_center_ghz=5.0)
    assert result["status"] == "available"
    assert result["stokes_i_jy"] == 0.4332708876619984
    assert result["spectral_index_coefficients"] == [0.5910513751904884, -0.12]
    assert abs(result["reference_frequency_ghz"] - 5.468221464542124) < 1e-12
    assert result["setjy_spws"] == [0, 1]


def test_spw_coverage_ambiguity_and_invalid_models():
    one = SETJY.format(spw="0,1", flux=0.43)
    assert select_model(parse_flux_text(one, "J0239-0234")[0], "2", 5.0)[0] == "unavailable"
    assert select_model(parse_flux_text(one, "OTHER")[0], "1", 5.0)[0] == "unavailable"
    # Duplicates of the same model (eb.ms, calibrators.ms, weblog copies) are not ambiguous.
    assert select_model(parse_flux_text(one + "\n" + one, "J0239-0234")[0], "1", 5.0)[0] == "available"
    two = one + "\n" + SETJY.format(spw="1", flux=0.5)
    assert select_model(parse_flux_text(two, "J0239-0234")[0], "1", 5.0)[0] == "ambiguous"
    assert select_model(parse_flux_text(two, "J0239-0234")[0], "0", 5.0)[0] == "available"
    bad = SETJY.format(spw="0", flux=-1.0)
    assert select_model(parse_flux_text(bad, "J0239-0234")[0], "0", 5.0)[0] == "invalid"
    assert select_model(parse_flux_text(one, "J0239-0234")[0], None, None)[0] == "unavailable"


def test_whole_observation_models_cross_nominal_band_edges():
    unlisted = lambda flux, ref: SETJY.format(spw="0", flux=flux).replace("spw='0', ", "").replace(
        "5468221464.542124Hz", ref)
    edge = parse_flux_text(unlisted(0.9, "1.988GHz"), "J0239-0234")[0]
    result = build_estimate(edge, [], "J0239-0234", selected_spw="3", spw_center_ghz=2.051)  # L ref, S window
    assert result["status"] == "available" and result["reference_frequency_ghz"] == 1.988
    assert result["flux_at_spw_center_jy"] == evaluate(result, 2.051)
    # A call listing the SPW takes precedence over a whole-observation call.
    both = edge + parse_flux_text(SETJY.format(spw="3", flux=0.7), "J0239-0234")[0]
    assert select_model(both, "3", 2.051)[1]["stokes_i_jy"] == 0.7
    assert select_model(both, "4", 2.051)[1]["stokes_i_jy"] == 0.9
    # Different whole-observation models conflict; another calibrator's model is never used.
    two = edge + parse_flux_text(unlisted(1.1, "3.0GHz"), "J0239-0234")[0]
    assert select_model(two, "3", 2.051)[0] == "ambiguous"
    assert select_model(parse_flux_text(unlisted(0.9, "1.988GHz"), "OTHER")[0], "3", 2.051)[0] == "unavailable"


def test_evaluate_uses_casa_log10_curvature():
    model = dict(stokes_i_jy=2.0, reference_frequency_ghz=4.0, spectral_index_coefficients=[-0.5, 0.3])
    assert evaluate(model, 4.0) == 2.0
    x = math.log10(8.0 / 4.0)
    assert abs(evaluate(model, 8.0) - 2.0 * 2.0 ** (-0.5 + 0.3 * x)) < 1e-15


def test_recheck_from_source_text_and_logs(tmp_path):
    entry = tmp_path / "entry"
    entry.mkdir()
    line = SETJY.format(spw="0,1", flux=0.43)
    (entry / "extraction_metadata.json").write_text(json.dumps(dict(
        entry_id="e1", gain_calibrator_name="J0239-0234", selected_spw="1", spw_center_ghz=5.0)))
    old = dict(status="available", source_text=line, source_file="old.log", fit_snr=12.0)
    (entry / "flux_estimate.json").write_text(json.dumps(old))
    result = recheck(entry)
    assert result["status"] == "available" and result["recovered_from"] == "source_text"
    assert result["ambiguity_checked"] is False and result["previous"] == old
    assert result["spectral_index_coefficients"] == [0.5910513751904884, -0.12]
    (entry / "extraction_metadata.json").write_text(json.dumps(dict(
        entry_id="e1", gain_calibrator_name="J0239-0234", selected_spw="5", spw_center_ghz=5.0)))
    assert recheck(entry)["status"] == "needs_logs"   # per-SPW pipelines log one call per SPW
    old["source_text"] = SETJY.format(spw="0", flux=0.43).replace("spw='0', ", "")
    (entry / "flux_estimate.json").write_text(json.dumps(old))
    (entry / "extraction_metadata.json").write_text(json.dumps(dict(
        entry_id="e1", gain_calibrator_name="J0239-0234", selected_spw="5", spw_center_ghz=None)))
    result = recheck(entry)   # a whole-observation line applies to any extracted SPW
    assert result["status"] == "available" and result["setjy_spws"] is None
    old["source_text"] = SETJY.format(spw="0,1", flux=0.43)
    (entry / "flux_estimate.json").write_text(json.dumps(old))
    logs = tmp_path / "downloads" / "e1" / "pipeline"
    logs.mkdir(parents=True)
    (logs / "casa_commands.log").write_text(SETJY.format(spw="4,5", flux=0.61))
    result = recheck(entry, tmp_path / "downloads" / "e1")
    assert result["status"] == "available" and result["recovered_from"] == "logs"
    assert result["stokes_i_jy"] == 0.61 and result["previous"] == old


def test_recheck_keeps_schema2_result_after_logs_are_removed(tmp_path):
    entry = tmp_path / 'entry'
    entry.mkdir()
    metadata = dict(entry_id='e1', gain_calibrator_name='J0239-0234',
                    selected_spw='1', spw_center_ghz=5.0)
    (entry / 'extraction_metadata.json').write_text(json.dumps(metadata))
    logs = tmp_path / 'logs'
    logs.mkdir()
    (logs / 'casa_commands.log').write_text(SETJY.format(spw='0,1', flux=0.43))
    result = recheck(entry, logs)
    assert result['status'] == 'available'
    (entry / 'flux_estimate.json').write_text(json.dumps(result))
    assert recheck(entry) == result
    assert recheck(entry, tmp_path / 'removed_logs') == result
    metadata['selected_spw'] = '2'
    (entry / 'extraction_metadata.json').write_text(json.dumps(metadata))
    assert recheck(entry)['status'] != 'available'


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
        if self.path.name == "FIELD" and name == "PHASE_DIR":
            # J0012-3954 at 00:12:59.9 -39:54:26 (radians, shape 2 x 1 x nfield)
            return np.radians(np.array([[[3.249583]], [[-39.907222]]]))
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
        "ra": "00:12:59.9",
        "dec": "-39:54:26",
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


def test_extract_entry_rejects_a_field_of_another_source(tmp_path):
    download = _source_ms(tmp_path)
    split_calls = []
    entry = {"entry_id": "1407+284_obs", "gain_calibrator_name": "J0012-3954", "band_guess": "C",
             "ra": "14:07:00.394", "dec": "+28:27:14.69"}
    with pytest.raises(ValueError, match="not the requested source"):
        extract_entry(entry, download, tmp_path / "out", FakeTable, lambda **k: split_calls.append(k), None)
    del entry["ra"], entry["dec"]
    with pytest.raises(ValueError, match="no catalog position"):
        extract_entry(entry, download, tmp_path / "out", FakeTable, lambda **k: split_calls.append(k), None)
    assert split_calls == []


def test_field_names_are_checked_by_position():
    from workflows.radioastro_calibrators.field_match import jname_consistent, separation_arcsec, sky_degrees

    ra, dec = sky_degrees("14:07:00.394", "+28:27:14.69")
    assert jname_consistent("J1407+2827", ra, dec) is True
    assert jname_consistent("J1125+2610", ra, dec) is False
    assert jname_consistent("J1227+3635_S", *sky_degrees("12:27:58.73", "+36:35:11.8")) is True
    assert jname_consistent("J0958+6533 CG", *sky_degrees("9:58:47.25", "+65:33:54.8")) is True
    assert jname_consistent("J2139+143", *sky_degrees("21:39:01.31", "+14:23:35.99")) is True
    assert jname_consistent("J1150-0023", *sky_degrees("11:50:43.87", "-0:23:54.2")) is True
    assert jname_consistent("3C286", ra, dec) is None
    assert abs(separation_arcsec(10.0, 0.0, 10.0, 1 / 3600) - 1.0) < 1e-6
