"""Gain-calibrator flux model from the NRAO pipeline's manual setjy calls.

The pipeline (hifv_fluxboot) bootstraps each gain calibrator and applies the result with
``setjy(standard='manual', field=<cal>, fluxdensity=[S0, 0, 0, 0], spix=[c0, c1, ...],
reffreq='<f0>', spw='<ids>')``. CASA evaluates it as

    S(f) = S0 * (f/f0) ** (c0 + c1*log10(f/f0) + c2*log10(f/f0)**2 + ...)

(log base 10: checked numerically against CASA 6 setjy with a curvature term).

Only calls for the extracted gain calibrator are considered. Calls listing SPWs apply only
when they include the extracted SPW, and take precedence. Otherwise calls without an spw
argument apply to the whole observation: the reference frequency is the model's normalization
point, not a band limit, so a model referenced across a nominal band edge is still used and
evaluated at the SPW frequency. Several different applicable models are "ambiguous" and rejected.

Sidecar schema 2 (flux_estimate.json) keeps every coefficient, the evidence and the decision.
Rewrite existing schema-1 sidecars of extracted entries (previous content kept under "previous"):

    python -m workflows.radioastro_calibrators.flux_weblog recheck --downloads-root <downloads> <entry dir>...

Logs come from <downloads>/<entry_id>/ when present; otherwise the saved source_text is used:
a line listing the extracted SPW, or a line without an spw argument, is accepted
(ambiguity_checked=false); a line listing other SPWs gives "needs_logs". The setjy calls are in the small casa_commands.log files.
"""
from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path


SCHEMA = 2
SPIX_CONVENTION = "S(f)=S0*(f/f0)**sum_k(spix[k]*log10(f/f0)**k)  (CASA setjy manual)"
FLOAT_RE = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"
FIT_RE = re.compile(
    r"(?P<field>\S+)\s+(?P<band>[A-Za-z]+)\s+fitted spectral index\s*&\s*SNR\s*=\s*"
    r"(?P<spix>%s)\s+(?P<snr>%s)" % (FLOAT_RE, FLOAT_RE),
    re.IGNORECASE,
)
BAND_RANGES_GHZ = {
    "L": (1.0, 2.0), "S": (2.0, 4.0), "C": (4.0, 8.0), "X": (8.0, 12.0),
    "KU": (12.0, 18.0), "K": (18.0, 26.5), "KA": (26.5, 40.0), "Q": (40.0, 50.0),
}
_UNIT_GHZ = {"hz": 1e-9, "khz": 1e-6, "mhz": 1e-3, "ghz": 1.0}


def band_for_ghz(frequency_ghz):
    for band, (low, high) in BAND_RANGES_GHZ.items():
        if low <= frequency_ghz <= high:
            return band
    return None


def _argument(text, name, pattern):
    match = re.search(r"\b%s\s*=\s*%s" % (re.escape(name), pattern), text, re.IGNORECASE)
    return match.group(1) if match else None


def _floats(text):
    return [float(x) for x in re.findall(FLOAT_RE, text)]


def _candidate_files(download_root):
    root = Path(download_root)
    paths = []
    paths.extend(sorted(root.glob("**/stage*/casapy.log")))
    paths.extend(sorted(root.glob("**/stage*/*.log")))
    paths.extend(sorted(root.glob("**/stage*/*.html")))
    paths.extend(sorted(root.glob("**/weblog*/**/*.log")))
    paths.extend(sorted(root.glob("**/weblog*/**/*.html")))
    paths.extend(sorted(root.glob("**/casa_commands.log")))
    seen = set()
    for path in paths:
        resolved = str(path.resolve())
        if resolved not in seen and path.is_file():
            seen.add(resolved)
            yield path


def _source_stage(path):
    for parent in (path,) + tuple(path.parents):
        if re.fullmatch(r"stage\d+", parent.name, re.IGNORECASE):
            return parent.name
    return "top-level"


def parse_setjy_line(line, gain_calibrator_name):
    """One manual setjy call for this field -> model dict, or None when the line is not one."""
    if "setjy(" not in line.lower():
        return None
    if _argument(line, "field", r"['\"]([^'\"]+)['\"]") != gain_calibrator_name:
        return None
    flux_text = _argument(line, "fluxdensity", r"(\[[^\]]*\]|%s)" % FLOAT_RE)
    spix_text = _argument(line, "spix", r"(\[[^\]]*\]|%s)" % FLOAT_RE)
    reffreq = re.search(r"\breffreq\s*=\s*['\"]\s*(%s)\s*([GMK]?Hz)['\"]" % FLOAT_RE, line, re.IGNORECASE)
    if flux_text is None or spix_text is None or reffreq is None:
        return None
    flux, spix = _floats(flux_text), _floats(spix_text)
    if not flux or not spix:
        return None
    spw_text = _argument(line, "spw", r"['\"]([^'\"]*)['\"]")
    spws = None
    if spw_text is not None and spw_text.strip():
        if not re.fullmatch(r"\s*\d+(\s*,\s*\d+)*\s*", spw_text):
            return dict(invalid="unsupported spw selection %r" % spw_text, source_text=line.strip())
        spws = sorted({int(x) for x in spw_text.split(",")})
    return dict(
        stokes_i_jy=flux[0],
        spectral_index_coefficients=spix,
        reference_frequency_ghz=float(reffreq.group(1)) * _UNIT_GHZ[reffreq.group(2).lower()],
        spws=spws,
        vis=_argument(line, "vis", r"['\"]([^'\"]+)['\"]"),
        source_text=line.strip(),
    )


def model_problem(model):
    """Reason a parsed model is unusable, or None."""
    if model.get("invalid"):
        return model["invalid"]
    values = [model["stokes_i_jy"], model["reference_frequency_ghz"], *model["spectral_index_coefficients"]]
    if not all(math.isfinite(v) for v in values):
        return "non-finite flux model value"
    if model["stokes_i_jy"] <= 0:
        return "non-positive Stokes I flux density"
    if model["reference_frequency_ghz"] <= 0:
        return "non-positive reference frequency"
    return None


def evaluate(model, frequency_ghz):
    """Stokes I (Jy) of a setjy manual model at frequency_ghz."""
    if not (math.isfinite(frequency_ghz) and frequency_ghz > 0):
        raise ValueError("frequency must be finite and positive")
    x = math.log10(frequency_ghz / model["reference_frequency_ghz"])
    exponent = sum(c * x ** k for k, c in enumerate(model["spectral_index_coefficients"]))
    return model["stokes_i_jy"] * 10 ** (x * exponent)


def _key(model):
    return (model["stokes_i_jy"], tuple(model["spectral_index_coefficients"]), model["reference_frequency_ghz"])


def applies(model, selected_spw=None):
    """True/False when the call's spw list does/does not include the SPW; None when the call has
    no spw list (it applies to the whole observation) or the SPW is unknown."""
    if model["spws"] is not None and selected_spw is not None:
        return int(selected_spw) in model["spws"]
    return None


def select_model(models, selected_spw=None, spw_center_ghz=None):
    """(status, model or None, reason) from every parsed setjy call for the field.

    spw_center_ghz is accepted for call compatibility; band labels never veto a model."""
    if not models:
        return "unavailable", None, "no manual setjy call for this field"
    valid = [m for m in models if model_problem(m) is None]
    if not valid:
        return "invalid", None, "; ".join(sorted({model_problem(m) for m in models}))
    verdicts = [applies(m, selected_spw) for m in valid]
    explicit = [m for m, ok in zip(valid, verdicts) if ok is True]
    unlisted = [m for m in valid if m["spws"] is None]   # whole-observation calls
    applicable = explicit or unlisted
    if not applicable:
        return "unavailable", None, "no setjy call covers the selected SPW"
    distinct = {_key(m) for m in applicable}
    if len(distinct) > 1:
        return "ambiguous", None, "%d different flux models cover the selected SPW" % len(distinct)
    return "available", applicable[0], None


def _fit_snr(fits, field, band):
    values = {float(f["snr"]) for f in fits if f["field"] == field and (band is None or f["band"].upper() == band)}
    return values.pop() if len(values) == 1 else None


def build_estimate(models, fits, gain_calibrator_name, *, selected_spw=None, spw_center_ghz=None,
                   band=None, recovered_from="logs", ambiguity_checked=True):
    status, model, reason = select_model(models, selected_spw, spw_center_ghz)
    spw_band = band_for_ghz(spw_center_ghz) if spw_center_ghz else None
    candidates = sorted({_key(m) for m in models if model_problem(m) is None}, key=lambda k: (k[2], k[0]))
    result = {
        "schema": SCHEMA,
        "status": status,
        "reason": reason,
        "gain_calibrator_name": gain_calibrator_name,
        "band": spw_band or band,
        "selected_spw": None if selected_spw is None else str(selected_spw),
        "spw_center_ghz": spw_center_ghz,
        "spix_convention": SPIX_CONVENTION,
        "stokes_i_jy": None,
        "reference_frequency_ghz": None,
        "spectral_index": None,
        "spectral_index_coefficients": None,
        "setjy_spws": None,
        "flux_at_spw_center_jy": None,
        "fit_snr": None,
        "source_stage": None,
        "source_file": None,
        "source_text": None,
        "recovered_from": recovered_from,
        "ambiguity_checked": ambiguity_checked,
        "candidate_models": [dict(stokes_i_jy=k[0], spectral_index_coefficients=list(k[1]),
                                  reference_frequency_ghz=k[2]) for k in candidates],
    }
    if model is not None:
        result.update(
            stokes_i_jy=model["stokes_i_jy"],
            reference_frequency_ghz=model["reference_frequency_ghz"],
            spectral_index=model["spectral_index_coefficients"][0],
            spectral_index_coefficients=list(model["spectral_index_coefficients"]),
            setjy_spws=model["spws"],
            flux_at_spw_center_jy=evaluate(model, spw_center_ghz) if spw_center_ghz else None,
            fit_snr=_fit_snr(fits, gain_calibrator_name, spw_band),
            source_stage=model.get("source_stage"),
            source_file=None if model.get("source_file") is None else str(model["source_file"]),
            source_text=model["source_text"],
        )
    return result


def parse_flux_text(text, gain_calibrator_name, source_file=""):
    """(models, fits) from one log/HTML text."""
    models, fits = [], []
    for line in text.splitlines():
        match = FIT_RE.search(line)
        if match and match.group("field") == gain_calibrator_name:
            fits.append(match.groupdict())
        model = parse_setjy_line(line, gain_calibrator_name)
        if model is not None:
            model.update(source_file=str(source_file),
                         source_stage=_source_stage(Path(source_file)) if source_file else None)
            models.append(model)
    return models, fits


def find_flux_estimate(download_root, gain_calibrator_name, *, selected_spw=None, spw_center_ghz=None, band=None):
    """Schema-2 estimate for one extracted SPW from every retained pipeline log under download_root."""
    models, fits = [], []
    for path in _candidate_files(download_root):
        try:
            text = path.read_text(errors="replace")
        except OSError:
            continue
        found, fit = parse_flux_text(text, gain_calibrator_name, source_file=path)
        models += found
        fits += fit
    return build_estimate(models, fits, gain_calibrator_name, selected_spw=selected_spw,
                          spw_center_ghz=spw_center_ghz, band=band)


def write_flux_estimate(result, path):
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(result, indent=2) + "\n")


def recheck(entry_dir, logs_root=None):
    """Rebuild one extracted entry's schema-2 sidecar (returned; the caller writes it)."""
    entry_dir = Path(entry_dir)
    metadata = json.loads((entry_dir / "extraction_metadata.json").read_text())
    previous_path = entry_dir / "flux_estimate.json"
    previous = json.loads(previous_path.read_text()) if previous_path.is_file() else None
    # A repeated recheck must not erase a validated model after its download logs
    # have been removed. Re-read logs when supplied; otherwise retain the result
    # only while it still describes the same extracted field/SPW/frequency.
    if (previous and previous.get("schema") == SCHEMA and previous.get("status") == "available"
            and not (logs_root is not None and Path(logs_root).is_dir())
            and all(previous.get(key) == metadata.get(key)
                    for key in ("gain_calibrator_name", "selected_spw", "spw_center_ghz"))):
        return previous
    if previous and previous.get("schema") == SCHEMA:
        previous = previous.get("previous")
    field = metadata["gain_calibrator_name"]
    kwargs = dict(selected_spw=metadata.get("selected_spw"), spw_center_ghz=metadata.get("spw_center_ghz"))
    if logs_root is not None and Path(logs_root).is_dir():
        result = find_flux_estimate(logs_root, field, **kwargs)
        result["logs_root"] = str(logs_root)
    else:
        line = (previous or {}).get("source_text") or ""
        model = parse_setjy_line(line, field)
        models = [] if model is None else [dict(model, source_file=previous.get("source_file"),
                                                 source_stage=previous.get("source_stage"))]
        result = build_estimate(models, [], field, recovered_from="source_text", ambiguity_checked=False, **kwargs)
        if result["status"] == "unavailable" and models and model_problem(models[0]) is None:
            result.update(status="needs_logs", reason="saved line does not prove SPW coverage; recheck with retained logs")
        result["fit_snr"] = (previous or {}).get("fit_snr") if result["status"] == "available" else None
    result["previous"] = previous
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("recheck", help="Rewrite schema-2 flux sidecars of extracted entries")
    p.add_argument("entries", nargs="+", type=Path, help="Folders holding extraction_metadata.json")
    p.add_argument("--downloads-root", type=Path, help="Retained logs at <downloads-root>/<entry_id>/")
    p.add_argument("--dry-run", action="store_true", help="Report without writing")
    args = parser.parse_args(argv)
    counts = {}
    for entry in args.entries:
        entry_id = json.loads((entry / "extraction_metadata.json").read_text())["entry_id"]
        logs = args.downloads_root / entry_id if args.downloads_root else None
        result = recheck(entry, logs)
        counts[result["status"]] = counts.get(result["status"], 0) + 1
        print("%-12s %-12s %s %s" % (result["status"], result["recovered_from"], entry, result["reason"] or ""))
        if not args.dry_run:
            write_flux_estimate(result, entry / "flux_estimate.json")
    print("SUMMARY", json.dumps(counts, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
